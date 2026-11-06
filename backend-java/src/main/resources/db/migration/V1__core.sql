CREATE TABLE sources (
 id bigserial PRIMARY KEY, name text NOT NULL UNIQUE,
 adapter text NOT NULL CHECK(adapter IN ('manual','github','greenhouse','rss')),
 config jsonb NOT NULL DEFAULT '{}', status text NOT NULL DEFAULT 'unverified',
 enabled boolean NOT NULL DEFAULT false, etag text, last_modified text,
 last_success timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO sources(name,adapter,status,enabled) VALUES ('手动导入','manual','manual_only',true),('离线演示（合成数据）','manual','test_data',true);
CREATE TABLE collection_runs (
 id bigserial PRIMARY KEY, source_id bigint NOT NULL REFERENCES sources,
 state text NOT NULL DEFAULT 'running', started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
 collected int NOT NULL DEFAULT 0, parsed int NOT NULL DEFAULT 0, failed int NOT NULL DEFAULT 0,
 deduplicated int NOT NULL DEFAULT 0, updated int NOT NULL DEFAULT 0, inserted int NOT NULL DEFAULT 0,
 errors jsonb NOT NULL DEFAULT '[]'
);
CREATE TABLE companies(id bigserial PRIMARY KEY, name text NOT NULL UNIQUE, company_type text NOT NULL DEFAULT 'unknown');
CREATE TABLE items (
 id bigserial PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('job','opportunity','release')),
 canonical_key text NOT NULL UNIQUE, title text NOT NULL, company_id bigint REFERENCES companies,
 country text, city text, company_type text NOT NULL DEFAULT 'unknown',
 category text, employment_type text, education text, graduation_year int,
 deadline date, published_at timestamptz, payload jsonb NOT NULL,
 content_hash text NOT NULL, version int NOT NULL DEFAULT 1,
 is_demo boolean NOT NULL DEFAULT false,
 first_seen timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE raw_records (
 id bigserial PRIMARY KEY, source_id bigint NOT NULL REFERENCES sources,
 external_id text NOT NULL, raw_hash text NOT NULL, body jsonb NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(source_id, external_id, raw_hash)
);
CREATE TABLE item_sources (
 source_id bigint NOT NULL REFERENCES sources, external_id text NOT NULL,
 item_id bigint NOT NULL REFERENCES items, url text, raw_id bigint REFERENCES raw_records,
 PRIMARY KEY(source_id,external_id)
);
CREATE TABLE item_versions (
 item_id bigint NOT NULL REFERENCES items, version int NOT NULL, payload jsonb NOT NULL,
 changed_fields jsonb NOT NULL, raw_id bigint REFERENCES raw_records, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(item_id,version)
);
CREATE TABLE duplicate_candidates (
 item_a bigint NOT NULL REFERENCES items, item_b bigint NOT NULL REFERENCES items,
 reason text NOT NULL, confidence numeric NOT NULL, PRIMARY KEY(item_a,item_b), CHECK(item_a < item_b)
);
CREATE TABLE job_skills (
 item_id bigint NOT NULL REFERENCES items, skill text NOT NULL,
 requirement text NOT NULL CHECK(requirement IN ('required','preferred','mentioned')),
 evidence text NOT NULL, extracted_by text NOT NULL DEFAULT 'rule', PRIMARY KEY(item_id,skill)
);
CREATE TABLE user_profiles (
 id int PRIMARY KEY CHECK(id=1), settings jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO user_profiles VALUES (1,'{"skills":[],"learningSkills":[],"cities":[],"roles":[],"companyTypes":[],"excludedTerms":[],"education":null,"graduationYear":null,"hardCity":false,"weights":{"role":30,"skills":40,"city":15,"company":15}}',now());
CREATE TABLE subscriptions (
 id bigserial PRIMARY KEY, name text NOT NULL, rules jsonb NOT NULL, enabled boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE match_results (
 item_id bigint PRIMARY KEY REFERENCES items, hard_status text NOT NULL, score numeric NOT NULL,
 explanation jsonb NOT NULL, calculated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE job_applications (
 item_id bigint PRIMARY KEY REFERENCES items, status text NOT NULL CHECK(status IN ('interested','saved','preparing','applied','assessment','interview1','interview_next','offer','rejected','closed')),
 notes text NOT NULL DEFAULT '', applied_at timestamptz, assessment_at timestamptz, interview_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE application_history (
 id bigserial PRIMARY KEY, item_id bigint NOT NULL REFERENCES items, snapshot jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE alerts (
 id bigserial PRIMARY KEY, item_id bigint REFERENCES items, dedup_key text NOT NULL UNIQUE,
 message text NOT NULL, read_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE task_requests (
 id bigserial PRIMARY KEY, task_type text NOT NULL CHECK(task_type IN ('import','collect','enrich')),
 source_id bigint NOT NULL REFERENCES sources, payload jsonb NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','done','failed')),
 attempts int NOT NULL DEFAULT 0, result jsonb, error text,
 created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, finished_at timestamptz
);
CREATE TABLE ai_enrichments (
 item_id bigint NOT NULL REFERENCES items, content_hash text NOT NULL, provider text NOT NULL,
 result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(item_id,content_hash,provider)
);
CREATE TABLE ai_usage (
 id bigserial PRIMARY KEY, month text NOT NULL, provider text NOT NULL, state text NOT NULL,
 reserved_usd numeric NOT NULL, actual_usd numeric, input_tokens int, output_tokens int,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_items_filters ON items(kind,country,company_type,city);
CREATE INDEX idx_items_category ON items(kind,category,education,employment_type);
CREATE INDEX idx_items_updated ON items(updated_at DESC,id DESC);
CREATE INDEX idx_items_deadline ON items(deadline) WHERE deadline IS NOT NULL;
CREATE INDEX idx_items_payload ON items USING gin(payload jsonb_path_ops);
CREATE INDEX idx_skills_skill ON job_skills(skill,item_id);
CREATE INDEX idx_item_sources_item ON item_sources(item_id,source_id);
CREATE INDEX idx_runs_source ON collection_runs(source_id,started_at DESC);
CREATE INDEX idx_task_pending ON task_requests(state,created_at);
CREATE INDEX idx_ai_month ON ai_usage(month);
