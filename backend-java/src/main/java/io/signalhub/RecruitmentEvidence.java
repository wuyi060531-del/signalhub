package io.signalhub;

import java.net.URI;
import java.time.Clock;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** 只解释已保存的逐岗证据。来源成功、HTTP200、缺席和网络失败均不能推导在招/关岗。 */
final class RecruitmentEvidence {
    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    private static final int RECENT_DAYS = 7;
    private static final Set<String> CLOSED = Set.of("closed", "expired", "inactive", "已关闭", "已截止");

    record Status(String state, String label, String basis, String verifiedAt, String url) {}

    private RecruitmentEvidence() {}

    static Status evaluate(Map<String, Object> payload, Object deadline, Clock clock, boolean demo) {
        if (demo) {
            return new Status("synthetic", "合成演示 · 非真实招聘", "招聘条件和状态仅用于演示，不是官方在列证据", null, null);
        }
        String marker = Objects.toString(payload.get("status"), "").strip().toLowerCase(java.util.Locale.ROOT);
        String url = Json.string(payload, "url");
        OffsetDateTime verified = verificationTime(payload.get("source_verified_at"), clock);
        boolean evidence = verified != null && officialLink(url)
            && !Objects.toString(payload.get("body"), "").isBlank()
            && !Objects.toString(payload.get("source_verification_note"), "").isBlank();
        String verifiedAt = verified == null ? null : verified.toString();
        LocalDate today = LocalDate.now(clock.withZone(ZONE));
        if (deadline != null && LocalDate.parse(deadline.toString()).isBefore(today)) {
            return new Status("closed", "已关闭或截止", "已过保存的截止日期 " + deadline + "；请核对官方原文", verifiedAt, url);
        }
        if (CLOSED.contains(marker) && evidence) {
            return new Status("closed", "已关闭或截止", "导入者保存了官方关闭标记及核验说明；原文和历史保留", verifiedAt, url);
        }
        if (marker.equals("open") && evidence && !verified.toInstant().isBefore(clock.instant().minusSeconds(RECENT_DAYS * 86400L))) {
            return new Status("recently_listed", "最近人工核验官方仍在列", "导入者声明，7日内核验；仅证明核验当时在列，不保证现在可申请或个人符合", verifiedAt, url);
        }
        if (marker.equals("pending_review") || (!evidence && marker.equals("open"))
                || CLOSED.contains(marker) || payload.get("source_verified_at") != null && !marker.equals("open")) {
            return new Status("pending_review", "等待人工核验", "现有标记或JD可见证据不足以确认当前仍在列；请核对官方页面", verifiedAt, url);
        }
        return new Status("archived_unknown", "历史存档，状态未知", "没有7日内明确在列证据；采集成功/部分结果/请求失败均不改变本结论", verifiedAt, url);
    }

    private static OffsetDateTime verificationTime(Object value, Clock clock) {
        try {
            var time = OffsetDateTime.parse(Objects.toString(value, ""));
            return time.toInstant().isAfter(clock.instant()) ? null : time;
        } catch (java.time.format.DateTimeParseException ignored) {
            return null;
        }
    }

    private static boolean officialLink(String value) {
        try {
            URI uri = URI.create(value);
            return "https".equals(uri.getScheme()) && uri.getHost() != null && uri.getUserInfo() == null;
        } catch (IllegalArgumentException | NullPointerException ignored) {
            return false;
        }
    }
}
