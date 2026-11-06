package io.signalhub;
import org.junit.jupiter.api.*;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.test.context.ContextConfiguration;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
@SpringBootTest(properties={"spring.datasource.url=${TEST_DB_URL:jdbc:postgresql://127.0.0.1:55432/signalhub_test}","spring.datasource.username=${TEST_DB_USER:signalhub}","spring.datasource.password=${TEST_DB_PASSWORD:signalhub-test-fixture}"})
@AutoConfigureMockMvc
@ContextConfiguration(initializers=BusinessIntegrationTest.TestDatabaseGuard.class)
class BusinessIntegrationTest {
    static class TestDatabaseGuard implements ApplicationContextInitializer<ConfigurableApplicationContext> {
        @Override public void initialize(ConfigurableApplicationContext context) {
            String url=context.getEnvironment().getRequiredProperty("spring.datasource.url");
            if(!url.matches("jdbc:postgresql://(?:127\\.0\\.0\\.1|localhost)(?::[0-9]{1,5})?/[A-Za-z0-9_]+_test"))
                throw new IllegalStateException("只允许本机 _test 库执行 Flyway 和集成测试");
        }
    }
    @org.springframework.test.context.bean.override.mockito.MockitoSpyBean NamedParameterJdbcTemplate db;
    @Autowired org.springframework.transaction.PlatformTransactionManager transactionManager;
    @Autowired ItemRepository repo;
    @Autowired EmployerRegistry employers;
    @Autowired BusinessService service;
    @Autowired MockMvc mvc;
    @Autowired BusinessScheduler scheduler;
    @org.springframework.test.context.bean.override.mockito.MockitoSpyBean MatchingEngine matcher;
    @BeforeEach void clean() {
        String name=db.queryForObject("SELECT current_database()",Map.of(),String.class);
        if(!name.endsWith("_test"))throw new IllegalStateException("拒绝在非测试库清理数据");
        db.getJdbcTemplate().execute("TRUNCATE reading_translation_jobs,translation_runtime,employer_reviews,ai_usage,ai_enrichments,alerts,application_history,job_applications,match_results,subscriptions,duplicate_candidates,job_skills,item_versions,item_sources,raw_records,items,companies,collection_runs,task_requests RESTART IDENTITY CASCADE");
        db.update("DELETE FROM sources WHERE id>2",Map.of());
    }
    private long item(String type,String city,String skill) {
        var payload=new HashMap<String,Object>(Map.of("kind","job","title","数据工程实习","body","2027届 本科 Python SQL","country","CN","city",city,"company_type",type,"education","bachelor","graduation_year",2027,"skills",List.of(Map.of("name",skill)),"categories",List.of("data_engineering")));
        long id=db.queryForObject("INSERT INTO items(kind,canonical_key,title,country,city,company_type,payload,content_hash,education,graduation_year) VALUES ('job',:key,'数据工程实习','CN',:city,:type,CAST(:json AS jsonb),'hash','bachelor',2027) RETURNING id",Map.of("key",UUID.randomUUID().toString(),"city",city,"type",type,"json",Json.encode(payload)),Long.class);
        db.update("INSERT INTO job_skills VALUES (:id,:skill,'required','Python SQL','rule')",Map.of("id",id,"skill",skill));
        db.update("INSERT INTO item_sources(source_id,external_id,item_id) VALUES (1,:ext,:id),(2,:ext,:id)",Map.of("id",id,"ext","fixture-"+id));
        return id;
    }
    @Test void incrementalRefreshInvalidatesOnlyChangedInputsAndKeepsSubscriptions() {
        db.update("UPDATE user_profiles SET settings='{\"skills\":[],\"learningSkills\":[],\"cities\":[],\"roles\":[],\"companyTypes\":[],\"excludedTerms\":[],\"weights\":{\"role\":35,\"skills\":40,\"city\":10,\"company\":0,\"qualifications\":15}}'::jsonb,updated_at=now() WHERE id=1",Map.of());
        long first=item("foreign","上海","Python"),second=item("private","成都","Java");
        employerFor(first,"增量合成企业","CN");
        assertThat(service.refresh().get("computedJobs")).isEqualTo(2);
        var original=db.queryForList("SELECT * FROM match_results ORDER BY item_id",Map.of());
        assertThat(service.refresh()).containsEntry("computedJobs",0).containsEntry("matchWrites",0);
        assertThat(db.queryForList("SELECT * FROM match_results ORDER BY item_id",Map.of())).isEqualTo(original);
        service.subscription(new Contracts.Subscription("缓存结果订阅",Map.of("kind","job","minimumScore",0),true));
        assertThat(service.refresh().get("computedJobs")).isEqualTo(0);
        assertThat(service.alerts()).hasSize(2);
        db.update("UPDATE items SET version=version+1 WHERE id=:id",Map.of("id",first));
        assertThat(repo.detail(first).get("matching_status")).isEqualTo("pending");
        assertThat(service.refresh()).containsEntry("computedJobs",1).containsEntry("matchWrites",1);
        assertThat(db.queryForMap("SELECT * FROM match_results WHERE item_id=:id",Map.of("id",second))).isEqualTo(original.getLast());
        db.update("UPDATE match_results SET engine_revision='synthetic-old-rule'",Map.of());
        assertThat(service.refresh().get("computedJobs")).isEqualTo(2);
        reviewedEmployer("增量合成企业","foreign","publicly_listed");
        assertThat(repo.detail(first).get("matching_status")).isEqualTo("pending");
        assertThat(service.refresh().get("computedJobs")).isEqualTo(1);
        db.update("UPDATE match_results SET item_version=NULL WHERE item_id=:id",Map.of("id",second));
        assertThat(service.refresh().get("computedJobs")).isEqualTo(1);
        db.update("UPDATE user_profiles SET updated_at=updated_at+interval '1 second' WHERE id=1",Map.of());
        assertThat(service.refresh().get("computedJobs")).isEqualTo(2);
        assertThat(service.refresh()).containsEntry("computedJobs",0).containsEntry("matchWrites",0);
        var listed=(List<Map<String,Object>>)repo.search(Map.of("kind","job","sort","match_desc"),0,10).get("items");
        for(var row:listed)assertThat(repo.detail(((Number)row.get("id")).longValue()).get("explanation")).isEqualTo(row.get("explanation"));
    }
    @Test void localHostAllowlistRejectsRebindingBeforeReadingPrivateData() throws Exception {
        for(String host:List.of("evil.example","localhost.evil.example","127.0.0.1.evil.example","localhost:8080@evil.example"))
            mvc.perform(get("/api/profile").header("Host",host)).andExpect(status().isForbidden());
        for(String host:List.of("localhost","LOCALHOST:8080","127.0.0.1:18080","[::1]:8080"))
            mvc.perform(get("/api/health").header("Host",host)).andExpect(status().isOk());
        mvc.perform(get("/api/health").header("Host","localhost","evil.example")).andExpect(status().isForbidden());
        mvc.perform(get("/api/health").header("Host","evil.example").header("X-Forwarded-Host","localhost")).andExpect(status().isForbidden());
    }
    @Test void measureRefreshWritesOnSyntheticJobs() {
        // 固定合成档案，避免测试执行顺序影响前后对照；不读取正式个人档案。
        db.update("""
            UPDATE user_profiles SET settings='{"skills":["Java"],"learningSkills":[],"cities":["成都"],
                "roles":["backend"],"companyTypes":[],"excludedTerms":[],"education":"bachelor",
                "weights":{"role":35,"skills":40,"city":10,"company":0,"qualifications":15}}'::jsonb,
                updated_at=now() WHERE id=1
            """,Map.of());
        // 同一测试既测旧代码也测新代码；统计来自当前事务的 PG 实际行写入，不是 UPSERT 调用估算。
        db.update("""
            INSERT INTO items(kind,canonical_key,title,country,city,payload,content_hash,is_demo)
            SELECT 'job','benchmark:'||n,'合成 Java 实习','CN','成都',
                '{"kind":"job","title":"Java 后端实习","body":"本科 Java SQL","country":"CN","city":"成都","skills":[{"name":"Java"}],"categories":["backend"]}'::jsonb,
                'synthetic',true FROM generate_series(1,200) n
            """,Map.of());
        var tx=new org.springframework.transaction.support.TransactionTemplate(transactionManager);
        for(int round=0;round<6;round++) {
            org.mockito.Mockito.clearInvocations(matcher);
            final int sample=round;
            tx.executeWithoutResult(status->{
                var before=db.queryForMap("SELECT n_tup_ins AS inserted,n_tup_upd AS updated FROM pg_stat_xact_user_tables WHERE relname='match_results'",Map.of());
                long started=System.nanoTime();
                var result=service.refresh();
                double elapsed=(System.nanoTime()-started)/1_000_000.0;
                var writes=db.queryForMap("SELECT n_tup_ins AS inserted,n_tup_upd AS updated FROM pg_stat_xact_user_tables WHERE relname='match_results'",Map.of());
                for(String key:List.of("inserted","updated"))writes.put(key,((Number)writes.get(key)).longValue()-((Number)before.get(key)).longValue());
                long calculations=org.mockito.Mockito.mockingDetails(matcher).getInvocations().stream().filter(i->i.getMethod().getName().equals("match")).count();
                System.out.println("MATCH_BENCHMARK "+Json.encode(Map.of("round",sample,"jobs",200,"milliseconds",elapsed,"calculations",calculations,"writes",writes,"result",result)));
            });
        }
    }
    @Test void localTranslationQueueIsBoundedIdempotentAndStaleCacheCannotLeak() throws Exception {
        long id=item("foreign","上海","Python");
        String request=Json.encode(Map.of("ids",List.of(id),"depth",1,"retry",false));
        mvc.perform(post("/api/translations").with(csrf()).contentType("application/json").content(request)).andExpect(jsonPath("$.state").value("unavailable"));
        db.update("INSERT INTO translation_runtime VALUES (1,true,'synthetic-test-revision','合成队列测试，非真实翻译',now())",Map.of());
        for(int n=0;n<2;n++)mvc.perform(post("/api/translations").with(csrf()).contentType("application/json").content(request)).andExpect(status().isOk());
        assertThat(db.queryForObject("SELECT count(*) FROM reading_translation_jobs",Map.of(),Long.class)).isEqualTo(1L);
        mvc.perform(get("/api/reading").param("ids",Long.toString(id))).andExpect(jsonPath("$[0].reading.processing").value(true)).andExpect(jsonPath("$[0].content_hash").value("hash"));
        String synthetic=Json.encode(Map.of("method","synthetic_test_provider","reviewed",false,"title_zh","合成机译标题","body_zh","仅合成队列测试正文","attribution","测试夹具，非模型运行证据","depth",1));
        db.update("UPDATE reading_translation_jobs SET state='done',result=CAST(:json AS jsonb)",Map.of("json",synthetic));
        mvc.perform(get("/api/items/"+id)).andExpect(jsonPath("$.reading.status").value("current")).andExpect(jsonPath("$.reading.translation.reviewed").value(false));
        db.update("INSERT INTO reading_translations(item_id,content_hash,payload) VALUES (:id,'hash',CAST(:json AS jsonb))",Map.of("id",id,"json",Json.encode(Map.of("title_zh","人工核验合成标题","method","human_reviewed","reviewed",true,"attribution","人工合成夹具"))));
        mvc.perform(get("/api/items/"+id)).andExpect(jsonPath("$.reading.translation.title_zh").value("人工核验合成标题")).andExpect(jsonPath("$.reading.translation.body_zh").value("仅合成队列测试正文"));
        db.update("UPDATE items SET content_hash='updated-source' WHERE id=:id",Map.of("id",id));
        mvc.perform(get("/api/reading").param("ids",Long.toString(id))).andExpect(jsonPath("$[0].reading.status").value("stale")).andExpect(jsonPath("$[0].reading.translation").doesNotExist());
        mvc.perform(post("/api/translations").with(csrf()).contentType("application/json").content(Json.encode(Map.of("ids",java.util.Collections.nCopies(21,id),"depth",1)))).andExpect(status().isBadRequest());
        mvc.perform(post("/api/translations").contentType("application/json").content(request)).andExpect(status().isForbidden());
        assertThat(db.queryForObject("SELECT count(*) FROM ai_usage",Map.of(),Long.class)).isZero();
    }
    private void reviewedEmployer(String name,String origin,String ownership) {
        employers.save(new EmployerRegistry.Review(name,origin,List.of(origin.equals("china_local")?"CN":"DE"),ownership,"合成行业",List.of("https://example.com/synthetic-evidence"),"合成测试核验，非真实公司",java.time.LocalDate.now(),"verified"));
    }
    private void employerFor(long id,String name,String country) {
        db.update("UPDATE items SET country=:country,payload=payload || jsonb_build_object('company',CAST(:company AS text),'country',CAST(:country AS text)) WHERE id=:id",Map.of("id",id,"company",name,"country",country));
    }
    @Test void verifiedOriginAndSameMainlandLocationSeparateCentersWithoutChangingRawLabels() throws Exception {
        long domestic=item("foreign","上海","Python"),foreign=item("private","上海","Python"),overseas=item("foreign","上海","Java"),unknown=item("foreign","北京","Java");
        employerFor(domestic,"本土测试","CN");employerFor(foreign,"境外测试","CN");employerFor(overseas,"境外测试","US");employerFor(unknown,"Unknown English Name","CN");
        reviewedEmployer("本土测试","china_local","private");reviewedEmployer("境外测试","foreign","foundation_owned");
        assertThat(repo.search(Map.of("domain","domestic"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.search(Map.of("domain","foreign"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.search(Map.of("domain","unclassified"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.search(Map.of("domain","all"),0,20).get("total")).isEqualTo(4L);
        assertThat(repo.search(Map.of("domain","domestic","company_type","private"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.detail(domestic).get("company_type")).isEqualTo("foreign"); // source input preserved
        db.update("UPDATE items SET payload=payload || CAST(:json AS jsonb) WHERE id=:id",Map.of("id",overseas,"json",Json.encode(Map.of("locations",List.of(Map.of("country","CN","city","北京"))))));
        assertThat(repo.search(Map.of("domain","foreign","city","上海"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.search(Map.of("domain","foreign","city","北京"),0,20).get("total")).isEqualTo(0L);
        assertThat(repo.search(Map.of("country","CN","city","北京"),0,20).get("total")).isEqualTo(2L);
        mvc.perform(get("/api/classification-summary")).andExpect(jsonPath("$.domestic.jobs").value(1)).andExpect(jsonPath("$.mainland.bachelorStudentInternships").value(0)).andExpect(jsonPath("$.unknownCompanyWorldwide").value(1));
        mvc.perform(put("/api/employers/review").with(csrf()).contentType("application/json").content(Json.encode(Map.of("name","Bad","origin","foreign","ownership","unknown","headquartersCountries",List.of("US"),"evidenceUrls",List.of("https://example.com"),"basis","缺所有制核验","verifiedOn",java.time.LocalDate.now().toString(),"status","verified")))).andExpect(status().isBadRequest());
    }
    @Test void mainlandCenterRejectsHongKongMacauTaiwanDespiteSourceCountryCode() {
        reviewedEmployer("Regional Group","foreign","publicly_listed");
        for(String city:List.of("Hong Kong","香港","Macao","Macau","澳门","Taipei","臺北")) {
            long id=item("foreign",city,"Python");employerFor(id,"Regional Group","CN");
        }
        long mainland=item("foreign","上海","Python");employerFor(mainland,"Regional Group","CN");
        assertThat(repo.search(Map.of("domain","foreign","includeDemo","true"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.search(Map.of("country","CN","includeDemo","true"),0,20).get("total")).isEqualTo(8L);
    }
    @Test void databaseSortAcrossPagesFiltersNullsTiesAndDetailUseSameCalculatedResult() throws Exception {
        var profile=new HashMap<>(service.profile());profile.put("skills",List.of("Python"));profile.put("roles",List.of("data_engineering"));profile.put("cities",List.of("上海"));profile.put("education","bachelor");profile.put("graduationYear",2027);
        db.update("UPDATE user_profiles SET settings=CAST(:json AS jsonb),updated_at=now()",Map.of("json",Json.encode(profile)));
        reviewedEmployer("Sort Company","foreign","publicly_listed");
        var ids=new ArrayList<Long>();
        for(int n=0;n<7;n++) {
            long id=item("foreign","上海","Python");employerFor(id,"Sort Company","CN");ids.add(id);
            var payload=Json.map(repo.detail(id).get("payload"));payload.put("body","数据工程实习，负责开发数据管道和数据仓库。要求Python和SQL，2027届本科。此为合成排序测试。");
            payload.put("skills",n%2==0?List.of(Map.of("name","Python","requirement","required","evidence","要求Python")):List.of(Map.of("name","Java","requirement","required","evidence","要求Java")));
            db.update("UPDATE items SET payload=CAST(:json AS jsonb),published_at=now()-CAST(:days AS int)*interval '1 day',deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date+CAST(:days AS int) WHERE id=:id",Map.of("id",id,"json",Json.encode(payload),"days",n));
        }
        service.refresh();
        long pending=item("foreign","上海","Python");employerFor(pending,"Sort Company","CN");
        var found=new ArrayList<Map<String,Object>>();
        for(int page=0;page<3;page++)found.addAll((List<Map<String,Object>>)repo.search(Map.of("domain","foreign","city","上海","q","数据","sort","match_desc"),page,3).get("items"));
        assertThat(found).hasSize(8);assertThat(found.stream().map(r->r.get("id")).distinct()).hasSize(8);
        assertThat(found.getLast().get("id")).isEqualTo(pending);assertThat(found.getLast().get("score")).isNull();
        for(int n=1;n<7;n++)assertThat(((Number)found.get(n-1).get("score")).doubleValue()).isGreaterThanOrEqualTo(((Number)found.get(n).get("score")).doubleValue());
        for(var row:found)assertThat(repo.detail(((Number)row.get("id")).longValue()).get("score")).isEqualTo(row.get("score"));
        assertThat(((List<Map<String,Object>>)repo.search(Map.of("domain","foreign","city","上海","q","数据","sort","match_desc"),0,100).get("items")).stream().map(r->r.get("id")).toList()).isEqualTo(found.stream().map(r->r.get("id")).toList());
        assertThat(((List<Map<String,Object>>)repo.search(Map.of("domain","foreign","sort","deadline_asc"),0,20).get("items")).getFirst().get("id")).isEqualTo(ids.getFirst());
        assertThat(((List<Map<String,Object>>)repo.search(Map.of("domain","foreign","sort","first_seen_desc"),0,20).get("items")).getFirst().get("id")).isEqualTo(pending);
        var asc=(List<Map<String,Object>>)repo.search(Map.of("domain","foreign","sort","match_asc"),0,20).get("items");
        for(int n=1;n<7;n++)assertThat(((Number)asc.get(n-1).get("score")).doubleValue()).isLessThanOrEqualTo(((Number)asc.get(n).get("score")).doubleValue());
        assertThat(asc.getLast().get("id")).isEqualTo(pending);
        assertThat(((List<Map<String,Object>>)repo.search(Map.of("domain","foreign","sort","published_desc"),0,20).get("items")).getFirst().get("id")).isEqualTo(ids.getFirst());
        mvc.perform(get("/api/items?sort=score;DROP TABLE items")).andExpect(status().isBadRequest());
        reviewedEmployer("Sort Company","foreign","foundation_owned");
        assertThat(repo.detail(ids.getFirst()).get("matching_status")).isEqualTo("pending");service.refresh();
        assertThat(repo.detail(ids.getFirst()).get("matching_status")).isEqualTo("current");
        profile.put("skills",List.of("Java"));mvc.perform(put("/api/profile").with(csrf()).contentType("application/json").content(Json.encode(profile))).andExpect(status().isOk());
        assertThat(repo.detail(ids.getFirst()).get("score")).isNull();service.refresh();
        var changed=(List<Map<String,Object>>)repo.search(Map.of("domain","foreign","sort","match_desc"),0,20).get("items");
        assertThat(((Number)changed.stream().filter(r->r.get("id").equals(ids.get(1))).findFirst().orElseThrow().get("score")).doubleValue()).isGreaterThan(((Number)repo.detail(ids.getFirst()).get("score")).doubleValue());
    }
    @Test void readingCacheIsAdditiveAndExpiredTranslationsNeverLeakIntoResponses() throws Exception {
        long id=item("foreign","上海","Python");
        String original=Json.encode(repo.detail(id).get("payload"));
        String translated=Json.encode(Map.of("method","human_reviewed","reviewed",true,"attribution","合成夹具人工核验","title_zh","中文参考名称","summary_zh","合成中文摘要"));
        db.update("INSERT INTO reading_translations(item_id,content_hash,payload) VALUES (:id,'hash',CAST(:payload AS jsonb))",Map.of("id",id,"payload",translated));
        mvc.perform(get("/api/items/"+id)).andExpect(jsonPath("$.reading.status").value("current"))
            .andExpect(jsonPath("$.reading.translation.title_zh").value("中文参考名称"));
        mvc.perform(get("/api/items?country=CN&q=Python")).andExpect(jsonPath("$.total").value(1))
            .andExpect(jsonPath("$.items[0].reading.translation.summary_zh").value("合成中文摘要"));
        assertThat(Json.encode(repo.detail(id).get("payload"))).isEqualTo(original);
        db.update("UPDATE items SET content_hash='new',payload=jsonb_set(payload,'{body}','\"Changed English content\"') WHERE id=:id",Map.of("id",id));
        mvc.perform(get("/api/items/"+id)).andExpect(jsonPath("$.reading.status").value("stale"))
            .andExpect(jsonPath("$.reading.translation").doesNotExist()).andExpect(jsonPath("$.payload.body").value("Changed English content"));
        assertThat(db.queryForObject("SELECT count(*) FROM reading_translations WHERE item_id=:id",Map.of("id",id),Long.class)).isEqualTo(1L);
    }
    @Test void savedRawOriginalComesFromCurrentVersionNotLatestUnrelatedSource() throws Exception {
        long id=item("foreign","上海","Python");
        String rawText="Full original\nsecond paragraph <script>alert(1)</script>";
        long raw=db.queryForObject("INSERT INTO raw_records(source_id,external_id,raw_hash,body) VALUES (1,'reading','raw',CAST(:body AS jsonb)) RETURNING id",Map.of("body",Json.encode(Map.of("body",rawText))),Long.class);
        db.update("INSERT INTO item_versions(item_id,version,payload,changed_fields,raw_id) SELECT id,1,payload,'[]',:raw FROM items WHERE id=:id",Map.of("id",id,"raw",raw));
        mvc.perform(get("/api/items/"+id)).andExpect(jsonPath("$.original.body").value(rawText)).andExpect(jsonPath("$.original.complete").value(false));
        mvc.perform(get("/view/domestic")).andExpect(content().string(org.hamcrest.Matchers.containsString("reading-mode")))
            .andExpect(content().string(org.hamcrest.Matchers.containsString("/reading.js")));
    }
    @Test void healthIdentifiesDatabaseAndProcessWithoutCredentials() throws Exception {
        mvc.perform(get("/api/health")).andExpect(status().isOk())
            .andExpect(jsonPath("$.database").value(org.hamcrest.Matchers.endsWith("_test")))
            .andExpect(jsonPath("$.pid").isNumber()).andExpect(jsonPath("$.status").value("ok"))
            .andExpect(jsonPath("$.password").doesNotExist()).andExpect(jsonPath("$.profile").doesNotExist());
    }
    @Test void unsafeOrRelativeImportUrlReportsSafeActionableError() throws Exception {
        for(String url:List.of("relative/path","javascript:alert(1)","https://secret:private@example.com/job","https://example.com/%bad value")) {
            var payload=Map.of("sourceId",1,"records",List.of(Map.of("kind","job","external_id","invalid","title","测试","url",url)));
            mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(Json.encode(payload)))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error").value(org.hamcrest.Matchers.containsString("官方链接格式无效")))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("secret:private"))));
        }
        assertThat(db.queryForObject("SELECT count(*) FROM task_requests",Map.of(),Long.class)).isZero();
    }
    @Test void unreadSummaryAndPaginationIncludeAlertsBeyondOldLimit() throws Exception {
        db.update("INSERT INTO alerts(dedup_key,message) SELECT 'pagination:'||n,'合成提醒'||n FROM generate_series(1,205) n",Map.of());
        mvc.perform(get("/api/alerts/summary")).andExpect(jsonPath("$.total").value(205)).andExpect(jsonPath("$.unread").value(205));
        mvc.perform(get("/api/alerts").param("page","17").param("size","12"))
            .andExpect(jsonPath("$.length()").value(1)).andExpect(jsonPath("$[0].message").value("合成提醒1"));
        long id=db.queryForObject("SELECT id FROM alerts WHERE dedup_key='pagination:1'",Map.of(),Long.class);
        mvc.perform(put("/api/alerts/"+id+"/read").with(csrf())).andExpect(status().isOk());
        mvc.perform(get("/api/alerts/summary")).andExpect(jsonPath("$.total").value(205)).andExpect(jsonPath("$.unread").value(204));
        mvc.perform(get("/api/alerts").param("page","-1")).andExpect(status().isBadRequest());
        mvc.perform(get("/api/alerts").param("size","201")).andExpect(status().isBadRequest());
    }
    @Test void maintenanceHistoryFiltersBulkReadAndNewArrivalCutoff() throws Exception {
        long id=item("foreign","上海","Python");
        long raw=db.queryForObject("INSERT INTO raw_records(source_id,external_id,raw_hash,body) VALUES (1,'review','review','{}') RETURNING id",Map.of(),Long.class);
        db.update("INSERT INTO item_versions(item_id,version,payload,changed_fields,raw_id) SELECT id,1,payload,'[]',:raw FROM items WHERE id=:id",Map.of("id",id,"raw",raw));
        db.update("INSERT INTO item_versions(item_id,version,payload,changed_fields,raw_id) SELECT id,2,payload,'[\"skills\"]',:raw FROM items WHERE id=:id",Map.of("id",id,"raw",raw));
        db.update("INSERT INTO alerts(item_id,dedup_key,message) VALUES (:id,:key,'合成维护提醒')",Map.of("id",id,"key","change:"+id+":2"));
        db.update("INSERT INTO alerts(item_id,dedup_key,message) VALUES (:id,:key,'合成业务提醒')",Map.of("id",id,"key","subscription:1:"+id+":1"));
        db.update("INSERT INTO alerts(dedup_key,message) VALUES ('test:unknown','合成无实体提醒')",Map.of());
        assertThat(service.alertSummary("all","maintenance",false).get("total")).isEqualTo(1L);
        assertThat(service.alertSummary("unread","actionable",false).get("total")).isEqualTo(2L);
        mvc.perform(get("/api/alerts?type=maintenance&includeDemo=false")).andExpect(jsonPath("$[0].alert_type").value("maintenance"));
        long cutoff=((Number)service.alertSummary("unread","actionable",false).get("through_id")).longValue();
        db.update("INSERT INTO alerts(dedup_key,message) VALUES ('test:new','筛选后到达')",Map.of());
        mvc.perform(put("/api/alerts/read?type=actionable&state=unread&includeDemo=false&throughId="+cutoff)).andExpect(status().isForbidden());
        mvc.perform(put("/api/alerts/read?type=actionable&state=unread&includeDemo=false&throughId="+cutoff).with(csrf())).andExpect(jsonPath("$.updated").value(2));
        assertThat(service.alertSummary("unread","maintenance",false).get("unread")).isEqualTo(1L);
        assertThat(service.alertSummary("unread","actionable",false).get("unread")).isEqualTo(1L);
        assertThat(service.alertSummary().get("total")).isEqualTo(4L);
        assertThat(service.readAlerts("unread","actionable",false,cutoff).get("updated")).isEqualTo(0);
        long readId=db.queryForObject("SELECT id FROM alerts WHERE dedup_key LIKE 'subscription:%'",Map.of(),Long.class);
        Object originalRead=db.queryForObject("SELECT read_at FROM alerts WHERE id=:id",Map.of("id",readId),Object.class);
        service.readAlert(readId);
        assertThat(db.queryForObject("SELECT read_at FROM alerts WHERE id=:id",Map.of("id",readId),Object.class)).isEqualTo(originalRead);
        mvc.perform(get("/api/alerts?type=invalid")).andExpect(status().isBadRequest());
        mvc.perform(get("/api/alerts/summary?state=invalid")).andExpect(status().isBadRequest());
        mvc.perform(put("/api/alerts/999999/read").with(csrf())).andExpect(status().isNotFound());
    }
    @Test void subscriptionParserUpdatesDoNotNotifyAgainButNewSubscriptionCanBackfill() {
        long id=item("foreign","上海","Python");
        long raw=db.queryForObject("INSERT INTO raw_records(source_id,external_id,raw_hash,body) VALUES (1,'subscription-review','raw','{}') RETURNING id",Map.of(),Long.class);
        db.update("INSERT INTO item_versions(item_id,version,payload,changed_fields,raw_id) SELECT id,1,payload,'[]',:raw FROM items WHERE id=:id",Map.of("id",id,"raw",raw));
        service.subscription(new Contracts.Subscription("合成订阅",Map.of("kind","job"),true));service.refresh();
        assertThat(service.alerts()).hasSize(1);
        db.update("INSERT INTO item_versions(item_id,version,payload,changed_fields,raw_id) SELECT id,2,payload,'[\"skills\"]',:raw FROM items WHERE id=:id",Map.of("id",id,"raw",raw));
        db.update("UPDATE items SET version=2 WHERE id=:id",Map.of("id",id));service.refresh();service.refresh();
        assertThat(service.alerts()).hasSize(1);
        service.subscription(new Contracts.Subscription("新合成订阅",Map.of("kind","job"),true));service.refresh();service.refresh();
        assertThat(service.alerts()).hasSize(2);
        long fresh=db.queryForObject("INSERT INTO raw_records(source_id,external_id,raw_hash,body) VALUES (1,'subscription-review','changed','{}') RETURNING id",Map.of(),Long.class);
        db.update("INSERT INTO item_versions(item_id,version,payload,changed_fields,raw_id) SELECT id,3,payload,'[\"body\"]',:raw FROM items WHERE id=:id",Map.of("id",id,"raw",fresh));
        db.update("UPDATE items SET version=3 WHERE id=:id",Map.of("id",id));service.refresh();service.refresh();
        assertThat(service.alerts()).hasSize(4);
        assertThat(service.alerts(0,20,"all","subscription",false)).hasSize(4);
        db.update("UPDATE items SET is_demo=true WHERE id=:id",Map.of("id",id));
        assertThat(service.alertSummary("all","all",false).get("total")).isEqualTo(0L);
        assertThat(service.alertSummary().get("total")).isEqualTo(4L);
    }
    @Test void keywordWildcardsAreLiteralAndAgreeWithSubscription() {
        long id=item("foreign","上海","Python");long other=item("foreign","上海","SQL");
        db.update("UPDATE items SET title='100%_Python',payload=jsonb_set(payload,'{title}','\"100%_Python\"') WHERE id=:id",Map.of("id",id));
        assertThat(repo.search(Map.of("q","%_"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.stats(Map.of("q","%_")).get("sampleSize")).isEqualTo(1L);
        service.subscription(new Contracts.Subscription("符号关键字",Map.of("kind","job","q","%_"),true));
        service.refresh();assertThat(service.alerts()).hasSize(1);
        assertThat(repo.search(Map.of("q","\\"),0,20).get("total")).isEqualTo(0L);
        db.update("UPDATE items SET payload=jsonb_set(payload,'{company}','\"Unique%_Company\"') WHERE id=:id",Map.of("id",other));
        assertThat(repo.search(Map.of("q","Unique%_Company"),0,20).get("total")).isEqualTo(1L);
        service.subscription(new Contracts.Subscription("企业关键字",Map.of("kind","job","q","Unique%_Company"),true));
        service.refresh();assertThat(service.alerts()).hasSize(3);
        assertThat(repo.search(Map.of("q","%_"),0,20).get("total")).isEqualTo(2L);
        // 两个不同规则都匹配同一岗位，各保留一条带订阅名的通知；重复刷新不增加。
        service.refresh();assertThat(service.alerts()).hasSize(3);
    }
    @Test void unreviewedSourceLabelsNeverCreateDomesticOrForeignMembership() {item("foreign","上海","Python");item("private","杭州","Java");assertThat(repo.search(Map.of("domain","domestic"),0,20).get("total")).isEqualTo(0L);assertThat(repo.search(Map.of("domain","foreign"),0,20).get("total")).isEqualTo(0L);assertThat(repo.search(Map.of("domain","unclassified"),0,20).get("total")).isEqualTo(2L);assertThat(repo.search(Map.of("city","杭州"),0,20).get("total")).isEqualTo(1L);}
    @Test void companySubscriptionsUseVerifiedFactsAndUnknownStaysUnknown() {
        long domestic=item("foreign","上海","Python"),foreign=item("private","上海","Python"),unknown=item("foreign","上海","Python");
        employerFor(domestic,"订阅本土企业","CN");employerFor(foreign,"订阅境外企业","CN");employerFor(unknown,"订阅未核验企业","CN");
        service.subscription(new Contracts.Subscription("已核验外企",Map.of("kind","job","company_type","foreign"),true));
        service.refresh();assertThat(service.alerts()).isEmpty();
        reviewedEmployer("订阅本土企业","china_local","private");reviewedEmployer("订阅境外企业","foreign","publicly_listed");
        service.refresh();assertThat(service.alerts()).extracting(a->a.get("item_id")).containsExactly(foreign);
        service.subscription(new Contracts.Subscription("已核验民企",Map.of("kind","job","company_type","private"),true));
        service.subscription(new Contracts.Subscription("企业未知",Map.of("kind","job","company_type","unknown"),true));
        service.refresh();service.refresh();
        assertThat(service.alerts()).extracting(a->a.get("item_id")).containsExactlyInAnyOrder(domestic,foreign,unknown);
        assertThat(repo.detail(domestic).get("company_type")).isEqualTo("foreign");
        assertThat(repo.search(Map.of("domain","foreign"),0,20).get("total")).isEqualTo(1L);
    }
    @Test void companyFiltersAndSkillStatsUseVerifiedFactsAcrossAllJobViews() {
        long domestic=item("foreign","上海","Python"),foreign=item("private","上海","Java"),unknown=item("foreign","北京","SQL");
        employerFor(domestic,"筛选本土企业","CN");employerFor(foreign,"筛选境外企业","CN");employerFor(unknown,"筛选未核验企业","CN");
        reviewedEmployer("筛选本土企业","china_local","private");reviewedEmployer("筛选境外企业","foreign","publicly_listed");
        for(var scope:List.of(Map.<String,String>of(),Map.of("domain","all"),Map.of("domain","mainland"))) {
            for(var expected:Map.of("private",domestic,"foreign",foreign,"unknown",unknown).entrySet()) {
                var query=new HashMap<>(scope);query.put("company_type",expected.getKey());
                var rows=(List<Map<String,Object>>)repo.search(query,0,20).get("items");
                assertThat(rows).extracting(row->row.get("id")).containsExactly(expected.getValue());
                assertThat(repo.stats(query).get("sampleSize")).isEqualTo(1L);
            }
        }
        // Pending evidence cannot turn a source label into a verified fact.
        employers.save(new EmployerRegistry.Review("筛选未核验企业","unclassified",List.of(),"unknown","合成行业",List.of("https://example.com/synthetic-evidence"),"合成待核验资料",java.time.LocalDate.now(),"pending"));
        assertThat(repo.search(Map.of("domain","unclassified","company_type","unknown"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.detail(domestic).get("company_type")).isEqualTo("foreign");
        long release=item("private","上海","Python");employerFor(release,"筛选境外企业","CN");
        db.update("UPDATE items SET kind='release',payload=jsonb_set(payload,'{kind}','\"release\"') WHERE id=:id",Map.of("id",release));
        assertThat(repo.search(Map.of("kind","release","company_type","private"),0,20).get("total")).isEqualTo(1L);
    }
    @Test void nullProfileElementsAreRejectedBeforeSaving() throws Exception {
        var before=service.profile();
        for(String key:List.of("skills","learningSkills","cities","roles","companyTypes","excludedTerms","internshipTypes","employmentTypes")) {
            var profile=new HashMap<>(before);profile.put(key,Arrays.asList((Object)null));
            mvc.perform(put("/api/profile").with(csrf()).contentType("application/json").content(Json.encode(profile))).andExpect(status().isBadRequest());
        }
        var profile=new HashMap<>(before);var weights=new HashMap<>(Json.map(before.get("weights")));weights.put("skills",null);profile.put("weights",weights);
        mvc.perform(put("/api/profile").with(csrf()).contentType("application/json").content(Json.encode(profile))).andExpect(status().isBadRequest());
        assertThat(service.profile()).isEqualTo(before);
    }
    @Test void legacyNullProfileEntriesRemainUnknownWithoutBreakingRefresh() {
        item("foreign","上海","Python");var before=service.profile();var profile=new HashMap<>(before);
        try {
            for(String key:List.of("skills","learningSkills","cities","roles","companyTypes","excludedTerms","internshipTypes","employmentTypes"))profile.put(key,Arrays.asList((Object)null));
            db.update("UPDATE user_profiles SET settings=CAST(:json AS jsonb),updated_at=now()",Map.of("json",Json.encode(profile)));
            assertThat(service.refresh().get("matchedJobs")).isEqualTo(1);
            assertThat(db.queryForObject("SELECT score FROM match_results",Map.of(),Double.class)).isZero();
            assertThat(service.profile()).isEqualTo(profile); // 读取降级，不静默改写用户档案。
        } finally {
            db.update("UPDATE user_profiles SET settings=CAST(:json AS jsonb),updated_at=now()",Map.of("json",Json.encode(before)));
        }
    }
    @Test void nullImportElementsNeverCreateAnUnprocessableTask() throws Exception {
        mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content("{\"sourceId\":1,\"records\":[null]}")).andExpect(status().isBadRequest());
        var record=new HashMap<String,Object>(Map.of("kind","job","external_id","null-elements","title","合成输入校验","body","要求Python或Java任选一项"));
        for(String key:List.of("skills","locations","skill_groups","experience_requirements","risk_notes")) {
            var invalid=new HashMap<>(record);invalid.put(key,Arrays.asList((Object)null));
            mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(Json.encode(Map.of("sourceId",1,"records",List.of(invalid))))).andExpect(status().isBadRequest());
        }
        record.put("skill_groups",List.of(Map.of("names",Arrays.asList("Python",null),"minimum",1,"requirement","required","evidence",record.get("body"))));
        mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(Json.encode(Map.of("sourceId",1,"records",List.of(record))))).andExpect(status().isBadRequest());
        assertThat(db.queryForObject("SELECT count(*) FROM task_requests",Map.of(),Long.class)).isZero();
    }
    @Test void nullHeadquartersCannotBeSavedAsVerified() throws Exception {
        var review=Map.of("name","合成无总部","origin","foreign","headquartersCountries",Arrays.asList((Object)null),"ownership","publicly_listed","evidenceUrls",List.of("https://example.com"),"basis","合成验证","verifiedOn",java.time.LocalDate.now().toString(),"status","verified");
        mvc.perform(put("/api/employers/review").with(csrf()).contentType("application/json").content(Json.encode(review))).andExpect(status().isBadRequest());
        assertThat(employers.all()).isEmpty();
    }
    @Test void nullTranslationIdsAreRejectedBeforeQueueing() throws Exception {
        mvc.perform(post("/api/translations").with(csrf()).contentType("application/json").content("{\"ids\":[null],\"depth\":1}")).andExpect(status().isBadRequest());
        assertThat(db.queryForObject("SELECT count(*) FROM reading_translation_jobs",Map.of(),Long.class)).isZero();
    }
    @Test void detailReturnsMatchByExactIdDespiteSameTitlesAndPagination() throws Exception {
        long requested=item("foreign","上海","Python");
        for(int i=0;i<100;i++)item("private","杭州","Java");
        db.update("INSERT INTO match_results(item_id,hard_status,score,explanation,item_version,profile_updated_at,engine_revision,employer_revision) VALUES (:id,'eligible',89,CAST(:json AS jsonb),1,(SELECT updated_at FROM user_profiles WHERE id=1),:revision,0)",Map.of("id",requested,"revision",MatchingEngine.REVISION,"json",Json.encode(Map.of("hardStatus","eligible","score",89,"reasons",List.of("原始ID对应的结果")))));
        assertThat(((List<?>)repo.search(Map.of("q","数据工程实习"),0,100).get("items"))).hasSize(100);
        assertThat(Json.map(repo.detail(requested).get("explanation")).get("score")).isEqualTo(89);
        mvc.perform(get("/api/items/"+requested)).andExpect(status().isOk()).andExpect(jsonPath("$.explanation.score").value(89));
    }
    @Test void staleMatchesAreHiddenForItemProfileEngineAndLegacyRevisions() throws Exception {
        long id=item("foreign","上海","Python");service.refresh();
        assertThat(repo.detail(id).get("matching_status")).isEqualTo("current");
        db.update("UPDATE items SET version=version+1 WHERE id=:id",Map.of("id",id));
        mvc.perform(get("/api/items/"+id)).andExpect(jsonPath("$.matching_status").value("pending")).andExpect(jsonPath("$.score").isEmpty()).andExpect(jsonPath("$.explanation").isEmpty());
        var list=(List<Map<String,Object>>)repo.search(Map.of(),0,20).get("items");
        assertThat(list.getFirst().get("score")).isNull();service.refresh();
        db.update("UPDATE user_profiles SET updated_at=updated_at+interval '1 microsecond' WHERE id=1",Map.of());
        assertThat(repo.detail(id).get("explanation")).isNull();service.refresh();
        db.update("UPDATE match_results SET engine_revision='old-rule' WHERE item_id=:id",Map.of("id",id));
        assertThat(repo.detail(id).get("matching_status")).isEqualTo("pending");service.refresh();
        db.update("UPDATE match_results SET item_version=NULL,profile_updated_at=NULL,engine_revision=NULL WHERE item_id=:id",Map.of("id",id));
        assertThat(repo.detail(id).get("score")).isNull();
        assertThat(db.queryForObject("SELECT count(*) FROM match_results",Map.of(),Long.class)).isEqualTo(1L);
    }
    @Test void detailUsesOneSnapshotWhenEtlCommitsBetweenPayloadAndSkillsReads() throws Exception {
        long id=item("foreign","上海","Python");service.refresh();
        db.update("INSERT INTO item_versions(item_id,version,payload,changed_fields) SELECT id,version,payload,'[]' FROM items WHERE id=:id",Map.of("id",id));
        var once=new java.util.concurrent.atomic.AtomicBoolean();
        org.mockito.Mockito.doAnswer(invocation->{
            Object answer=invocation.callRealMethod();String sql=invocation.getArgument(0);
            if(sql.contains("WHERE i.id=:id") && once.compareAndSet(false,true)) {
                java.util.concurrent.CompletableFuture.runAsync(()->new org.springframework.transaction.support.TransactionTemplate(transactionManager).executeWithoutResult(tx->{
                    db.update("UPDATE items SET version=2,payload=jsonb_set(payload,'{skills}','[{\"name\":\"Java\"}]') WHERE id=:id",Map.of("id",id));
                    db.update("DELETE FROM job_skills WHERE item_id=:id",Map.of("id",id));
                    db.update("INSERT INTO job_skills(item_id,skill,requirement,evidence) VALUES (:id,'Java','required','Java')",Map.of("id",id));
                    db.update("INSERT INTO item_versions(item_id,version,payload,changed_fields) SELECT id,version,payload,'[]' FROM items WHERE id=:id",Map.of("id",id));
                })).get(5,java.util.concurrent.TimeUnit.SECONDS);
            }
            return answer;
        }).when(db).queryForList(org.mockito.ArgumentMatchers.anyString(),org.mockito.ArgumentMatchers.<String,Object>anyMap());
        var snapshot=repo.detail(id);
        assertThat(snapshot.get("version")).isEqualTo(1);
        assertThat(((List<Map<String,Object>>)snapshot.get("skills")).getFirst().get("skill")).isEqualTo("Python");
        assertThat((List<?>)snapshot.get("versions")).hasSize(1);
        var latest=repo.detail(id);assertThat(latest.get("version")).isEqualTo(2);
        assertThat(latest.get("matching_status")).isEqualTo("pending");
        assertThat(((List<Map<String,Object>>)latest.get("skills")).getFirst().get("skill")).isEqualTo("Java");
    }
    @Test void taskByIdPersistsPartialFailureAndNeverReturnsImportPayload() throws Exception {
        long id=service.enqueue("import",1,Map.of("records",List.of(Map.of("body","synthetic private import text"))));
        mvc.perform(get("/api/tasks/"+id)).andExpect(status().isOk()).andExpect(jsonPath("$.state").value("pending")).andExpect(jsonPath("$.payload").doesNotExist());
        db.update("UPDATE task_requests SET state='failed',result=CAST(:json AS jsonb) WHERE id=:id",Map.of("id",id,"json",Json.encode(Map.of("state","partial","inserted",1,"failed",1))));
        mvc.perform(get("/api/tasks/"+id)).andExpect(jsonPath("$.state").value("failed")).andExpect(jsonPath("$.result.state").value("partial")).andExpect(jsonPath("$.result.inserted").value(1));
        mvc.perform(get("/api/tasks/999999")).andExpect(status().isNotFound());
    }
    @Test void smartRecruitersSourceConfigValidatedBeforeSaving() throws Exception {
        String body="""
            {"name":"SR测试","adapter":"smartrecruiters","enabled":false,
             "config":{"board":"BoschGroup","country":"CN","q":"Python","max_items":50,"intern_only":false}}
            """;
        mvc.perform(post("/api/sources").with(csrf()).contentType("application/json").content(body)).andExpect(status().isOk());
        for(String invalid:List.of(body.replace("BoschGroup","../private"),body.replace("\"CN\"","\"China\""),body.replace("\"max_items\":50","\"max_items\":201"),body.replace("\"intern_only\":false","\"intern_only\":\"false\"")))
            mvc.perform(post("/api/sources").with(csrf()).contentType("application/json").content(invalid)).andExpect(status().isBadRequest());
        assertThat(db.queryForObject("SELECT count(*) FROM sources WHERE adapter='smartrecruiters'",Map.of(),Long.class)).isEqualTo(1L);
    }
    @Test void leverPublicConfigAndMigrationAcceptOnlyValidatedFields() throws Exception {
        String body="""
            {"name":"Lever测试","adapter":"lever","enabled":false,
             "config":{"board":"veeva","country":"CN","commitment":"Internship","max_items":20,"intern_only":true}}
            """;
        mvc.perform(post("/api/sources").with(csrf()).contentType("application/json").content(body)).andExpect(status().isOk());
        for(String invalid:List.of(body.replace("veeva","../private"),body.replace("\"CN\"","\"China\""),body.replace("\"Internship\"","null"),body.replace("\"max_items\":20","\"max_items\":true"),body.replace("\"intern_only\":true","\"intern_only\":\"true\"")))
            mvc.perform(post("/api/sources").with(csrf()).contentType("application/json").content(invalid)).andExpect(status().isBadRequest());
        assertThat(db.queryForObject("SELECT count(*) FROM sources WHERE adapter='lever'",Map.of(),Long.class)).isEqualTo(1L);
    }
    @Test void monitoringExposesRunModeWithoutGuessingHistoricalRuns() throws Exception {
        db.update("INSERT INTO collection_runs(source_id,state) VALUES (1,'success')",Map.of());
        db.update("INSERT INTO collection_runs(source_id,state,mode) VALUES (1,'success','archive_reparse')",Map.of());
        mvc.perform(get("/api/monitor")).andExpect(status().isOk()).andExpect(jsonPath("$.runs[0].mode").value("archive_reparse")).andExpect(jsonPath("$.runs[1].mode").value("legacy"));
    }
    @Test void statsUniqueSamplesSourceDateAndRequirement() {long id=item("foreign","上海","Python");item("private","杭州","Java");db.update("INSERT INTO job_skills VALUES (:id,'Spark','preferred','Spark加分','rule')",Map.of("id",id));var stats=repo.stats(Map.of("source","1","from","2000-01-01","to","2099-01-01"));assertThat(stats.get("sampleSize")).isEqualTo(2L);assertThat((List<?>)stats.get("skills")).hasSize(3);assertThat(repo.stats(Map.of("from","2099-01-01")).get("sampleSize")).isEqualTo(0L);}
    @Test void applicationsHistoryAndDeadlineRemindersDeduplicate() {long id=item("foreign","上海","Python");db.update("UPDATE items SET deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date+2 WHERE id=:id",Map.of("id",id));service.saveApplication(id,new Contracts.Application("applied","备注",java.time.OffsetDateTime.now(),null,null));service.saveApplication(id,new Contracts.Application("interview1","更新",null,null,null));assertThat(service.applications()).hasSize(1);assertThat(service.history(id)).hasSize(2);service.refresh();service.refresh();assertThat(service.alerts()).hasSize(1);db.update("UPDATE items SET deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date-1 WHERE id=:id",Map.of("id",id));assertThat(repo.detail(id).get("deadline_status")).isEqualTo("expired");}
    @Test void applicationNextActionSurvivesReadsAndStatusUpdatesWithoutChangingJobEvidence() throws Exception {
        long id=item("private","成都","Java");
        db.update("UPDATE items SET payload=payload || '{\"company\":\"合成测试企业\"}'::jsonb WHERE id=:id",Map.of("id",id));
        var originalItem=db.queryForMap("SELECT * FROM items WHERE id=:id",Map.of("id",id));
        // A row created before V12 remains readable with an unknown next action.
        db.update("INSERT INTO job_applications(item_id,status,notes) VALUES (:id,'saved','旧收藏备注')",Map.of("id",id));
        assertThat(service.applications().getFirst()).containsEntry("next_action",null).containsEntry("company","合成测试企业").containsEntry("city","成都");
        String next="核对官网毕业届别及每周到岗天数";
        mvc.perform(put("/api/applications/"+id).with(csrf()).contentType("application/json")
            .content(Json.encode(Map.of("status","preparing","notes","合成备注","nextAction",next))))
            .andExpect(status().isOk());
        mvc.perform(get("/api/applications")).andExpect(status().isOk())
            .andExpect(jsonPath("$[0].status").value("preparing"))
            .andExpect(jsonPath("$[0].next_action").value(next))
            .andExpect(jsonPath("$[0].company").value("合成测试企业"))
            .andExpect(jsonPath("$[0].city").value("成都"));
        mvc.perform(put("/api/applications/"+id).with(csrf()).contentType("application/json")
            .content(Json.encode(Map.of("status","applied","notes","已自行投递，合成测试","nextAction","等待官网回执"))))
            .andExpect(status().isOk());
        assertThat(service.applications().getFirst()).containsEntry("status","applied").containsEntry("next_action","等待官网回执");
        var history=service.history(id);
        assertThat(history).hasSize(2);
        assertThat(Json.map(history.getFirst().get("snapshot"))).containsEntry("nextAction","等待官网回执");
        assertThat(Json.map(history.getLast().get("snapshot"))).containsEntry("nextAction",next);
        assertThat(db.queryForMap("SELECT * FROM items WHERE id=:id",Map.of("id",id))).isEqualTo(originalItem);
        // The optional field keeps old API payloads and Java callers compatible.
        mvc.perform(put("/api/applications/"+id).with(csrf()).contentType("application/json").content("{\"status\":\"saved\",\"notes\":\"旧客户端\"}"))
            .andExpect(status().isOk());
        assertThat(service.applications().getFirst()).containsEntry("next_action",null);
    }
    @Test void applicationNextActionRejectsOversizeWithoutLosingSavedState() throws Exception {
        long id=item("private","重庆","Java");
        service.saveApplication(id,new Contracts.Application("saved","保留备注",null,null,null,"核对实习时长"));
        var before=service.applications();
        mvc.perform(put("/api/applications/"+id).with(csrf()).contentType("application/json")
            .content(Json.encode(Map.of("status","applied","nextAction","测".repeat(501)))))
            .andExpect(status().isBadRequest());
        assertThat(service.applications()).isEqualTo(before);
        assertThat(service.history(id)).hasSize(1);
        assertThatThrownBy(()->db.update("UPDATE job_applications SET next_action=:next WHERE item_id=:id",Map.of("id",id,"next","测".repeat(501))))
            .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(service.applications()).isEqualTo(before);
    }
    @Test void subscriptionNewVersionAlertsDeduplicate() {item("foreign","上海","Python");service.subscription(new Contracts.Subscription("数据实习",Map.of("kind","job","category","data_engineering"),true));service.refresh();service.refresh();assertThat(service.alerts()).hasSize(1);db.update("UPDATE items SET version=2",Map.of());service.refresh();assertThat(service.alerts()).hasSize(2);}
    @Test void subscriptionsSkipExpiredAndClosedButKeepTodayUnknownAndHistory() {
        long yesterday=item("foreign","上海","Python"),today=item("foreign","上海","Python"),unknown=item("foreign","上海","Python");
        db.update("UPDATE items SET deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date-1 WHERE id=:id",Map.of("id",yesterday));
        db.update("UPDATE items SET deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date WHERE id=:id",Map.of("id",today));
        for(String status:List.of("closed","expired","inactive","已关闭","已截止"," CLOSED ")) {
            long id=item("foreign","上海","Python");
            db.update("UPDATE items SET payload=payload || jsonb_build_object('status',CAST(:status AS text)) WHERE id=:id",Map.of("id",id,"status",status));
        }
        long opportunity=item("foreign","上海","Python");
        db.update("UPDATE items SET kind='opportunity',deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date-1,payload=payload || '{\"kind\":\"opportunity\"}'::jsonb WHERE id=:id",Map.of("id",opportunity));
        service.subscription(new Contracts.Subscription("合成全部信息",Map.of(),true));
        service.refresh();service.refresh();
        assertThat(service.alerts().stream().map(a->a.get("item_id")).toList()).containsExactlyInAnyOrder(today,unknown);
        assertThat(repo.detail(yesterday)).isNotEmpty(); // 存档仍可查，不关闭或删除记录。
        db.update("UPDATE items SET version=2,deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date-1 WHERE id=:id",Map.of("id",today));
        service.refresh();
        assertThat(service.alerts()).hasSize(2); // 旧提醒保留，不因到期重发。
        db.update("UPDATE items SET version=3,deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date+1 WHERE id=:id",Map.of("id",today));
        service.refresh();service.refresh();
        assertThat(service.alerts()).hasSize(3); // 有明确延期的新版本可以重新提醒。
    }
    @Test void subscriptionsExcludeDemoByDefaultAndExplicitOptInIsLocalToRule() {
        long real=item("foreign","上海","Python"),demo=item("foreign","上海","Python");
        db.update("UPDATE items SET is_demo=true WHERE id=:id",Map.of("id",demo));
        long normal=service.subscription(new Contracts.Subscription("默认真实",Map.of("kind","job"),true));
        long explicit=service.subscription(new Contracts.Subscription("明确排除演示",Map.of("kind","job","includeDemo",false),true));
        long optIn=service.subscription(new Contracts.Subscription("主动包含演示",Map.of("kind","job","includeDemo",true),true));
        service.refresh();service.refresh();
        for(long sub:List.of(normal,explicit)) {
            assertThat(service.alerts().stream().filter(a->a.get("dedup_key").toString().startsWith("subscription:"+sub+":")).map(a->a.get("item_id")).toList()).containsExactly(real);
        }
        assertThat(service.alerts().stream().filter(a->a.get("dedup_key").toString().startsWith("subscription:"+optIn+":")).map(a->a.get("item_id")).toList()).containsExactlyInAnyOrder(real,demo);
    }
    @Test void closedJobsDoNotCreateApplicationDeadlineAlertsButConfirmedInterviewRemains() {
        long closed=item("foreign","上海","Python"),open=item("foreign","上海","Python");
        db.update("UPDATE items SET deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date+2",Map.of());
        db.update("UPDATE items SET payload=payload || '{\"status\":\"closed\"}'::jsonb WHERE id=:id",Map.of("id",closed));
        service.saveApplication(closed,new Contracts.Application("interview1","合成已确认面试",null,null,java.time.OffsetDateTime.now().plusHours(2)));
        service.saveApplication(open,new Contracts.Application("saved","合成收藏",null,null,null));
        service.refresh();service.refresh();
        var keys=service.alerts().stream().map(a->a.get("dedup_key").toString()).toList();
        assertThat(keys).hasSize(2).contains("deadline:"+open+":"+repo.detail(open).get("deadline"));
        assertThat(keys.stream().filter(k->k.startsWith("interview_at:"+closed+":"))).hasSize(1);
    }
    @Test void recruitmentExpiryDoesNotSilenceTechnicalReleaseSubscriptions() {
        long release=item("foreign","上海","Python");
        db.update("UPDATE items SET kind='release',deadline=(now() AT TIME ZONE 'Asia/Shanghai')::date-1,payload=payload || '{\"kind\":\"release\",\"status\":\"closed\"}'::jsonb WHERE id=:id",Map.of("id",release));
        service.subscription(new Contracts.Subscription("合成技术订阅",Map.of("kind","release"),true));
        service.refresh();service.refresh();
        assertThat(service.alerts()).hasSize(1);
        assertThat(service.alerts().getFirst().get("item_id")).isEqualTo(release);
    }
    @Test void frameworkClientErrorsKeepTheirStatusAndNeverExposeDetails() throws Exception {
        mvc.perform(get("/api/sources")).andExpect(status().isMethodNotAllowed())
            .andExpect(header().string("Allow",org.hamcrest.Matchers.containsString("POST")))
            .andExpect(jsonPath("$.error").isNotEmpty())
            .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("Exception"))));
        mvc.perform(put("/api/alerts/read").with(csrf())).andExpect(status().isBadRequest());
        mvc.perform(post("/api/imports").with(csrf()).contentType("text/plain").content("synthetic"))
            .andExpect(status().isUnsupportedMediaType());
        mvc.perform(get("/api/no-such-resource")).andExpect(status().isNotFound());
    }
    @Test void csrfAndValidationErrors() throws Exception {mvc.perform(post("/api/matches/refresh")).andExpect(status().isForbidden());mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content("{bad json}")).andExpect(status().isBadRequest());mvc.perform(get("/api/items?page=-1")).andExpect(status().isBadRequest());mvc.perform(get("/api/items/999")).andExpect(status().isNotFound());}
    @Test void manualImportQueuedAndUnsafeLinkRejected() throws Exception {String data="{\"sourceId\":1,\"records\":[{\"kind\":\"job\",\"external_id\":\"manual1\",\"title\":\"实习\",\"body\":\"Python SQL\",\"url\":\"https://example.com/j\"}]}";mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(data)).andExpect(status().isOk()).andExpect(jsonPath("$.state").value("pending"));assertThat(db.queryForObject("SELECT count(*) FROM task_requests",Map.of(),Long.class)).isEqualTo(1);mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(data.replace("https://example.com/j","javascript:alert(1)"))).andExpect(status().isBadRequest());}
    @Test void profileAndThymeleafRendering() throws Exception {var p=new Contracts.Profile(List.of("Python"),List.of("Spark"),List.of("上海"),List.of("data_engineering"),List.of("foreign"),List.of(),"bachelor",2027,false,"数据科学",3,3,List.of("日常"),200.0,"day","CNY",null,null,null,null,null,null,Map.of("role",30,"skills",40,"city",15,"company",15));service.saveProfile(p);assertThat(service.profile().get("graduationYear")).isEqualTo(2027);mvc.perform(get("/")).andExpect(status().isOk()).andExpect(content().string(org.hamcrest.Matchers.containsString("csrf")));}

    @Test void fullStructuredImportKeepsIsoDatesAndNestedFields() throws Exception {
        String body="""
            {"sourceId":1,"records":[{"kind":"job","external_id":"full","title":"实习",
             "body":"要求 Python","country":"CN","province":"上海","city":"上海","remote":false,
             "categories":["data_engineering"],"recruitment_batch":"春招","internship_type":"日常",
             "application_start":"2026-10-01","deadline":"2026-12-31","published_at":"2026-10-13T08:00:00Z",
             "days_per_week":3,"duration_months":6,"accepts_bachelor":true,"conversion":true,
             "salary":{"minimum":200,"maximum":300,"currency":"CNY","period":"day"},
             "skills":[{"name":"Python","requirement":"required","evidence":"要求 Python"}]}]}
            """;
        mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(body)).andExpect(status().isOk());
        var payload=Json.map(db.queryForObject("SELECT payload FROM task_requests",Map.of(),Object.class));
        var record=Json.map(((List<?>)payload.get("records")).getFirst());
        assertThat(record.get("deadline")).isEqualTo("2026-12-31");
        assertThat(record.get("published_at")).isInstanceOf(String.class);
        assertThat(Json.map(record.get("salary")).get("minimum")).isEqualTo(200.0);
        assertThat(record.get("days_per_week")).isEqualTo(3);
        assertThat(record.keySet()).doesNotContain("dateRangeValid");
        assertThat(Json.map(record.get("salary")).keySet()).doesNotContain("rangeValid");
        // 供随后的 Python 契约测试使用实际 Java 队列序列化结果，而不是手工仿造 JSON。
        java.nio.file.Files.writeString(java.nio.file.Path.of("target","interop-import.json"),Json.encode(record));
        mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(body.replace("\"minimum\":200","\"minimum\":400"))).andExpect(status().isBadRequest());
    }
    @Test void subscriptionUpdateRejectsBadTypesWithoutChangingSavedRule() throws Exception {
        long id=service.subscription(new Contracts.Subscription("订阅",Map.of("kind","job","minimumScore",50),true));
        for(String rules:List.of("{\"minimumScore\":\"bad\"}","{\"minimumScore\":101}","{\"city\":[]}","{\"kind\":\"anything\"}"))
            mvc.perform(put("/api/subscriptions/"+id).with(csrf()).contentType("application/json").content("{\"name\":\"订阅\",\"enabled\":true,\"rules\":"+rules+"}")).andExpect(status().isBadRequest());
        assertThat(Json.map(service.subscriptions().getFirst().get("rules")).get("minimumScore")).isEqualTo(50);
        service.refresh();
    }
    @Test void malformedUploadedJsonReturns400AndCsvNestedFieldsWork() throws Exception {
        var malformed=new org.springframework.mock.web.MockMultipartFile("file","bad.json","application/json","[broken".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        mvc.perform(multipart("/api/imports/file").file(malformed).param("sourceId","1").with(csrf())).andExpect(status().isBadRequest());
        String csv="kind,external_id,title,categories,deadline\njob,csv-1,实习,\"[\"\"data_engineering\"\"]\",2026-12-31\n";
        var file=new org.springframework.mock.web.MockMultipartFile("file","jobs.csv","text/csv",csv.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        mvc.perform(multipart("/api/imports/file").file(file).param("sourceId","1").with(csrf())).andExpect(status().isOk());
        assertThat(db.queryForObject("SELECT count(*) FROM task_requests",Map.of(),Long.class)).isEqualTo(1);
    }

    @Test void badDatesManualCollectionAndDisabledSourcesAreRejected() throws Exception {
        mvc.perform(get("/api/skills?from=not-a-date")).andExpect(status().isBadRequest());
        mvc.perform(post("/api/sources/1/collect").with(csrf())).andExpect(status().isBadRequest());
        long id=service.saveSource(new Contracts.SourceRequest("disabled", "github",Map.of("repo","pallets/flask"),false));
        mvc.perform(post("/api/sources/"+id+"/collect").with(csrf())).andExpect(status().isBadRequest());
        mvc.perform(post("/api/sources").with(csrf()).contentType("application/json").content("{\"name\":\"rss\",\"adapter\":\"rss\",\"enabled\":true,\"config\":{\"url\":\"https://github.blog/feed/\",\"kind\":null}}")).andExpect(status().isBadRequest());
    }

    @Test void scheduledRefreshRollsBackEntireBatchOnMidwayFailure() {
        item("foreign","上海","Python");item("private","杭州","Java");
        var calls=new java.util.concurrent.atomic.AtomicInteger();
        org.mockito.Mockito.doAnswer(invocation->{
            if(calls.incrementAndGet()==2)throw new IllegalStateException("synthetic midway failure");
            return invocation.callRealMethod();
        }).when(matcher).match(org.mockito.ArgumentMatchers.anyMap(),org.mockito.ArgumentMatchers.anyMap());
        scheduler.scheduledRefresh();
        assertThat(calls.get()).isEqualTo(2);
        assertThat(db.queryForObject("SELECT count(*) FROM match_results",Map.of(),Long.class)).isZero();
    }

    @Test void structuredRegionRemoteInternshipFiltersKeepUnknownSeparate() throws Exception {
        long known=item("foreign","上海","Python");item("private","杭州","Java");
        db.update("UPDATE items SET payload=payload || '{\"province\":\"上海\",\"remote\":true,\"internship_type\":\"日常\",\"recruitment_batch\":\"春招\"}'::jsonb WHERE id=:id",Map.of("id",known));
        assertThat(repo.search(Map.of("province","上海","remote","true","internship_type","日常","recruitment_batch","春招"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.stats(Map.of("remote","true")).get("sampleSize")).isEqualTo(1L);
        assertThat(repo.search(Map.of("remote","unknown"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.search(Map.of("remote","false"),0,20).get("total")).isEqualTo(0L);
        mvc.perform(get("/api/items?remote=maybe")).andExpect(status().isBadRequest());
    }

    @Test void ashbySourceAndMultiLocationSearchStatsSubscriptionUseSamePlace() throws Exception {
        long id=item("foreign","Singapore","Python");
        String locations="[{\"country\":\"SG\",\"city\":\"Singapore\",\"primary\":true},{\"country\":\"CN\",\"city\":\"上海\",\"province\":\"上海\",\"primary\":false}]";
        db.update("UPDATE items SET country='SG',payload=jsonb_set(jsonb_set(payload,'{country}','\"SG\"'),'{locations}',CAST(:locations AS jsonb)) WHERE id=:id",Map.of("id",id,"locations",locations));
        assertThat(repo.search(Map.of("country","CN","city","上海"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.search(Map.of("country","CN","city","Singapore"),0,20).get("total")).isEqualTo(0L);
        assertThat(repo.stats(Map.of("country","CN","city","上海")).get("sampleSize")).isEqualTo(1L);
        service.subscription(new Contracts.Subscription("上海岗位",Map.of("country","CN","city","上海"),true));
        service.subscription(new Contracts.Subscription("错误地点组合",Map.of("country","CN","city","Singapore"),true));
        service.refresh();assertThat(service.alerts()).hasSize(1);
        mvc.perform(post("/api/sources").with(csrf()).contentType("application/json").content("{\"name\":\"Ashby test\",\"adapter\":\"ashby\",\"enabled\":false,\"config\":{\"board\":\"example\"}}")).andExpect(status().isOk());
        mvc.perform(post("/api/sources").with(csrf()).contentType("application/json").content("{\"name\":\"bad board\",\"adapter\":\"ashby\",\"enabled\":false,\"config\":{\"board\":\"../localhost\"}}")).andExpect(status().isBadRequest());
    }

    @Test void experienceEvidenceContractRejectsInvalidBoundsAndKeepsZeroYears() throws Exception {
        String body="""
            {"sourceId":1,"records":[{"kind":"job","external_id":"experience-contract","title":"合成工程师",
            "body":"工作经验：0-2年","is_demo":true,
            "experience_requirements":[{"minimum_years":0,"maximum_years":2,"scope":"work","requirement":"required","evidence":"工作经验：0-2年"}],
            "qualification_review_notes":["工作经验：0-2年"]}]}
            """;
        mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(body)).andExpect(status().isOk());
        var payload=Json.map(db.queryForObject("SELECT payload FROM task_requests",Map.of(),Object.class));
        var record=Json.map(((List<?>)payload.get("records")).getFirst());
        assertThat(Json.map(((List<?>)record.get("experience_requirements")).getFirst())).doesNotContainKey("rangeValid");
        java.nio.file.Files.writeString(java.nio.file.Path.of("target","interop-experience-import.json"),Json.encode(record));
        for(String invalid:List.of(body.replace("\"minimum_years\":0","\"minimum_years\":3"),body.replace("\"evidence\":\"工作经验：0-2年\"","\"evidence\":\"伪造\""),body.replace("\"qualification_review_notes\":[\"工作经验：0-2年\"]","\"qualification_review_notes\":[\"伪造\"]")))
            mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(invalid)).andExpect(status().isBadRequest());
        assertThat(db.queryForObject("SELECT count(*) FROM task_requests",Map.of(),Long.class)).isEqualTo(1L);
    }
    @Test void skillGroupAndMultipleCohortImportContractIsValidatedAndSerialized() throws Exception {
        String body="""
            {"sourceId":1,"records":[{"kind":"job","external_id":"group-contract","title":"合成实习",
            "body":"要求Python或Java任选一项；硕士在读","is_demo":true,
            "graduation_years":[2026,2027],"student_required":true,
            "skill_groups":[{"names":["Python","Java"],"minimum":1,"requirement":"required","evidence":"要求Python或Java任选一项"}]}]}
            """;
        mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(body)).andExpect(status().isOk());
        var payload=Json.map(db.queryForObject("SELECT payload FROM task_requests",Map.of(),Object.class));
        var record=Json.map(((List<?>)payload.get("records")).getFirst());
        assertThat(record.get("graduation_years")).isEqualTo(List.of(2026,2027));
        assertThat(Json.map(((List<?>)record.get("skill_groups")).getFirst())).doesNotContainKey("countValid");
        java.nio.file.Files.writeString(java.nio.file.Path.of("target","interop-group-import.json"),Json.encode(record));
        for(String invalid:List.of(body.replace("\"minimum\":1","\"minimum\":3"),body.replace("[\"Python\",\"Java\"]","[\"Python\",\"python\"]"),body.replace("\"evidence\":\"要求Python或Java任选一项\"","\"evidence\":\"伪造证据\"")))
            mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(invalid)).andExpect(status().isBadRequest());
        assertThat(db.queryForObject("SELECT count(*) FROM task_requests",Map.of(),Long.class)).isEqualTo(1L);
    }

    @Test void attentionRejectsDemoUnarchivedUnknownCohortAndStaleResults() throws Exception {
        var p=new HashMap<>(service.profile());p.putAll(Map.of("roles",List.of("data_engineering"),"skills",List.of("Python"),"education","bachelor","graduationYear",2028,"currentlyStudying",true,"employmentTypes",List.of("internship")));
        db.update("UPDATE user_profiles SET settings=CAST(:json AS jsonb),updated_at=now()",Map.of("json",Json.encode(p)));
        long id=item("foreign","成都","Python");employerFor(id,"合成来源护栏","CN");
        db.update("UPDATE items SET is_demo=true,employment_type='internship',payload=payload || CAST(:p AS jsonb) WHERE id=:id",Map.of("id",id,"p",Json.encode(Map.of("is_demo",true,"employment_type","internship","student_required",true,"body","合成数据开发实习，负责数据工程工作，要求Python。本科在读，届别未确认。","url","https://example.com/synthetic","graduation_year",2028))));
        service.refresh();
        assertThat(repo.search(Map.of("domain","mainland","view","target","includeDemo","true"),0,20).get("total")).isEqualTo(1L);
        assertThat(repo.search(Map.of("domain","mainland","view","attention","includeDemo","true"),0,20).get("total")).isEqualTo(0L);
        assertThat(repo.search(Map.of("domain","mainland","view","leads"),0,20).get("total")).isEqualTo(0L);
        db.update("UPDATE user_profiles SET updated_at=now()",Map.of());
        assertThat(repo.search(Map.of("domain","mainland","view","target","includeDemo","true"),0,20).get("total")).isEqualTo(0L);
        mvc.perform(get("/api/items").param("view","bad")).andExpect(status().isBadRequest());
    }
    // Isolated _test fixtures stand in for production rows; their text and evidence URLs remain synthetic.
    // Persist explicit current match outcomes here to test retrieval policy independently of the rule engine.
    private long overviewJob(String company,String country,String city,String hard,int score,boolean internship) {
        long id=item("unknown",city,"Python");employerFor(id,company,country);
        db.update("UPDATE items SET employment_type=:type,payload=payload || CAST(:json AS jsonb) WHERE id=:id",Map.of("id",id,"type",internship?"internship":"fulltime","json",Json.encode(Map.of("company",company,"employment_type",internship?"internship":"fulltime","student_required",true,"source_verified_at","2026-01-01T00:00:00+08:00","source_verification_note","合成隔离测试核验，非真实岗位","url","https://example.com/synthetic-job/"+id))));
        long raw=db.queryForObject("INSERT INTO raw_records(source_id,external_id,raw_hash,body) VALUES (1,:key,:key,'{\"body\":\"合成隔离测试JD\"}') RETURNING id",Map.of("key","overview-"+id),Long.class);
        db.update("UPDATE item_sources SET raw_id=:raw WHERE item_id=:id AND source_id=1",Map.of("id",id,"raw",raw));
        db.update("INSERT INTO match_results(item_id,hard_status,score,explanation,item_version,profile_updated_at,engine_revision,employer_revision) SELECT i.id,:hard,:score,CAST(:json AS jsonb),i.version,(SELECT updated_at FROM user_profiles WHERE id=1),:revision,coalesce(e.revision,0) FROM items i"+EmployerRegistry.JOIN+" WHERE i.id=:id",Map.of("id",id,"hard",hard,"score",score,"revision",MatchingEngine.REVISION,"json",Json.encode(Map.of("targetDirection",true,"bachelorStatus","confirmed"))));
        return id;
    }
    @SuppressWarnings("unchecked")
    @Test void overviewKeepsFiveHundredGlobalJobsOutAndDiversifiesBeforeLimiting() throws Exception {
        reviewedEmployer("合成本土甲","china_local","private");reviewedEmployer("合成本土乙","china_local","private");reviewedEmployer("合成本土大样本","china_local","private");
        db.update("INSERT INTO items(kind,canonical_key,title,country,city,payload,content_hash,updated_at) SELECT 'job','synthetic-anthropic-'||n,'合成 Anthropic 美国技术岗位','US','San Francisco',jsonb_build_object('company','Anthropic','country','US','city','San Francisco'),'synthetic-global',now()+interval '1 day' FROM generate_series(1,500) n",Map.of());
        long chengdu=overviewJob("合成本土甲","CN","成都","eligible",30,true);
        long chongqing=overviewJob("合成本土乙","CN","重庆","eligible",20,true);
        long shanghai=overviewJob("合成本土甲","CN","上海","eligible",99,true);
        var attention=Json.map(repo.jobOverview().get("attention"));
        var rows=(List<Map<String,Object>>)attention.get("items");
        assertThat(rows.stream().map(row->row.get("id")).toList()).containsExactly(chengdu,chongqing,shanghai);
        assertThat(attention.get("total")).isEqualTo(3L);assertThat(attention.get("sort")).isEqualTo("recommendation");
        assertThat(repo.jobCoverage("all").get("jobs")).isEqualTo(503L);
        // A recently updated global job remains first in the explicitly global archive only.
        var updated=repo.search(Map.of("domain","all","sort","updated_desc"),0,1);
        assertThat(updated.get("sort")).isEqualTo("updated_desc");
        assertThat(((List<Map<String,Object>>)updated.get("items")).getFirst().get("country")).isEqualTo("US");
        assertThat(((List<Map<String,Object>>)repo.search(Map.of("domain","mainland","sort","updated_desc"),0,3).get("items")).getFirst().get("id")).isEqualTo(shanghai);
        // More than 100 better-scored jobs from one employer must not crowd out the later employer.
        for(int n=0;n<120;n++)overviewJob("合成本土大样本","CN","上海","eligible",100,true);
        attention=Json.map(repo.jobOverview().get("attention"));rows=(List<Map<String,Object>>)attention.get("items");
        assertThat(rows).hasSize(5);assertThat(attention.get("total")).isEqualTo(123L);
        assertThat(rows.stream().map(row->row.get("id")).toList()).contains(chengdu,chongqing,shanghai);
        assertThat(rows.stream().filter(row->"合成本土大样本".equals(Json.map(row.get("payload")).get("company")))).hasSize(2);
        assertThat(rows).allMatch(row->"CN".equals(row.get("country")));
        assertThat(Json.map(repo.jobOverview().get("leads")).get("total")).isEqualTo(0L);
        assertThat(Json.map(repo.jobOverview().get("target")).get("total")).isEqualTo(0L);
        mvc.perform(get("/api/job-overview")).andExpect(status().isOk()).andExpect(jsonPath("$.classification.domestic.jobs").value(123)).andExpect(jsonPath("$.attention.maxPerEmployer").value(2));
    }
    @SuppressWarnings("unchecked")
    @Test void coverageExplainsMissingCategoryQualificationsAndFiltersWithoutPromotingUnknowns() throws Exception {
        reviewedEmployer("合成在华外企","foreign","publicly_listed");
        for(int n=0;n<10;n++)overviewJob("合成在华外企","CN","上海",n<5?"insufficient_information":"not_eligible",60,true);
        assertThat(repo.search(Map.of("domain","foreign","view","all"),0,20).get("total")).isEqualTo(10L);
        assertThat(repo.search(Map.of("domain","foreign","view","target"),0,20).get("total")).isEqualTo(10L);
        assertThat(repo.search(Map.of("domain","foreign","view","attention"),0,20).get("total")).isEqualTo(0L);
        assertThat(repo.search(Map.of("domain","foreign","view","target","city","成都"),0,20).get("total")).isEqualTo(0L);
        mvc.perform(get("/api/job-coverage").param("domain","foreign").param("city","成都").param("q","无结果关键词"))
            .andExpect(jsonPath("$.jobs").value(10)).andExpect(jsonPath("$.target").value(10)).andExpect(jsonPath("$.leads").value(5)).andExpect(jsonPath("$.attention").value(0)).andExpect(jsonPath("$.sourceCount").value(2)).andExpect(jsonPath("$.employerCount").value(1));
        mvc.perform(get("/api/job-coverage").param("domain","domestic")).andExpect(jsonPath("$.jobs").value(0)).andExpect(jsonPath("$.sourceCount").value(0));
        // The same unknown company bucket is limited to two, and never becomes a verified origin.
        for(int n=0;n<6;n++)overviewJob("","CN","北京","insufficient_information",80,false);
        long closed=overviewJob("合成已关闭","CN","成都","insufficient_information",100,false);
        db.update("UPDATE items SET payload=payload || '{\"status\":\"closed\"}'::jsonb WHERE id=:id",Map.of("id",closed));
        long pending=item("unknown","重庆","Python");
        long demo=overviewJob("合成演示","CN","成都","eligible",100,true);
        db.update("UPDATE items SET is_demo=true WHERE id=:id",Map.of("id",demo));
        var coverage=repo.jobCoverage("unclassified");
        assertThat(coverage.get("jobs")).isEqualTo(8L);assertThat(coverage.get("pending")).isEqualTo(1L);
        assertThat(repo.jobCoverage("domestic").get("jobs")).isEqualTo(0L);
        assertThat(repo.jobCoverage("foreign").get("jobs")).isEqualTo(10L);
        var overview=repo.jobOverview();
        assertThat(Json.map(overview.get("attention")).get("total")).isEqualTo(0L);
        assertThat(Json.map(overview.get("leads")).get("total")).isEqualTo(5L);
        var target=Json.map(overview.get("target"));
        assertThat(target.get("total")).isEqualTo(6L);
        var rows=(List<Map<String,Object>>)target.get("items");
        assertThat(rows).hasSize(2).noneMatch(row->Set.of(closed,pending,demo).contains(row.get("id")));
        assertThat(rows).allMatch(row->"insufficient_information".equals(row.get("hard_status")));
        mvc.perform(get("/api/job-coverage").param("domain","invalid")).andExpect(status().isBadRequest());
    }
    @Test void manualVerificationCannotBeDeclaredForLinkOnlyAndProfileWindowIsValidated() throws Exception {
        var raw=new HashMap<String,Object>(Map.of("kind","job","external_id","synthetic-verification","title","合成技术实习","is_demo",true,"url","https://example.com/synthetic","source_verified_at","2026-01-01T00:00:00+08:00","source_verification_note","合成核验记录"));
        mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(Json.encode(Map.of("sourceId",1,"records",List.of(raw))))).andExpect(status().isBadRequest());
        raw.put("body","合成JD，本科在读，日常实习。仅用于测试，不是岗位来源。");
        mvc.perform(post("/api/imports").with(csrf()).contentType("application/json").content(Json.encode(Map.of("sourceId",1,"records",List.of(raw))))).andExpect(status().isOk());
        var p=new HashMap<>(service.profile());p.put("internshipStartFrom","2027-05-01");p.put("internshipStartTo","2027-03-01");
        mvc.perform(put("/api/profile").with(csrf()).contentType("application/json").content(Json.encode(p))).andExpect(status().isBadRequest());
        p.put("internshipStartTo","2027-05-31");p.put("employmentTypes",List.of("internship"));
        mvc.perform(put("/api/profile").with(csrf()).contentType("application/json").content(Json.encode(p))).andExpect(status().isOk());
        assertThat(service.profile().get("internshipStartFrom")).isEqualTo("2027-05-01");
    }
}
