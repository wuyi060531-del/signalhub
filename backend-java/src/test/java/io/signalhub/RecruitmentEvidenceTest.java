package io.signalhub;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.assertThat;

class RecruitmentEvidenceTest {
    private static final Clock CLOCK = Clock.fixed(Instant.parse("2026-10-25T08:00:00Z"), ZoneOffset.UTC);
    private Map<String,Object> verified() {
        return new HashMap<>(Map.of("status","open","url","https://example.com/synthetic-job", "body","合成JD",
            "source_verified_at","2026-10-24T10:00:00+08:00","source_verification_note","合成官方在列核验，非真实招聘"));
    }
    @Test void explicitRecentManualEvidenceIsRequiredAndExpiresConservatively() {
        var job=verified();
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isEqualTo("recently_listed");
        job.put("source_verified_at","2026-10-18T16:00:00+08:00"); // exactly seven days
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isEqualTo("recently_listed");
        job.put("source_verified_at","2026-10-18T15:59:59+08:00");
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isEqualTo("archived_unknown");
        job.put("source_verified_at","2026-10-26T10:00:00+08:00");
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isEqualTo("pending_review");
        for(String field: new String[]{"source_verified_at","source_verification_note","body","url"}) {
            job=verified();job.remove(field);
            assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isNotEqualTo("recently_listed");
        }
    }
    @Test void visibleJdAndSourceHealthAreNotProofOfCurrentRecruitment() {
        var job=verified();job.remove("status");
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isEqualTo("pending_review");
        job.clear();
        for(String status:new String[]{"verified","unavailable","partial","not_modified"}) {
            job.put("source_status",status);
            assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isEqualTo("archived_unknown");
        }
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).verifiedAt()).isNull();
    }
    @Test void syntheticJobsNeverClaimOfficialRecruitment() {
        var job=verified();
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,true).state()).isEqualTo("synthetic");
        assertThat(RecruitmentEvidence.evaluate(job,"2026-10-24",CLOCK,true).verifiedAt()).isNull();
    }
    @Test void savedDeadlineAndVerifiedClosureWinWhileUnprovenMarkerStaysPending() {
        var job=verified();
        assertThat(RecruitmentEvidence.evaluate(job,"2026-10-24",CLOCK,false).state()).isEqualTo("closed");
        assertThat(RecruitmentEvidence.evaluate(job,"2026-10-25",CLOCK,false).state()).isEqualTo("recently_listed");
        job.put("status","closed");
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isEqualTo("closed");
        job.remove("source_verified_at");
        assertThat(RecruitmentEvidence.evaluate(job,null,CLOCK,false).state()).isEqualTo("pending_review");
    }
}
