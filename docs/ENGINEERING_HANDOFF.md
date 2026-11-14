# Engineering validation and frontend handoff — 2026-11-14

This review is AI-assisted (Codex), uses isolated synthetic databases, and does not
represent production experience or real job applications.

## Safe PR integration

Published main is `5e3685912198fb5a4c5dc85eec59642d49690155`.
PR #8 (`d191db44edf4635e55665f6c8578db6abd51b2f0`) rejects blank external IDs;
PR #9 (`97fb8008a6f3224c369a01fd72bce6a51406a3c8`) filters structured cities.
Both descend from that main and change different files. There is no feature dependency.
Suggested human merge order: #8 (identity corruption guard), then #9 (city selection),
checking the new main/PR CI after each merge. Do not recreate either feature in this PR.

Combined local validation used the exact remote #9 tree plus #8's three-file patch;
applying the patch was conflict-free. Git commit objects and trees were checked against
GitHub SHA values; no unrelated local `20107c2` history was merged. The remote #9/main
merge-base is `5e36859`; private local main has no common ancestor. This document-only
PR is based on published main and does not merge, close or modify #8/#9.

## Executed acceptance

- `./scripts/check.sh`: 99 Java + 336 Python passed, no skips/failures on the combined tree.
  PostgreSQL 17.11 in a dedicated loopback container; Flyway V1–V12. Synthetic evaluation
  and six static deployment checks passed.
- `node --test tests/*.test.cjs`: 38 passed; `node --check backend-java/src/main/resources/static/startup.js` passed.
- `./scripts/mvn.sh -f backend-java/pom.xml -DskipTests package`: passed after tests.
- `python scripts/integration_smoke.py`: 26 HTTP/queue integration checks passed.
- `python scripts/public_demo.py --verify-only`: passed on a fresh isolated database.
  Synthetic import → detail/filter → match explanation → JD v2 invalidates old score →
  refresh → saved/applied local records and history; 84.5 score, eligibility still unknown,
  AI disabled, translation unavailable with original text retained.
- `python scripts/deployment_check.py --docker`: attempted locally and failed during
  image retrieval/build (Docker Hub connectivity); not a successful local container test.
- Existing remote #8 CI run 43174807009 and #9 run 43534812810 succeeded, including
  container jobs. These do not constitute remote CI for the combined unmerged tree.

Test DB URLs/passwords and toolchain paths are intentionally omitted. Use the environment
variables shown in `.github/workflows/ci.yml`
and point them only at disposable `_test` databases. Counts are dated review evidence.

## Data and reliability boundaries

Raw API data, UUID, numeric ID, reference and URL stay preserved. City filtering uses
structured details; q/body text is not city evidence. Missing/mixed/unknown labels are
excluded, so high location precision does not guarantee full recall. Same-count concurrent
pagination changes cannot all be detected. No new crawlers or identity merges were added.

Pipeline transactions are per item. A detail failure may leave the committed prefix;
run/task fail, last_success does not advance, and filtered/failed absence never closes
historical jobs. Retrying deduplicates existing writes. Exhausted HTTP retries fail the
queue task; a new/manual scheduled task is needed, rather than assuming auto-requeue.
Do not label machine API observations as human verification or silently reassign saved
applications when a provider republishes a reference under another ID.

The earlier 2026-11-14 PR #9 reliability review additionally completed Bosch Chongqing
with max_items=20: 8 records / 9 HTTP 200 responses, including REF286263M, through a real
Worker/Pipeline into a disposable DB using an injected anonymous transport. This is dated
prior evidence, not a new crawl in this engineering pass or proof of current vacancies.

## Claude handoff

- Demo setup: [PUBLIC_DEMO.md](PUBLIC_DEMO.md), then `python scripts/public_demo.py`.
  This creates an isolated synthetic instance; use the URL printed by the script.
- Main assets: `backend-java/src/main/resources/static/`; HTTP handlers and matching
  rules: `backend-java/src/main/java/`; queue/adapters: `data-pipeline-python/src/signalhub/`.
- Entry pages: job list and detail, source/task status, profile/matching, applications/history.
  Keep the current page routes and API contracts; read [ARCHITECTURE.md](ARCHITECTURE.md).
- Preserve raw source links, unknown qualification labels, stale-score hiding, synthetic-data
  badges, local-only application meaning, error/empty states and CSRF/CSP protections.
- Use synthetic fixtures for screenshots. Do not claim live recruitment or human verification
  from a successful API response. No paid AI, external application or background collector.

Long-running 72-hour stability, production operation, global city recall, permanent provider
identity and a separate automatic/manual verification model remain outside this acceptance.
