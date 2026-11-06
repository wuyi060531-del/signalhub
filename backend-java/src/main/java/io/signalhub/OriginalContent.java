package io.signalhub;

import java.util.*;

/** Only saved source fields; never retrieve URLs or treat AI summaries as originals. */
final class OriginalContent {
    private OriginalContent() {}
    private static String str(Map<String,Object> m, String key) {
        return m.get(key) instanceof String s ? s : "";
    }
    static Map<String,Object> from(Map<String,Object> payload, String adapter, Map<String,Object> raw) {
        String body="", summary="";
        boolean complete=true;
        switch(adapter) {
            case "greenhouse" -> body=str(raw,"content");
            case "ashby" -> body=str(raw,"descriptionPlain").isBlank()?str(raw,"descriptionHtml"):str(raw,"descriptionPlain");
            case "github" -> body=str(raw,"body");
            case "manual" -> { body=str(raw,"body"); complete=false; }
            case "lever" -> {
                var parts=new ArrayList<String>();
                parts.add(str(raw,"description").isBlank()?str(raw,"descriptionPlain"):str(raw,"description"));
                if(raw.get("lists") instanceof List<?> list) for(Object entry:list) {
                    var part=Json.map(entry);parts.add(str(part,"text"));parts.add(str(part,"content"));
                }
                parts.add(str(raw,"additional").isBlank()?str(raw,"additionalPlain"):str(raw,"additional"));
                parts.add(str(raw,"salaryDescriptionPlain"));body=String.join("\n\n",parts);
            }
            case "smartrecruiters" -> {
                var sections=Json.map(Json.map(raw.get("jobAd")).get("sections"));
                var parts=new ArrayList<String>();
                var keys=new LinkedHashSet<>(List.of("companyDescription","jobDescription","qualifications","additionalInformation"));
                keys.addAll(sections.keySet());
                for(String key:keys) {
                    if(sections.get(key) instanceof Map<?,?>) {
                        var part=Json.map(sections.get(key));parts.add(str(part,"title"));parts.add(str(part,"text"));
                    }
                }
                body=String.join("\n\n",parts);
            }
            case "rss" -> {
                summary=str(raw,"summary");
                if(raw.get("content") instanceof List<?> list && !list.isEmpty()) body=str(Json.map(list.getFirst()),"value");
                // Feed content, too, may be an excerpt of the linked article.
                if(body.isBlank()) body=summary;
                complete=false;
            }
            default -> complete=false;
        }
        String kind="saved_original";
        if(body.isBlank()) {body=str(payload,"body");complete=false;kind=body.isBlank()?"missing":"normalized";}
        else if(!complete) kind=adapter.equals("manual")?"provided":"excerpt";
        var result=new LinkedHashMap<String,Object>();
        result.put("title",str(payload,"title"));result.put("summary",summary);
        result.put("body",body);result.put("complete",complete);result.put("kind",kind);
        result.put("url",payload.get("url"));
        return result;
    }
}
