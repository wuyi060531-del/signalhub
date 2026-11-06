CREATE TABLE canonical_aliases (
 canonical_key text PRIMARY KEY,
 item_id bigint NOT NULL REFERENCES items
);
INSERT INTO canonical_aliases SELECT canonical_key,id FROM items;
CREATE INDEX idx_canonical_alias_item ON canonical_aliases(item_id);
ALTER TABLE ai_enrichments ADD COLUMN profile_updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE ai_enrichments DROP CONSTRAINT ai_enrichments_pkey;
ALTER TABLE ai_enrichments ADD PRIMARY KEY(item_id,content_hash,provider,profile_updated_at);
