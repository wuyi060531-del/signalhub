-- Local, reference-only machine translation has a separate cache from reviewed human translations.
CREATE TABLE translation_runtime (
 id int PRIMARY KEY CHECK(id=1), available boolean NOT NULL,
 provider_revision text NOT NULL, message text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE reading_translation_jobs (
 id bigserial PRIMARY KEY,
 item_id bigint NOT NULL REFERENCES items,
 content_hash text NOT NULL,
 provider_revision text NOT NULL,
 depth int NOT NULL CHECK(depth IN (1,2)),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','done','failed','superseded')),
 attempts int NOT NULL DEFAULT 0 CHECK(attempts>=0),
 result jsonb, error text,
 created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, finished_at timestamptz,
 UNIQUE(item_id,content_hash,provider_revision,depth)
);
CREATE INDEX idx_reading_translation_pending ON reading_translation_jobs(state,depth DESC,id);
