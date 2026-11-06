package io.signalhub;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
class OriginalContentTest {
    private final Map<String,Object> payload=Map.of("title","Original title","body","normalized excerpt","url","https://example.com/job");
    @Test void completeSavedFieldsNeverUseGeneratedText() {
        for(var example:List.of(
            Map.of("adapter","manual","raw",Map.of("body","Full\noriginal <script>evil()</script>")),
            Map.of("adapter","github","raw",Map.of("body","Full release notes")),
            Map.of("adapter","greenhouse","raw",Map.of("content","<p>Full description</p>")),
            Map.of("adapter","ashby","raw",Map.of("descriptionPlain","Full Ashby description")))) {
            var result=OriginalContent.from(payload,example.get("adapter").toString(),Json.map(example.get("raw")));
            assertThat(result.get("complete")).isEqualTo(!example.get("adapter").equals("manual"));
            assertThat(result.get("body").toString()).contains("Full").doesNotContain("normalized excerpt");
        }
    }
    @Test void rssSummaryAndMissingArchiveAreNeverLabelledFullArticle() {
        var result=OriginalContent.from(payload,"rss",Map.of("summary","Only a feed excerpt"));
        assertThat(result).containsEntry("complete",false).containsEntry("kind","excerpt").containsEntry("summary","Only a feed excerpt");
        assertThat(OriginalContent.from(payload,"rss",Map.of("content",List.of(Map.of("value","Stored article")),"summary","excerpt")))
            .containsEntry("complete",false).containsEntry("body","Stored article");
        assertThat(OriginalContent.from(payload,"",Map.of())).containsEntry("complete",false).containsEntry("kind","normalized");
        assertThat(OriginalContent.from(Map.of(),"manual",Map.of())).containsEntry("kind","missing");
        assertThat(OriginalContent.from(payload,"manual",Map.of("body","A manual excerpt"))).containsEntry("kind","provided").containsEntry("complete",false);
    }
    @Test void leverAndSmartRecruitersKeepEverySavedSection() {
        var lever=OriginalContent.from(payload,"lever",Map.of("description","Intro","lists",List.of(Map.of("text","Requirements","content","Python")),"additionalPlain","Closing","salaryDescriptionPlain","Salary"));
        assertThat(lever.get("body").toString()).contains("Intro","Requirements","Python","Closing","Salary");
        var sr=OriginalContent.from(payload,"smartrecruiters",Map.of("jobAd",Map.of("sections",Map.of("companyDescription",Map.of("title","About company","text","Company section"),"jobDescription",Map.of("title","Intro","text","A"),"qualifications",Map.of("title","Requirements","text","B"),"additionalInformation",Map.of("title","Closing","text","C")))));
        assertThat(sr.get("body").toString()).contains("About company","Company section","Intro","A","Requirements","B","Closing","C");
    }
}
