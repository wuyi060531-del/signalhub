package io.signalhub;
import java.util.*;
import java.util.regex.*;

/** Direction comes from job title or explicit personal responsibilities, not company advertising. */
final class RoleClassifier {
    record Assessment(List<String> categories,List<String> evidence,String kind) {}
    private static final Map<String,String> PATTERNS=new LinkedHashMap<>();
    static {
        PATTERNS.put("data_engineering","数据开发|数据工程|大数据开发|数据库.{0,12}(?:开发|研发)|data engineer|data platform engineer|etl developer");
        PATTERNS.put("java_backend","后端|\\bback[ -]?end\\b|(?<![A-Za-z0-9])Java(?![A-Za-z0-9]).{0,20}(?:engineer|developer|开发|工程)");
        PATTERNS.put("python","(?<![A-Za-z0-9])Python(?![A-Za-z0-9]).{0,20}(?:engineer|developer|开发|工程)");
        PATTERNS.put("data_analysis","数据分析|data analy(?:st|tics)");
        PATTERNS.put("ai","人工智能|机器学习|(?:大模型|智能体).{0,15}(?:算法|开发|研发|工程|研究)|(?:(?<![A-Za-z0-9])AI(?![A-Za-z0-9])|(?<![A-Za-z0-9])LLM(?![A-Za-z0-9])|(?<![A-Za-z0-9])RAG(?![A-Za-z0-9])|machine learning).{0,30}(?:engineer|developer|开发|研发|工程|研究)|(?:engineer|developer).{0,25}(?:machine learning|(?<![A-Za-z0-9])AI(?![A-Za-z0-9]))");
        PATTERNS.put("software","software engineer|software developer|软件工程|软件开发");
    }
    static Assessment assess(Map<String,Object> item) {
        String title=Objects.toString(item.get("title"),"");
        if(Pattern.compile("客户经理|销售|行政|人力资源|招聘专员|会计|account.{0,15}(?:manager|management)|\\b(?:pre[ -]?)?sales\\b|human resources|recruiter|administrative|accountant|program manager",Pattern.CASE_INSENSITIVE).matcher(title).find())
            return new Assessment(List.of(),List.of(title),"non_target");
        var categories=new LinkedHashSet<String>();var evidence=new ArrayList<String>();
        for(var e:PATTERNS.entrySet())if(Pattern.compile(e.getValue(),Pattern.CASE_INSENSITIVE).matcher(title).find())categories.add(e.getKey());
        if(!categories.isEmpty())evidence.add(title);
        String body=Objects.toString(item.get("body"),"");
        for(String sentence:body.split("[；;。\\n]")) {
            if(evidence.size()>=5)break;
            if(!Pattern.compile("you will|you['’]ll|you are responsible|负责|工作职责",Pattern.CASE_INSENSITIVE).matcher(sentence).find())continue;
            if(Pattern.compile("\\b(?:pre[ -]?)?sales\\b|\\bselling\\b|销售",Pattern.CASE_INSENSITIVE).matcher(sentence).find())continue;
            if(Pattern.compile("(?:build|develop|design|构建|开发|设计).{0,50}(?:data pipelines|data warehouse|数据管道|数据仓库|数据平台)",Pattern.CASE_INSENSITIVE).matcher(sentence).find()) {
                categories.add("data_engineering");evidence.add(sentence.trim());
            }
            // Application Engineer标题可能是咨询或售前；只有本人明确承担AI应用编码职责才算开发方向。
            if(Pattern.compile("\\byou(?: will|['’]ll)\\s+(?:contribute to|build|develop|implement)\\b.{0,100}\\b(?:AI[ -](?:enabled|powered)|LLM[ -]enabled)\\s+application(?:s| features)?\\b.{0,80}\\b(?:coding|programming|development)\\b",Pattern.CASE_INSENSITIVE).matcher(sentence).find()) {
                categories.add("ai");categories.add("software");evidence.add(sentence.trim());
            }
        }
        String kind=categories.isEmpty()?"unknown":"technical";
        if(categories.isEmpty() && Pattern.compile("solutions? engineer|technical consultant|解决方案|技术顾问",Pattern.CASE_INSENSITIVE).matcher(title).find()) {kind="adjacent";evidence.add(title);}
        return new Assessment(new ArrayList<>(categories),evidence,kind);
    }
}
