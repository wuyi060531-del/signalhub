package io.signalhub;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
class MatchingEngineTest {
    @Test void officialTechnicalTitlesAreRecognizedWithoutUsingCompanyAdvertising() {
        for(String title:List.of("AI Infra多模态数据理解方向研发实习生","智能体算法实习生","文本大模型算法实习生"))
            assertThat(RoleClassifier.assess(Map.of("title",title)).categories()).contains("ai");
        assertThat(RoleClassifier.assess(Map.of("title","RDS数据库管控平台开发实习生")).categories()).contains("data_engineering");
        for(String title:List.of("大模型销售实习生","智能体产品运营实习生","市场实习生"))
            assertThat(RoleClassifier.assess(Map.of("title",title,"body","公司开发大模型和智能体算法，拥有数据库开发团队")).categories()).isEmpty();
    }
    private final MatchingEngine engine=new MatchingEngine();
    private Map<String,Object> profile() {return new HashMap<>(Map.of("skills",List.of("python","SQL"),"education","bachelor","graduationYear",2027,"cities",List.of("上海"),"roles",List.of("data_engineering"),"companyTypes",List.of("foreign"),"weights",Map.of("role",30,"skills",40,"city",15,"company",15)));}
    private Map<String,Object> job() {var j=new HashMap<String,Object>(Map.of("title","数据工程实习","education","bachelor","graduation_year",2027,"city","上海","categories",List.of("data_engineering"),"company_type","foreign","skills",List.of(Map.of("name","Python"),Map.of("name","SQL"),Map.of("name","Spark"),Map.of("name","Airflow"))));j.put("body","数据工程实习，职责是设计和开发数据管道。2027届本科，Python、SQL、Spark和Airflow。此为明确的合成测试正文。");j.put("company_type_verified",true);return j;}
    @Test void explainedWeightedMatch() {var r=engine.match(job(),profile());assertThat(r.hardStatus()).isEqualTo("eligible");assertThat(r.score()).isEqualTo(82.61);assertThat(r.matchedSkills()).containsExactly("Python","SQL");assertThat(r.unconfirmedSkills()).containsExactly("Spark","Airflow");}
    @Test void unknownMustNotReject() {var j=job();j.remove("graduation_year");j.remove("education");assertThat(engine.match(j,profile()).hardStatus()).isEqualTo("insufficient_information");}
    @Test void explicitMinimumEducationAndCohortReject() {var j=job();j.put("education","master");assertThat(engine.match(j,profile()).hardStatus()).isEqualTo("not_eligible");j=job();j.put("graduation_year",2028);assertThat(engine.match(j,profile()).hardStatus()).isEqualTo("not_eligible");}
    @Test void hardCityAndTime() {var p=profile();p.put("hardCity",true);var j=job();j.put("city","北京");assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");j.remove("city");assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");p.put("availableDays",3);j.put("days_per_week",5);assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");}
    @Test void salaryPeriodsNeverCompared() {var p=profile();p.putAll(Map.of("minimumSalary",5000,"salaryPeriod","month","salaryCurrency","CNY"));var j=job();j.put("salary",Map.of("minimum",200,"period","day","currency","CNY"));var r=engine.match(j,p);assertThat(r.hardStatus()).isEqualTo("insufficient_information");assertThat(r.reasons()).anyMatch(x->x.contains("未直接比较"));}
    @Test void explicitBachelorExclusionAndExcludedTerm() {var j=job();j.put("accepts_bachelor",false);assertThat(engine.match(j,profile()).hardStatus()).isEqualTo("not_eligible");var p=profile();p.put("excludedTerms",List.of("实习"));assertThat(engine.match(job(),p).hardStatus()).isEqualTo("not_eligible");}

    @Test void secondaryCityMatchesAndUnconfirmedPlaceDoesNotReject() {
        var j=job();j.put("city","Singapore");j.put("locations",List.of(Map.of("country","CN","city","上海")));
        var p=profile();p.put("hardCity",true);
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
        assertThat(engine.match(j,p).components().get("city")).isEqualTo(1.0);
        j.put("locations",List.of(Map.of("name","城市待公布")));
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");
    }

