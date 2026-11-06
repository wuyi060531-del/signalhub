package io.signalhub;
import org.springframework.stereotype.Component;
import java.util.*;
import java.util.regex.Pattern;
@Component
public class MatchingEngine {
    public static final String REVISION="rules-2026-10-25-explicit-ai-application-duties-1";
    public record Result(String hardStatus,double score,List<String> reasons,List<String> matchedSkills,List<String> unconfirmedSkills,
        Map<String,Double> components,List<SkillCondition> skillConditions,List<QualificationRules.Check> qualifications,
        RoleClassifier.Assessment roleAssessment,List<ScorePart> breakdown,double baseScore,List<Adjustment> adjustments,
        String recommendation,List<String> nextSteps,String revision,boolean targetDirection,String bachelorStatus) {}
    public record SkillCondition(List<String> names,int minimum,String requirement,List<String> confirmed,String status,String evidence) {}
    public record ScorePart(String key,String label,double requestedWeight,double maximum,double ratio,double contribution,String status,String reason,List<String> evidence) {}
    public record Adjustment(String code,String reason,double delta) {}
    private static String norm(String s) {return QualificationRules.norm(s);}
    private static double round(double value) {return Math.round(value*100)/100.0;}
    private static boolean notRequired(String name,String evidence) {
        String token=Pattern.quote(name);
        return Pattern.compile(token+"\\s*(?:is|are)?\\s*(?:not required|not necessary)|(?:无需|不要求|不需要)[^；;。]{0,8}"+token,Pattern.CASE_INSENSITIVE).matcher(evidence).find();
    }
    static String bachelorStatus(Map<String,Object> item) {
        if(Boolean.FALSE.equals(item.get("accepts_bachelor")) || Set.of("master","doctor").contains(Objects.toString(item.get("education"),"")))return "excluded";
        // A minimum degree alone does not establish current-student acceptance.
        String evidence=Json.string(item,"bachelor_student_evidence");
        boolean route=evidence!=null && !evidence.isBlank() && Objects.toString(item.get("body"),"").contains(evidence)
            && Pattern.compile("(?:currently\\s+)?pursuing\\s+(?:a\\s+)?bachelor|(?:本科|学士).{0,8}(?:在读|在校)|(?:在读|在校).{0,8}本科",Pattern.CASE_INSENSITIVE).matcher(evidence).find()
            && !Pattern.compile("不接受|不招|无需|不要求|\\bnot\\b|\\bno\\b",Pattern.CASE_INSENSITIVE).matcher(evidence).find();
        return route || "bachelor".equals(item.get("education")) && Boolean.TRUE.equals(item.get("student_required")) ? "confirmed" : "unconfirmed";
    }
    public Result match(Map<String,Object> item,Map<String,Object> profile) {
        var qualifications=QualificationRules.evaluate(item,profile);
        var reasons=new ArrayList<String>();qualifications.checks().forEach(c->reasons.add(c.reason()));
        boolean fail=qualifications.conflict(),unknown=qualifications.unknown();
        for(String evidence:Json.strings(item.get("unparsed_skill_conditions"))) {unknown=true;reasons.add("技能组合尚未完整解析，需核验原文："+evidence);}
        Set<String> confirmed=new HashSet<>(Json.strings(profile.get("skills")).stream().map(MatchingEngine::norm).toList());
        Set<String> matched=new LinkedHashSet<>(),missing=new LinkedHashSet<>(),grouped=new HashSet<>();
        List<SkillCondition> conditions=new ArrayList<>();
        double skillNumerator=0,skillDenominator=0;
        if(item.get("skill_groups") instanceof List<?> groups)for(Object value:groups) {
            var group=Json.map(value);List<String> names=Json.strings(group.get("names"));
            String groupEvidence=Objects.toString(group.get("evidence"),"");
            if(names.stream().anyMatch(name->notRequired(name,groupEvidence))) {
                conditions.add(new SkillCondition(names,0,"not_required",List.of(),"not_required",groupEvidence));continue;
            }
            Integer minimum=Json.number(group.get("minimum"));
            if(minimum==null || minimum<1 || minimum>names.size()) {unknown=true;reasons.add("技能组结构不完整，需核验原文");continue;}
            names.forEach(n->grouped.add(norm(n)));
            List<String> hits=names.stream().filter(n->confirmed.contains(norm(n))).distinct().toList();
            boolean satisfied=hits.size()>=minimum;
            String requirement=Objects.toString(group.get("requirement"),"required");
            double weight=requirement.equals("preferred")?0.5:1;
            skillDenominator+=weight;skillNumerator+=weight*Math.min(1.0,(double)hits.size()/minimum);
            matched.addAll(hits);
            if(!satisfied)names.stream().filter(n->!confirmed.contains(norm(n))).forEach(missing::add);
            conditions.add(new SkillCondition(names,minimum,requirement,hits,satisfied?"satisfied":"unconfirmed",Objects.toString(group.get("evidence"),"")));
            reasons.add((requirement.equals("preferred")?"加分":"必备")+"技能组需至少 "+minimum+" 项 "+names+"；档案确认 "+hits.size()+" 项"+(satisfied?"，已满足":"，尚未确认满足"));
            if(!satisfied && requirement.equals("required"))unknown=true;
        }
        if(item.get("skills") instanceof List<?> skills) for(Object x:skills) {
            var skill=Json.map(x);String name=Json.string(skill,"name");
            if(name==null)continue;
            String requirement=Json.string(skill,"requirement");
            String evidence=Objects.toString(skill.get("evidence"),"");
            if(notRequired(name,evidence)) {
                conditions.add(new SkillCondition(List.of(name),0,"not_required",List.of(),"not_required",evidence));
                reasons.add(name+" 原文明示非必需，不作为必备条件计分");continue;
            }
            boolean hit=confirmed.contains(norm(name));
            if(hit)matched.add(name);
            else if(!grouped.contains(norm(name)) || "required".equals(requirement) || "preferred".equals(requirement))missing.add(name);
            if("mentioned".equals(requirement))continue;
            // 旧 payload 无性质仍兼容原评分，但不将其升级为明示硬条件。
            double weight="preferred".equals(requirement)?0.5:1;
            skillDenominator+=weight;if(hit)skillNumerator+=weight;
            conditions.add(new SkillCondition(List.of(name),1,requirement==null?"legacy":requirement,hit?List.of(name):List.of(),hit?"satisfied":"unconfirmed",Objects.toString(skill.get("evidence"),"")));
            if("required".equals(requirement) && !hit) {unknown=true;reasons.add("必备技能 "+name+" 在档案中尚未确认掌握");}
        }
        if(skillDenominator==0)unknown=true;
        if(confirmed.isEmpty())reasons.add("档案未确认任何已掌握技能，学习中的技能不视为已掌握");
        if(!missing.isEmpty())reasons.add("未匹配技能表示档案尚未确认掌握，并非认定不会");
        var direction=RoleClassifier.assess(item);
        List<String> roles=Json.strings(profile.get("roles"));
        boolean roleHit=!roles.isEmpty() && roles.stream().anyMatch(direction.categories()::contains);
        boolean roleConflict=!roles.isEmpty() && (direction.kind().equals("non_target") || (!direction.categories().isEmpty() && !roleHit && !direction.categories().equals(List.of("software"))));
        double roleRatio=roleHit?1:!roles.isEmpty() && (direction.kind().equals("adjacent")||direction.categories().equals(List.of("software")))?0.25:0;
        String roleReason=roles.isEmpty()?"尚未设置目标岗位方向，不计方向分":roleHit?"标题或明确个人职责符合目标方向："+direction.categories():roleConflict?"岗位方向与目标不符，不能用地点或公司偏好补成高推荐":"岗位方向证据不足或仅属相邻方向，需要核验核心职责";
        reasons.add(roleReason);
        List<String> cities=Json.strings(profile.get("cities")),locations=QualificationRules.cities(item);
        boolean cityKnown=!cities.isEmpty()&&!locations.isEmpty(),cityHit=cityKnown&&QualificationRules.cityMatch(cities,locations);
        var types=Json.strings(profile.get("companyTypes"));
        boolean companyKnown=Boolean.TRUE.equals(item.get("company_type_verified"))&&!types.isEmpty();
        boolean companyHit=companyKnown&&types.contains(item.get("company_type"));
        Map<String,Double> ratios=new LinkedHashMap<>();
        ratios.put("role",roleRatio);ratios.put("skills",skillDenominator>0?skillNumerator/skillDenominator:0);
        ratios.put("city",cityHit?1.0:0);ratios.put("company",companyHit?1.0:0);ratios.put("qualifications",qualifications.ratio());
        Map<String,String> statuses=Map.of("role",roles.isEmpty()||direction.kind().equals("unknown")?"unconfirmed":roleHit?"confirmed":roleRatio>0?"partial":"unmatched",
            "skills",skillDenominator==0?"unconfirmed":skillNumerator==skillDenominator?"confirmed":skillNumerator>0?"partial":"unconfirmed",
            "city",!cityKnown?"unconfirmed":cityHit?"confirmed":"unmatched",
            "company",!companyKnown?"unconfirmed":companyHit?"confirmed":"unmatched",
            "qualifications",qualifications.conflict()?"conflict":qualifications.unknown()?"unconfirmed":"confirmed");
        Map<String,String> descriptions=Map.of("role",roleReason,"skills",skillDenominator>0?"必备/历史条件权重1，加分条件0.5；任选组按达到数量比例，提及及否定条件不计分":"原文无可评分的明确技能条件，提及技能不计分",
            "city",!cityKnown?"目标城市或岗位城市未知，不计已确认地点分":cityHit?"符合目标城市偏好："+cities:"已知工作地点与目标城市不同",
            "company",!companyKnown?"企业性质未核验或未设置偏好，不计企业分":companyHit?"已核验的企业性质符合偏好":"已核验的企业性质与偏好不同",
            "qualifications","仅已确认符合项计分，未知项保留在分母；明确冲突会将最终分数降为0");
        Map<String,String> names=Map.of("role","岗位方向","skills","技能条件","city","城市偏好","company","企业偏好","qualifications","招聘资格");
        var configured=Json.map(profile.get("weights"));
        Map<String,Double> weights=new LinkedHashMap<>();
        Map<String,Integer> defaults=Map.of("role",35,"skills",40,"city",10,"company",0,"qualifications",15);
        for(String key:ratios.keySet())weights.put(key,configured.get(key) instanceof Number n?Math.max(0,n.doubleValue()):defaults.get(key).doubleValue());
        double total=weights.values().stream().mapToDouble(Double::doubleValue).sum();
        if(total<=0){weights.clear();defaults.forEach((k,v)->weights.put(k,v.doubleValue()));total=100;}
        var parts=new ArrayList<ScorePart>();double accumulated=0,previous=0,base=0;
        for(var entry:ratios.entrySet()) {
            String key=entry.getKey();accumulated+=weights.get(key);double boundary=round(100*accumulated/total),maximum=round(boundary-previous);previous=boundary;
            double contribution=round(maximum*entry.getValue());base=round(base+contribution);
            List<String> evidence=key.equals("role")?direction.evidence():key.equals("skills")?conditions.stream().map(SkillCondition::evidence).filter(x->!x.isBlank()).distinct().toList():List.of();
            parts.add(new ScorePart(key,names.get(key),weights.get(key),maximum,entry.getValue(),contribution,statuses.get(key),descriptions.get(key),evidence));
        }
        String body=Objects.toString(item.get("body"),"");
        boolean missingJd=body.strip().length()<30;
        if(missingJd){unknown=true;reasons.add("缺少完整JD或正文过短，需要核验职责及资格");}
        double cap=100;
        var adjustments=new ArrayList<Adjustment>();
        if(roleConflict)cap=Math.min(cap,10);
        else if(!roleHit)cap=Math.min(cap,35);
        if(missingJd)cap=Math.min(cap,20);
        boolean noCoreProfile=roles.isEmpty() && confirmed.isEmpty();
        if(noCoreProfile)cap=0;
        if(fail)cap=0;
        double score=round(Math.min(base,cap));
        if(score<base)adjustments.add(new Adjustment(fail?"hard_conflict":noCoreProfile?"profile_unconfirmed":roleConflict?"direction_conflict":missingJd?"missing_jd":"direction_unconfirmed",
            fail?"存在明确硬性资格冲突，其他偏好分不能掩盖":noCoreProfile?"未确认目标岗位与掌握技能，时间或资格项不能独立形成推荐分":roleConflict?"目标方向不符，推荐分上限10":missingJd?"完整JD不足，参考分上限20":"缺少目标方向确认，参考分上限35",round(score-base)));
        if(fail)reasons.add("存在明确硬性资格冲突，最终分数为0");
        var next=new ArrayList<String>();
        qualifications.checks().stream().filter(c->c.status().equals("conflict")||c.status().equals("unconfirmed")).map(c->c.label()+"："+c.reason()).forEach(next::add);
        conditions.stream().filter(c->c.status().equals("unconfirmed")&&c.requirement().equals("required")).map(c->"确认必备技能："+c.names()).forEach(next::add);
        if(!roleHit)next.add(roleReason);if(missingJd)next.add("打开官方来源补充完整JD");
        String advice=fail?"存在明确资格冲突，先核对原文，不能据高偏好分推荐":noCoreProfile?"先完善目标岗位与已确认技能，再参考推荐分":roleConflict?"与目标岗位方向不符，建议降低关注优先级":unknown?"可进一步了解，但需先确认列出的未知条件":"符合当前已知条件，可进一步核验官方信息";
        return new Result(fail?"not_eligible":unknown?"insufficient_information":"eligible",score,new ArrayList<>(new LinkedHashSet<>(reasons)),new ArrayList<>(matched),new ArrayList<>(missing),ratios,conditions,qualifications.checks(),direction,parts,base,adjustments,advice,next,REVISION,roleHit,bachelorStatus(item));
    }
}
