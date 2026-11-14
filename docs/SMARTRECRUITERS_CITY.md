# SmartRecruiters structured city filter

Research/implementation date: 2026-11-14 (Asia/Shanghai).

## Configuration

Optional `city` is a nonblank string of at most 100 characters. Example:

```json
{"board":"SAPITBusinessSysteme","country":"CN","city":"Chengdu","q":"Application Engineer","max_items":5}
```

For Bosch use board `BoschGroup`, country `CN`, city `Chongqing`; a narrow technical keyword and a small detail limit keep requests bounded. No sources are created or enabled by this change.

The documented [public Posting endpoint](https://developers.smartrecruiters.com/reference/v1listpostings) accepts a single city string. We send that parameter, then independently compare the detail's `location.city`. The full-text `q` parameter is never location evidence. With country CN, known English/Chinese city labels and the explicit Chinese 市 suffix are equivalent; English matching ignores case and edge whitespace. The API query uses the known English spelling. Without CN, labels only use exact case-insensitive trimmed comparison. Missing/non-string labels and combined labels such as `Chengdu / Beijing` do not match a single city. Remote status alone does not imply eligibility for a city. Unknown aliases are not guessed; server-side alias behavior can still reduce recall. This is not a worldwide city geocoder or an all-location search.

Omitting city preserves existing query and selection behavior. Detail city mismatches are skipped, not treated as closed jobs. Raw listing/detail, UUID, numeric ID, refNumber, URL and publication timestamp are preserved through the existing raw envelope. No identity mapping, database migration, employer review, application or favourite is changed.

## Completeness and availability

All list pages must complete before details are yielded. Existing duplicate-ID, empty-page, offset and bounded-pagination guards remain. Total changes between pages and overruns now fail explicitly. Constant-size concurrent replacements cannot be ruled out by offset pagination; this is not a transactionally consistent provider snapshot. An exception while streaming details can retain the already-ingested prefix under the existing pipeline; the collection fails and retries are idempotent. Neither failure nor filtered absence closes historical jobs. We do not return a page ETag as proof of whole-source freshness.

## Identity and verification follow-up (not implemented)

Historical SAP REF2723J used numeric posting 744000157440020; the 2026-11-13 observation used 744000159038469. Same refNumber is a candidate for review, not proof of globally unique permanent identity. The existing adapter prioritizes UUID; the manual SAP draft uses sap-REF2723J. A future identity proposal should scope refNumber to the provider/company and test: same UUID with changed URL; same refNumber with changed UUID; reused reference after closure; conflicting locations; same reference across companies; manual-versus-automatic provenance. Ambiguous cases must remain separate pending review. Existing favourites/application history must not be reassigned automatically.

Automatic API observations should eventually record method, observed_at, source run and active/visibility evidence independently of human verification. Do not populate the current human-labelled source_verified_at/status fields just to display a green badge. This PR leaves those fields and the data model unchanged; tests assert that filtered adapter rows do not manufacture human verification.

## Baseline and scope

Private local baseline 20107c2 and published main 5e36859 have unrelated histories (published root a6123f2); merge-base returned no common ancestor. Tree comparison showed 682 files changed, largely excluded private materials. The SmartRecruiters adapter itself was identical. This change was developed on an isolated worktree based on published main; private local history is not pushed. No six-company domestic crawlers, production imports, background collectors or applications were run.

## Verification

See the PR for executed regression results. Live observations are dated separately from historical evidence; public API access is not permission for unlimited collection. Requests retain PUBLIC destination, bounded detail counts and approximately one request per second; no credentials, internal endpoints or application POSTs are used.

Executed: check.sh passed (99 Java, 318 Python; zero failures/skips), including 24 new city tests and database regressions proving failed collections preserve existing items/last_success. Synthetic AI evaluation and static deployment checks passed. Initial setup failed because bundled PostgreSQL omitted createdb; created the isolated database with psycopg and reran successfully. Loopback port 55449, signalhub_city_test, Flyway migrations from Java tests; no production database. JS tests not run (node absent from PATH; no JS changes).

Live 2026-11-14: SAP city=Chengdu/q=Application Engineer returned 2 records and both details HTTP 200, including REF2723J, numeric ID 744000159038469, UUID fb28e5e5-fc96-4238-88e0-56d34ae4c626, active=true/PUBLIC, releasedDate 2026-11-02T03:31:45.433Z. The other is Consultant REF1687O: keyword matching does not guarantee role relevance. Bosch city=Chongqing/q=SW system development engineer returned 8 records; max_items=5 failed before fetching details rather than truncating. A separate single public detail GET confirmed REF286263M, numeric ID 744000126636669, UUID be129578-8330-471e-8bd2-40986acfeb2d, Chongqing/cn, active=true/PUBLIC, releasedDate 2026-05-15T06:55:51.526Z. Bosch is list plus single-detail verification, not a successful full adapter run. Publication dates are not first-post dates; deadlines, current headcount and personal eligibility remain unknown.
