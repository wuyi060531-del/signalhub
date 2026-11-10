package io.signalhub;
import java.util.*;

final class QualificationRules {
    record Check(String key,String label,String status,Object sourceValue,Object profileValue,String evidence,String reason) {}
    record Evaluation(List<Check> checks,boolean conflict,boolean unknown,double ratio) {}
    private static final List<String> DEGREES=List.of("high_school","associate","bachelor","master","doctor");
    static String norm(String s) {return s.toLowerCase(Locale.ROOT).replace("-"," ").replaceAll("\\s+"," ").trim().replace("springboot","spring boot");}
    static List<String> cities(Map<String,Object> item) {
        var result=new ArrayList<String>();String city=Json.string(item,"city");if(city!=null)result.add(city);
        if(item.get("locations") instanceof List<?> places)for(Object value:places) {String c=Json.string(Json.map(value),"city");if(c!=null)result.add(c);}
        return result;
    }
    // 明确等价的城市写法（重庆/重庆市/Chongqing）视为同一城市；其余仍按原有规范化全等比较，不做推断。
    private static String cityKey(String s) {String city=CityNames.canonical(s);return city!=null?city:norm(s);}
    static boolean cityMatch(List<String> targets,List<String> locations) {return targets.stream().anyMatch(x->locations.stream().anyMatch(y->cityKey(x).equals(cityKey(y))));}
    static Evaluation evaluate(Map<String,Object> item,Map<String,Object> profile) {
        var checks=new ArrayList<Check>();
        List<String> employment=Json.strings(profile.get("employmentTypes"));
        String actualEmployment=Json.string(item,"employment_type");
        if(!employment.isEmpty()) {
            String s=actualEmployment==null?"unconfirmed":employment.contains(actualEmployment)?"confirmed":"conflict";
            checks.add(new Check("employment_type","招聘类型",s,actualEmployment,employment,null,s.equals("confirmed")?"招聘类型符合档案":s.equals("conflict")?"岗位不是档案所选招聘类型":"招聘类型未知，不能当作实习"));
        }
        String edu=Json.string(item,"education"),personal=Json.string(profile,"education");
        String status=edu==null||personal==null||!DEGREES.contains(edu)||!DEGREES.contains(personal)?"unconfirmed":DEGREES.indexOf(personal)<DEGREES.indexOf(edu)?"conflict":"confirmed";
        if(edu==null && "bachelor".equals(personal) && MatchingEngine.bachelorStatus(item).equals("confirmed"))status="confirmed";
        checks.add(new Check("education","最低学历",status,edu,personal,null,status.equals("confirmed")?(edu==null?"原文明示本科在读申请路径；未推断唯一最低学历":"满足已知最低学历"):status.equals("conflict")?"学历低于明确最低要求":"学历要求或个人学历尚未确认"));
        if(item.get("bachelor_student_evidence")!=null && !Boolean.TRUE.equals(item.get("student_required")) && "bachelor".equals(personal)) {
            String s=Boolean.TRUE.equals(profile.get("currentlyStudying"))?"confirmed":"unconfirmed";
            checks.add(new Check("bachelor_student_route","本科在读申请路径",s,item.get("bachelor_student_evidence"),profile.get("currentlyStudying"),Json.string(item,"bachelor_student_evidence"),s.equals("confirmed")?"档案在读状态与原文明示本科路径一致":"未确认通过本科在读路径满足资格；替代工作经验路径需另外核验"));
        }
        var cohorts=new ArrayList<Integer>();
        if(item.get("graduation_years") instanceof List<?> list)for(Object value:list)if(value instanceof Number n)cohorts.add(n.intValue());
        if(cohorts.isEmpty() && item.get("graduation_year") instanceof Number n)cohorts.add(n.intValue());
        Integer year=Json.number(profile.get("graduationYear"));
        status=cohorts.isEmpty()||year==null?"unconfirmed":cohorts.contains(year)?"confirmed":"conflict";
        checks.add(new Check("graduation","招聘届别",status,cohorts,year,null,status.equals("confirmed")?"预计毕业年份属于明确招聘届别："+cohorts:status.equals("conflict")?"招聘届别与档案不一致："+cohorts:"招聘届别或预计毕业年份未知"));
        for(var pair:Map.of("student_required","currentlyStudying","experience_required","hasInternshipExperience").entrySet())if(Boolean.TRUE.equals(item.get(pair.getKey()))) {
            String label=pair.getKey().equals("student_required")?"在读资格":"相关实习经历";
            Object value=profile.get(pair.getValue());status=Boolean.TRUE.equals(value)?"confirmed":Boolean.FALSE.equals(value)?"conflict":"unconfirmed";
            checks.add(new Check(pair.getKey(),label,status,true,value,null,status.equals("confirmed")?"档案确认满足"+label:status.equals("conflict")?"不满足原文明示的"+label:label+"在档案中尚未确认"));
        }
        if(Boolean.FALSE.equals(item.get("accepts_bachelor")) && "bachelor".equals(personal))checks.add(new Check("bachelor_exclusion","本科限制","conflict",false,personal,null,"原文明确不接受本科生"));
        String major=Json.string(item,"major"),ownMajor=Json.string(profile,"major");
        if(major!=null && !Boolean.TRUE.equals(item.get("accepts_other_major"))) {
            boolean exact=ownMajor!=null && norm(major).equals(norm(ownMajor)) && !major.matches(".*(?:或|/|相关|(?i:or|degree)).*");
            checks.add(new Check("major","专业条件",exact?"confirmed":"unconfirmed",major,ownMajor,major,exact?"专业与明确要求文本一致":"专业条件需核验原文，未把相关专业或中英文名称强行判为符合/不符合："+major));
        }
        for(String evidence:Json.strings(item.get("qualification_review_notes")))checks.add(new Check("qualification_review","替代资格或冲突","unconfirmed",null,null,evidence,"资格条件需人工复核（替代资格或实习与经验年数冲突）："+evidence));
        if(item.get("experience_requirements") instanceof List<?> requirements)for(Object value:requirements) {
            var c=Json.map(value);boolean preferred="preferred".equals(c.get("requirement"));
            Double min=c.get("minimum_years") instanceof Number n?n.doubleValue():null,max=c.get("maximum_years") instanceof Number n?n.doubleValue():null;
            Double years=profile.get("workExperienceYears") instanceof Number n?n.doubleValue():null;
            String evidence=Objects.toString(c.get("evidence"),"");String reason;
            if(!"work".equals(c.get("scope"))) {status="unconfirmed";reason="经验的领域/口径需核验，总工作年数不替代相关经历："+evidence;}
            else if(years==null) {status="unconfirmed";reason="工作年数在档案中尚未确认："+evidence;}
            else if((min!=null && years<min)||(max!=null && years>max)) {status=preferred?"not_applicable":"conflict";reason="未满足明确工作经验年数边界："+evidence;}
            else {status="confirmed";reason="工作年数满足数值条件；仍须核验经历口径："+evidence;}
            if(preferred)status="not_applicable";
            checks.add(new Check("experience",preferred?"经验加分（不作硬门槛）":"工作经验",status,c,years,evidence,reason));
        }
        List<String> targets=Json.strings(profile.get("cities")),locations=cities(item);
        if(Boolean.TRUE.equals(profile.get("hardCity")) && !targets.isEmpty()) {
            boolean unknownPlace=locations.isEmpty();
            if(item.get("locations") instanceof List<?> places)for(Object value:places)if(Json.map(value).get("city")==null)unknownPlace=true;
            status=cityMatch(targets,locations)?"confirmed":unknownPlace?"unconfirmed":"conflict";
            checks.add(new Check("hardCity","硬性城市限制",status,locations,targets,null,status.equals("confirmed")?"符合硬性城市限制":status.equals("conflict")?"不符合硬性城市限制":"部分地点或城市未知，暂不排除"));
        }
        for(String key:List.of("days_per_week","duration_months")) {
            Integer demand=Json.number(item.get(key)),available=Json.number(profile.get(key.equals("days_per_week")?"availableDays":"availableMonths"));
            if(demand==null && !"internship".equals(item.get("employment_type")))continue;
            if(demand!=null||available!=null) {
                status=demand==null||available==null?"unconfirmed":available<demand?"conflict":"confirmed";
                checks.add(new Check(key,key.equals("days_per_week")?"每周实习时间":"实习持续月数",status,demand,available,null,status.equals("confirmed")?"满足明确实习时间要求":status.equals("conflict")?"无法满足明确的实习时间要求":"明确实习时间要求或个人可用时间尚未确认"));
            }
        }
        String body=(Objects.toString(item.get("title"),"")+" "+Objects.toString(item.get("body"),"")).toLowerCase(Locale.ROOT);
        for(String term:Json.strings(profile.get("excludedTerms")))if(!term.isBlank()&&body.contains(term.toLowerCase(Locale.ROOT)))checks.add(new Check("excluded","个人排除条件","conflict",term,term,null,"命中排除条件："+term));
        if(profile.get("minimumSalary") instanceof Number min && min.doubleValue()>0) {
            var salary=Json.map(item.get("salary"));
            boolean comparable=Objects.equals(profile.get("salaryPeriod"),salary.get("period"))&&Objects.equals(profile.get("salaryCurrency"),salary.get("currency"))&&salary.get("minimum") instanceof Number;
            status=!comparable?"unconfirmed":((Number)salary.get("minimum")).doubleValue()<min.doubleValue()?"conflict":"confirmed";
            checks.add(new Check("salary","最低薪资",status,salary,min,salary.get("raw") instanceof String s?s:null,!comparable?"薪资周期、币种或金额未知/不同，未直接比较":status.equals("conflict")?"明确薪资下限低于预期":"相同币种和周期下满足薪资下限"));
        }
        if("internship".equals(actualEmployment)) {
            List<String> types=Json.strings(profile.get("internshipTypes"));
            String actual=Json.string(item,"internship_type");
            if(!types.isEmpty()) {
                status=actual==null?"unconfirmed":types.contains(actual)?"confirmed":"conflict";
                checks.add(new Check("internship_type","实习类型",status,actual,types,null,actual==null?"实习类型未确认":status.equals("confirmed")?"实习类型符合档案":"实习类型与档案不符"));
            }
            String from=Json.string(profile,"internshipStartFrom"),to=Json.string(profile,"internshipStartTo");
            if(from!=null || to!=null) {
                String start=Json.string(item,"start_date");
                status=start==null?"unconfirmed":(from!=null && start.compareTo(from)<0)||(to!=null && start.compareTo(to)>0)?"conflict":"confirmed";
                checks.add(new Check("internship_start","期望实习开始窗口",status,start,Arrays.asList(from,to),null,start==null?"官方到岗日期未知；发布日期、招聘届别和全年招聘不等于可于期望时间入职":status.equals("confirmed")?"明确到岗日期位于档案期望窗口":"明确到岗日期不在档案期望窗口"));
            }
        }
        long eligible=checks.stream().filter(c->c.status().equals("confirmed")).count(),count=checks.stream().filter(c->!c.status().equals("not_applicable")).count();
        return new Evaluation(checks,checks.stream().anyMatch(c->c.status().equals("conflict")),checks.stream().anyMatch(c->c.status().equals("unconfirmed")),count==0?0:(double)eligible/count);
    }
}