    @Test void requiredGroupDoesNotDemandEveryAlternativeAndIndependentSqlRemainsRequired() {
        var j=job();j.put("skills",List.of(Map.of("name","Python","requirement","mentioned"),Map.of("name","Java","requirement","mentioned"),Map.of("name","SQL","requirement","required"),Map.of("name","Spark","requirement","preferred")));
        j.put("skill_groups",List.of(Map.of("names",List.of("Python","Java"),"minimum",1,"requirement","required","evidence","Python或Java任选一项")));
        var r=engine.match(j,profile());
        assertThat(r.hardStatus()).isEqualTo("eligible");
        assertThat(r.unconfirmedSkills()).containsExactly("Spark");
        assertThat(r.components().get("skills")).isEqualTo(0.8);
        assertThat(r.skillConditions().getFirst().status()).isEqualTo("satisfied");
        var p=profile();p.put("skills",List.of("Python"));
        r=engine.match(j,p);assertThat(r.hardStatus()).isEqualTo("insufficient_information");
        assertThat(r.reasons()).anyMatch(x->x.contains("必备技能 SQL"));
        assertThat(r.score()).isLessThan(100);
    }
    @Test void twoOfThreeCountsAndLearningSkillDoesNotSatisfyRequiredCondition() {
        var j=job();j.put("skills",List.of(Map.of("name","Python","requirement","mentioned"),Map.of("name","Java","requirement","mentioned"),Map.of("name","SQL","requirement","mentioned")));
        j.put("skill_groups",List.of(Map.of("names",List.of("Python","Java","SQL"),"minimum",2,"requirement","required","evidence","任意两种")));
        assertThat(engine.match(j,profile()).hardStatus()).isEqualTo("eligible");
        assertThat(engine.match(j,profile()).components().get("skills")).isEqualTo(1);
        var p=profile();p.put("skills",List.of("Python"));p.put("learningSkills",List.of("Java","SQL"));
        var r=engine.match(j,p);assertThat(r.hardStatus()).isEqualTo("insufficient_information");
        assertThat(r.components().get("skills")).isEqualTo(0.5);
        assertThat(r.reasons()).anyMatch(x->x.contains("确认 1 项"));
    }
    @Test void multipleCohortsAndExplicitStudentExperienceUseThreeStates() {
        var j=job();j.remove("graduation_year");j.put("graduation_years",List.of(2026,2027));
        j.put("student_required",true);j.put("experience_required",true);
        var p=profile();assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");
        p.put("currentlyStudying",true);p.put("hasInternshipExperience",true);
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
        p.put("currentlyStudying",false);assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");
        p.put("currentlyStudying",true);p.put("graduationYear",2028);assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");
    }
    @Test void emptyProfileCannotReceiveSkillCreditAndMentionsDoNotDiluteRequiredScore() {
        var j=job();j.put("skills",List.of(Map.of("name","Python","requirement","required"),Map.of("name","Java","requirement","mentioned")));
        var r=engine.match(j,new HashMap<>());assertThat(r.hardStatus()).isEqualTo("insufficient_information");assertThat(r.score()).isZero();
        assertThat(engine.match(j,profile()).components().get("skills")).isEqualTo(1);
        assertThat(engine.match(j,profile()).hardStatus()).isEqualTo("eligible");
    }
    @Test void unresolvedBooleanRequirementCannotClaimEligibility() {
        var j=job();j.put("unparsed_skill_conditions",List.of("Required: one of Rust, Python, Java"));
        var r=engine.match(j,profile());assertThat(r.hardStatus()).isEqualTo("insufficient_information");
        assertThat(r.reasons()).anyMatch(x->x.contains("尚未完整解析"));
    }
    @Test void generalWorkExperienceUsesUnknownLowerUpperAndPreferredStates() {
        var j=job();j.put("experience_requirements",List.of(Map.of("minimum_years",0,"maximum_years",2,"scope","work","requirement","required","evidence","工作经验：0-2年")));
        var p=profile();assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");
        p.put("workExperienceYears",0);assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
        p.put("workExperienceYears",2.5);assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");
        j.put("experience_requirements",List.of(Map.of("minimum_years",3,"scope","work","requirement","preferred","evidence","3年工作经验优先")));
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
        j.put("experience_requirements",List.of(Map.of("minimum_years",3,"scope","work","requirement","required","evidence","至少3年工作经验")));
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");
    }
    @Test void domainYearsAlternativeDegreeAndMajorCannotBeAssumedSatisfied() {
        var j=job();var p=profile();p.put("workExperienceYears",10);
        j.put("experience_requirements",List.of(Map.of("minimum_years",5,"scope","related","requirement","required","evidence","5+ years in software")));
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");
        j.remove("experience_requirements");j.put("qualification_review_notes",List.of("degree or equivalent work experience"));
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");
        j.remove("qualification_review_notes");j.put("major","计算机科学或相关专业");p.put("major","计算机科学");
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");
        j.put("major","计算机科学");assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
    }
    @Test void explicitInternshipScheduleNeedsProfileAvailability() {
        var j=job();j.put("days_per_week",3);j.put("duration_months",6);
        var p=profile();assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");
        p.put("availableDays",3);p.put("availableMonths",6);assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
        p.put("availableMonths",5);assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");
    }
    @Test void availabilityAndEducationAloneCannotCreateRecommendationWithoutCoreProfile() {
        var p=profile();p.put("skills",List.of());p.put("roles",List.of());p.put("availableDays",5);
        var j=job();j.put("days_per_week",3);
        var r=engine.match(j,p);assertThat(r.score()).isZero();assertThat(r.adjustments()).anyMatch(a->a.code().equals("profile_unconfirmed"));consistent(r);
    }
    private void consistent(MatchingEngine.Result result) {
        assertThat(result.breakdown().stream().mapToDouble(MatchingEngine.ScorePart::maximum).sum()).isCloseTo(100,within(0.01));
        assertThat(result.breakdown().stream().mapToDouble(MatchingEngine.ScorePart::contribution).sum()).isCloseTo(result.baseScore(),within(0.01));
        assertThat(result.baseScore()+result.adjustments().stream().mapToDouble(MatchingEngine.Adjustment::delta).sum()).isCloseTo(result.score(),within(0.01));
        assertThat(result.score()).isBetween(0.0,100.0);
    }
    @Test void nontechnicalTitlesCannotBorrowAiCompanyDescriptionOrLocationToGetRecommended() {
        var j=job();j.put("title","Account Manager");j.put("body","We build AI, Python and Java products. Our data engineering team is world class. This role sells customer accounts.");
        var result=engine.match(j,profile());assertThat(result.score()).isLessThanOrEqualTo(10);
        assertThat(result.roleAssessment().kind()).isEqualTo("non_target");consistent(result);
        j.put("title","Human Resources Coordinator");assertThat(engine.match(j,profile()).score()).isLessThanOrEqualTo(10);
    }
    @Test void salesforceTechnicalTitlesAndResponsibilitiesAreNotSalesJobs() {
        var j=job();j.put("title","Salesforce Data Engineer");
        var result=engine.match(j,profile());
        assertThat(result.roleAssessment().kind()).isEqualTo("technical");
        assertThat(result.targetDirection()).isTrue();assertThat(result.score()).isGreaterThan(10);
        j.put("title","Salesforce Software Engineer");
        assertThat(engine.match(j,profile()).roleAssessment().categories()).contains("software");
        j.put("title","Platform Intern");
        j.put("body","You will develop Salesforce data pipelines and data warehouse integrations. Required Python and SQL; 2027 bachelor students.");
        assertThat(engine.match(j,profile()).targetDirection()).isTrue();
        for(String title:List.of("Sales Engineer","Sales Manager","Presales Engineer","Salesforce Sales Manager")) {
            j.put("title",title);result=engine.match(j,profile());
            assertThat(result.roleAssessment().kind()).as(title).isEqualTo("non_target");
            assertThat(result.score()).as(title).isLessThanOrEqualTo(10);
        }
    }
    @Test void hardConflictIsZeroEvenWhenEverySoftPreferenceMatchesAndUnknownsDoNotGetFullQualificationCredit() {
        var j=job();j.put("education","master");var result=engine.match(j,profile());
        assertThat(result.hardStatus()).isEqualTo("not_eligible");assertThat(result.score()).isZero();assertThat(result.adjustments()).anyMatch(a->a.code().equals("hard_conflict"));consistent(result);
        j.remove("education");j.remove("graduation_year");result=engine.match(j,profile());
        assertThat(result.qualifications()).filteredOn(c->c.status().equals("unconfirmed")).hasSize(2);
        assertThat(result.components().get("qualifications")).isZero();consistent(result);
    }
    @Test void missingJdAndUnsupportedDirectionAreExplicitAndSkillNegationDoesNotDemandPython() {
        var j=job();j.put("body","");var result=engine.match(j,profile());
        assertThat(result.score()).isLessThanOrEqualTo(20);assertThat(result.nextSteps()).contains("打开官方来源补充完整JD");consistent(result);
        j=job();j.put("skills",List.of(Map.of("name","Python","requirement","required","evidence","Python is not required.")));
        result=engine.match(j,profile());assertThat(result.components().get("skills")).isZero();
        assertThat(result.skillConditions().getFirst().status()).isEqualTo("not_required");consistent(result);
    }
    @Test void confirmedDirectionAndCoreSkillsBeatMatchingCityOnlyAndConfiguredWeightsRemainVisible() {
        var technical=engine.match(job(),profile());var unrelated=job();unrelated.put("title","Administrative Assistant");
        assertThat(technical.score()).isGreaterThan(engine.match(unrelated,profile()).score());consistent(technical);
        var p=profile();p.put("weights",Map.of("role",40,"skills",40,"city",5,"company",0,"qualifications",15));
        var adjusted=engine.match(job(),p);consistent(adjusted);
        assertThat(adjusted.breakdown()).filteredOn(c->c.key().equals("company")).allMatch(c->c.maximum()==0);
        assertThat(adjusted.components().get("role")).isEqualTo(1);
    }

