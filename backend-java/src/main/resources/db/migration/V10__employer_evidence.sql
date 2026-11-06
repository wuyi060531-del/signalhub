-- Independent reviewed employer facts; raw source classifications are never overwritten.
CREATE TABLE employer_reviews (
 company_key text PRIMARY KEY CHECK(company_key=lower(btrim(company_key)) AND length(company_key)>0),
 name text NOT NULL,
 origin text NOT NULL CHECK(origin IN ('china_local','foreign','unclassified')),
 headquarters_countries jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(headquarters_countries)='array'),
 ownership text NOT NULL CHECK(ownership IN ('private','publicly_listed','foundation_owned','central_state','local_state','public_institution','joint_venture','unknown')),
 industry text,
 evidence_urls jsonb NOT NULL CHECK(jsonb_typeof(evidence_urls)='array'),
 basis text NOT NULL,
 verified_on date NOT NULL,
 status text NOT NULL CHECK(status IN ('verified','pending')),
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(status<>'verified' OR (origin<>'unclassified' AND ownership<>'unknown' AND jsonb_array_length(headquarters_countries)>0 AND jsonb_array_length(evidence_urls)>0 AND length(trim(basis))>0))
);
ALTER TABLE match_results ADD COLUMN employer_revision bigint CHECK(employer_revision>=0);
