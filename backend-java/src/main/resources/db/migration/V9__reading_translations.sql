-- 阅读译文独立于规范实体、版本、匹配及AI建议。源哈希不一致时保留历史但不使用。
CREATE TABLE reading_translations (
 item_id bigint NOT NULL REFERENCES items,
 content_hash text NOT NULL,
 language text NOT NULL DEFAULT 'zh-CN' CHECK (language = 'zh-CN'),
 payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (item_id, content_hash, language),
 CHECK (payload ?& ARRAY['method','attribution','reviewed']),
 CHECK (payload->'reviewed' = 'true'::jsonb),
 CHECK (payload->>'method' IN ('human_reviewed', 'source_bilingual')),
 CHECK (length(trim(payload->>'attribution')) > 0)
);