    @Test void editableEmploymentAndInternshipTypesHaveThreeStates() {
        var p=profile();p.put("employmentTypes",List.of("internship"));p.put("internshipTypes",List.of("日常","长期"));
        var j=job();j.put("employment_type","full_time");
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");
        j.remove("employment_type");assertThat(engine.match(j,p).hardStatus()).isEqualTo("insufficient_information");
        j.put("employment_type","internship");j.put("internship_type","暑期");
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");
        j.put("internship_type","日常");assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
    }
    @Test void springStartWindowNeverUsesPublicationDateOrCohortAsStartDate() {
        var p=profile();p.put("internshipStartFrom","2027-03-01");p.put("internshipStartTo","2027-05-31");
        var j=job();j.put("employment_type","internship");j.put("published_at","2027-03-01");
        assertThat(engine.match(j,p).qualifications()).anyMatch(c->c.key().equals("internship_start")&&c.status().equals("unconfirmed"));
        for(String day:List.of("2027-03-01","2027-05-31")) {
            j.put("start_date",day);assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
        }
        for(String day:List.of("2026-03-01","2027-02-28","2027-06-01")) {
            j.put("start_date",day);assertThat(engine.match(j,p).hardStatus()).isEqualTo("not_eligible");
        }
        j.remove("start_date");p.remove("internshipStartFrom");p.remove("internshipStartTo");
        assertThat(engine.match(j,p).hardStatus()).isEqualTo("eligible");
    }
    @Test void minimumDegreeDoesNotConfirmBachelorStudentAcceptance() {
        var j=job();assertThat(engine.match(j,profile()).bachelorStatus()).isEqualTo("unconfirmed");
        j.put("student_required",true);assertThat(engine.match(j,profile()).bachelorStatus()).isEqualTo("confirmed");
        j.remove("education");j.put("accepts_bachelor",true);assertThat(engine.match(j,profile()).bachelorStatus()).isEqualTo("unconfirmed");
        j.put("education","master");assertThat(engine.match(j,profile()).bachelorStatus()).isEqualTo("excluded");
        j.put("education","bachelor");j.put("accepts_bachelor",false);assertThat(engine.match(j,profile()).bachelorStatus()).isEqualTo("excluded");
    }

