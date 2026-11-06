package io.signalhub;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.time.OffsetDateTime;
import java.util.*;
public final class Contracts {
    public record Profile(
        @NotNull @Size(max=100) List<@NotNull @Size(max=80) String> skills,
        @NotNull @Size(max=100) List<@NotNull @Size(max=80) String> learningSkills,
        @NotNull @Size(max=30) List<@NotNull @Size(max=100) String> cities,
        @NotNull @Size(max=30) List<@NotNull @Size(max=100) String> roles,
        @NotNull @Size(max=20) List<@NotNull String> companyTypes,
        @NotNull @Size(max=30) List<@NotNull @Size(max=100) String> excludedTerms,
        @Pattern(regexp="high_school|associate|bachelor|master|doctor") String education,
        @Min(2000) @Max(2100) Integer graduationYear,
        boolean hardCity,
        @Size(max=200) String major,
        @Min(1) @Max(7) Integer availableDays,
        @Min(1) @Max(60) Integer availableMonths,
        @Size(max=20) List<@NotNull String> internshipTypes,
        @DecimalMin("0") Double minimumSalary,
        @Pattern(regexp="day|month|year|hour") String salaryPeriod,
        @Pattern(regexp="[A-Z]{3}") String salaryCurrency,
        Boolean currentlyStudying,
        Boolean hasInternshipExperience,
        @DecimalMin("0") @DecimalMax("60") Double workExperienceYears,
        @Size(max=4) List<@NotNull @Pattern(regexp="internship|campus|full_time|other") String> employmentTypes,
        java.time.LocalDate internshipStartFrom, java.time.LocalDate internshipStartTo,
        @NotNull @Size(min=4,max=5) Map<String,@NotNull @Min(0) @Max(100) Integer> weights
    ) {
        public void validateWeights() {
            if(internshipStartFrom!=null && internshipStartTo!=null && internshipStartFrom.isAfter(internshipStartTo))
                throw new IllegalArgumentException("期望实习开始窗口起日不能晚于止日");
            if(!(weights.keySet().equals(Set.of("role","skills","city","company")) || weights.keySet().equals(Set.of("role","skills","city","company","qualifications"))) || weights.values().stream().mapToInt(Integer::intValue).sum()==0)
                throw new IllegalArgumentException("权重需包含role/skills/city/company，可加qualifications，且总和大于零");
        }
    }
    public record Salary(
        @DecimalMin("0") Double minimum, @DecimalMin("0") Double maximum,
        @Pattern(regexp="[A-Z]{3}") String currency,
        @Pattern(regexp="day|month|year|hour") String period,
        @Min(1) @Max(24) Integer months, @Size(max=2000) String raw
    ) {
        @com.fasterxml.jackson.annotation.JsonIgnore
        @AssertTrue public boolean isRangeValid() {return minimum==null || maximum==null || minimum<=maximum;}
    }
    public record Skill(@NotBlank @Size(max=100) String name,
        @Pattern(regexp="required|preferred|mentioned") String requirement,
        @NotBlank @Size(max=200000) String evidence) {}
    public record Location(@Size(max=300) String name,@Size(max=100) String country,
        @Size(max=100) String province,@Size(max=100) String city,boolean primary) {}
    public record ExperienceRequirement(
        @DecimalMin("0") @DecimalMax("60") Double minimum_years,
        @DecimalMin("0") @DecimalMax("60") Double maximum_years,
        @NotNull @Pattern(regexp="required|preferred") String requirement,
        @NotNull @Pattern(regexp="work|related|unspecified") String scope,
        @NotBlank @Size(max=200000) String evidence) {
        @com.fasterxml.jackson.annotation.JsonIgnore
        @AssertTrue public boolean isRangeValid() {
            return (minimum_years!=null || maximum_years!=null)
                && (minimum_years==null || maximum_years==null || minimum_years<=maximum_years);
        }
    }
    public record SkillGroup(@NotNull @Size(min=2,max=30) List<@NotBlank @Size(max=100) String> names,
        @NotNull @Min(1) Integer minimum,
        @NotNull @Pattern(regexp="required|preferred") String requirement,
        @NotBlank @Size(max=200000) String evidence) {
        @com.fasterxml.jackson.annotation.JsonIgnore
        @AssertTrue public boolean isCountValid() {
            return names!=null && minimum!=null && minimum<=names.size() && names.stream().noneMatch(Objects::isNull)
                && names.stream().map(n->n.trim().toLowerCase(Locale.ROOT)).distinct().count()==names.size();
        }
    }
    public record ManualItem(
        @NotBlank @Pattern(regexp="job|opportunity|release") String kind,
        @NotBlank @Size(max=300) String external_id,
        @NotBlank @Size(max=500) String title,
        @Size(max=2000) String url, @Size(max=200000) String body,
        @Size(max=200) String company,
        @Pattern(regexp="central_state|local_state|private|foreign|joint_venture|finance|public_institution|research|other|unknown") String company_type,
        @Size(max=100) String country, @Size(max=100) String province, @Size(max=100) String city,
        @Size(max=100) List<@NotNull @Valid Location> locations,
        Boolean remote, @Size(max=30) List<@NotBlank @Size(max=100) String> categories,
        @Pattern(regexp="internship|campus|full_time|other") String employment_type,
        @Size(max=100) String internship_type, @Size(max=100) String recruitment_batch,
        @Pattern(regexp="high_school|associate|bachelor|master|doctor") String education,
        @Min(2000) @Max(2100) Integer graduation_year,
        @Size(max=101) List<@NotNull @Min(2000) @Max(2100) Integer> graduation_years,
        Boolean student_required,
        OffsetDateTime published_at, java.time.LocalDate deadline, java.time.LocalDate application_start,
        @Size(max=100) List<@NotNull @Valid Skill> skills, @Valid Salary salary,
        @Size(max=100) List<@NotNull @Valid SkillGroup> skill_groups,
        @Size(max=100) List<@NotBlank @Size(max=200000) String> unparsed_skill_conditions,
        @Size(max=100) List<@NotNull @Valid ExperienceRequirement> experience_requirements,
        @Size(max=100) List<@NotBlank @Size(max=200000) String> qualification_review_notes,
        @Min(1) @Max(7) Integer days_per_week, @Min(1) @Max(60) Integer duration_months,
        @Size(max=200000) String bachelor_student_evidence,
        Boolean accepts_bachelor, Boolean accepts_other_major, Boolean conversion, Boolean experience_required,
        @Size(max=2000) String major, @Size(max=2000) String language, @Size(max=100) String status,
        java.time.LocalDate start_date, java.time.LocalDate end_date,
        @Size(max=2000) String total_cost, @Size(max=2000) String funding, @Size(max=2000) String eligibility,
        @Size(max=30) List<@NotNull @Size(max=2000) String> risk_notes, @Size(max=100) String version_tag,
        @jakarta.validation.constraints.PastOrPresent OffsetDateTime source_verified_at,
        @Size(max=2000) String source_verification_note,
        boolean is_demo
    ) {
        @com.fasterxml.jackson.annotation.JsonIgnore
        @AssertTrue public boolean isDateRangeValid() {
            return (application_start==null || deadline==null || !application_start.isAfter(deadline))
                && (start_date==null || end_date==null || !start_date.isAfter(end_date));
        }
        @com.fasterxml.jackson.annotation.JsonIgnore
        @AssertTrue public boolean isCohortValid() {
            return graduation_year==null || graduation_years==null || graduation_years.isEmpty()
                || graduation_years.equals(List.of(graduation_year));
        }
    }
    public record ImportRequest(@Positive long sourceId, @NotEmpty @Size(max=1000) List<@NotNull @Valid ManualItem> records) {}
    public record SourceRequest(@NotBlank @Size(max=100) String name, @Pattern(regexp="manual|github|greenhouse|rss|ashby|smartrecruiters|lever") @NotNull String adapter, @NotNull Map<String,Object> config, boolean enabled) {}
    public record Subscription(@NotBlank @Size(max=100) String name,@NotNull Map<String,Object> rules,boolean enabled) {}
    public record Application(@NotNull @Pattern(regexp="interested|saved|preparing|applied|assessment|interview1|interview_next|offer|rejected|closed") String status,@Size(max=5000) String notes, OffsetDateTime appliedAt,OffsetDateTime assessmentAt,OffsetDateTime interviewAt,@Size(max=500) String nextAction) {
        public Application(String status,String notes,OffsetDateTime appliedAt,OffsetDateTime assessmentAt,OffsetDateTime interviewAt) {
            this(status,notes,appliedAt,assessmentAt,interviewAt,null);
        }
    }
}
