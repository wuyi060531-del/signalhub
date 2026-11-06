package io.signalhub;

/** 申请信息的明确失效证据；未知不等于关闭，来源缺席也不参与判断。 */
final class ItemAvailability {
    private ItemAvailability() {}

    // 使用 items 的固定别名 i；日期遵循产品的 Asia/Shanghai 日粒度约定。
    static final String OPEN_SQL="(i.kind NOT IN ('job','opportunity') OR "
        +"((i.deadline IS NULL OR i.deadline>=(now() AT TIME ZONE 'Asia/Shanghai')::date) "
        +"AND lower(btrim(coalesce(i.payload->>'status',''))) NOT IN ('closed','expired','inactive','已关闭','已截止')))";
}