    @Test void explicitBachelorPathDoesNotInventMinimumDegreeOrEraseOtherUnknownConditions() {
        var j=job();j.remove("education");j.put("bachelor_student_evidence","Pursuing Bachelor's degree or equivalent work experience");
        j.put("body","Pursuing Bachelor's degree or equivalent work experience; data engineering internship. Required Python.");
        j.put("qualification_review_notes",List.of("Pursuing Bachelor's degree or equivalent work experience"));
        var p=profile();p.put("currentlyStudying",true);
        var result=engine.match(j,p);
        assertThat(result.bachelorStatus()).isEqualTo("confirmed");
        assertThat(result.hardStatus()).isEqualTo("insufficient_information");
        assertThat(result.qualifications()).anyMatch(c->c.key().equals("education")&&c.status().equals("confirmed"));
        p.remove("currentlyStudying");
        assertThat(engine.match(j,p).qualifications()).anyMatch(c->c.key().equals("bachelor_student_route")&&c.status().equals("unconfirmed"));
        j.put("education","master");assertThat(engine.match(j,p).bachelorStatus()).isEqualTo("excluded");
    }
    @Test void applicationEngineerNeedsExplicitPersonalCodingDutiesNotCompanyAiMarketing() {
        var item=new HashMap<String,Object>();
        item.put("title","Application Engineer Intern - 2028 Graduates");
        item.put("body","You'll contribute to AI-enabled application features through coding, testing, and debugging. LLM integration tasks are part of the work.");
        assertThat(RoleClassifier.assess(item).categories()).contains("ai","software");
        for(String body:List.of("We build AI-enabled application features through coding.",
                "You will join an AI-enabled application team.",
                "You'll contribute to AI-enabled application features through customer interviews.")) {
            item.put("body",body);
            assertThat(RoleClassifier.assess(item).categories()).isEmpty();
        }
        item.put("title","Sales Application Engineer");
        item.put("body","You'll contribute to AI-enabled application features through coding.");
        assertThat(RoleClassifier.assess(item).kind()).isEqualTo("non_target");
    }
}
