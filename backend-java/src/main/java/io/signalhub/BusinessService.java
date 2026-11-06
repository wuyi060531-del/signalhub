package io.signalhub;
import org.springframework.stereotype.Service;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import java.net.URI;
import java.util.*;
import java.time.*;
@Service
public class BusinessService {
    private final NamedParameterJdbcTemplate db;
    private final MatchingEngine matcher;
    public BusinessService(NamedParameterJdbcTemplate db,MatchingEngine matcher) {this.db=db;this.matcher=matcher;}
    public Map<String,Object> profile() {return Json.map(db.queryForObject("SELECT settings FROM user_profiles WHERE id=1",Map.of(),Object.class));}
    public Map<String,Object> health() {
        profile(); // 确认Flyway后的业务表可读，不把只存活的JVM当成就绪。
        return Map.of("status","ok","paidAI","disabled by default",
            "database",db.queryForObject("SELECT current_database()",Map.of(),String.class),
            "pid",ProcessHandle.current().pid());
    }
    @Transactional
    public Map<String,Object> saveProfile(Contracts.Profile profile) {
        profile.validateWeights();
        lockMatching();
        db.update("UPDATE user_profiles SET settings=CAST(:json AS jsonb),updated_at=now() WHERE id=1",Map.of("json",Json.encode(profile)));
        return Map.of("saved",true);
    }
    public long enqueue(String type,long source,Map<String,Object> payload) {
        var config=db.queryForMap("SELECT adapter,enabled FROM sources WHERE id=:id",Map.of("id",source));
        if(type.equals("collect") && (config.get("adapter").equals("manual") || !Boolean.TRUE.equals(config.get("enabled"))))
            throw new IllegalArgumentException("只能采集启用的自动数据源");
        return db.queryForObject("INSERT INTO task_requests(task_type,source_id,payload) VALUES (:type,:source,CAST(:json AS jsonb)) RETURNING id",Map.of("type",type,"source",source,"json",Json.encode(payload)),Long.class);
    }
    public long importRecords(Contracts.ImportRequest request) {
        String adapter=db.queryForObject("SELECT adapter FROM sources WHERE id=:id",Map.of("id",request.sourceId()),String.class);
        if(!"manual".equals(adapter)) throw new IllegalArgumentException("手动导入需选择 manual 来源");
        List<Map<String,Object>> records=new ArrayList<>();
        for(var record:request.records()) {
            if(record.url()!=null && !record.url().isBlank()) safeUrl(record.url());
            if(record.skill_groups()!=null)for(var group:record.skill_groups()) {
                if(record.body()==null || !record.body().contains(group.evidence()))
                    throw new IllegalArgumentException("技能组证据必须属于导入正文");
            }
            if(record.experience_requirements()!=null)for(var condition:record.experience_requirements()) {
                if(record.body()==null || !record.body().contains(condition.evidence()))
                    throw new IllegalArgumentException("经验条件证据必须属于导入正文");
            }
            if(record.qualification_review_notes()!=null)for(String evidence:record.qualification_review_notes()) {
                if(record.body()==null || !record.body().contains(evidence))
                    throw new IllegalArgumentException("资格复核证据必须属于导入正文");
            }
            if(record.bachelor_student_evidence()!=null && (record.body()==null || !record.body().contains(record.bachelor_student_evidence())))
                throw new IllegalArgumentException("本科在读接受条件证据必须属于导入正文");
            if(record.source_verified_at()!=null && (record.url()==null || !record.url().startsWith("https://") || record.body()==null || record.body().isBlank() || record.source_verification_note()==null || record.source_verification_note().isBlank()))
                throw new IllegalArgumentException("人工核验需HTTPS官方链接、JD正文及核验说明；仅有链接不能声明已核验");
            Map<String,Object> map=Json.map(Json.encode(record));
            map.values().removeIf(Objects::isNull);
            // 可选嵌套字段也省略 null，让 Python 的缺省值生效。
            if(map.get("salary") instanceof Map<?,?> salary)salary.values().removeIf(Objects::isNull);
            if(map.get("skills") instanceof List<?> skills)for(Object skill:skills)if(skill instanceof Map<?,?> fields)fields.values().removeIf(Objects::isNull);
            if(map.get("url")!=null && map.get("url").toString().isBlank()) map.remove("url");
            records.add(map);
        }
        return enqueue("import",request.sourceId(),Map.of("records",records));
    }
    static void safeUrl(String url) {
        try {
            URI u=URI.create(url);
            if(("http".equals(u.getScheme()) || "https".equals(u.getScheme())) && u.getHost()!=null && u.getUserInfo()==null) return;
        } catch(IllegalArgumentException ignored) { /* 不回显不可信URL/内嵌凭据。 */ }
        throw new InputValidationException("官方链接格式无效：只接受完整 http/https、无凭据的链接；不会自动抓取");
    }
    public long saveSource(Contracts.SourceRequest request) {
        var c=request.config();
        if(Json.encode(c).length()>10000)throw new IllegalArgumentException("来源配置过大");
        if("github".equals(request.adapter()) && !Objects.toString(c.get("repo"),"").matches("[\\w.-]+/[\\w.-]+")) throw new IllegalArgumentException("repo 格式 owner/name");
        if(Set.of("greenhouse","ashby","smartrecruiters","lever").contains(request.adapter()) && !Objects.toString(c.get("board"),"").matches("[A-Za-z0-9_-]{1,100}")) throw new IllegalArgumentException("board 格式错误");
        if(Set.of("smartrecruiters","lever").contains(request.adapter())) {
            if(c.containsKey("country") && (!(c.get("country") instanceof String country) || !country.matches("[A-Za-z]{2}")))throw new IllegalArgumentException("country需为两位国家代码");
            if(c.containsKey("intern_only") && !(c.get("intern_only") instanceof Boolean))throw new IllegalArgumentException("intern_only需为布尔值");
            if(c.containsKey("q") && (!(c.get("q") instanceof String keyword) || keyword.length()>100))throw new IllegalArgumentException("q需为100字符以内文本");
            if(c.containsKey("max_items") && (!(c.get("max_items") instanceof Integer count) || count<1 || count>200))throw new IllegalArgumentException("max_items范围1–200");
            if("lever".equals(request.adapter()) && c.containsKey("commitment") && (!(c.get("commitment") instanceof String value) || value.isBlank() || value.length()>100))throw new IllegalArgumentException("commitment需为1–100字符文本");
        }
        if("rss".equals(request.adapter())) {
            safeUrl(Objects.toString(c.get("url"),""));
            if(!Objects.toString(c.get("url")).startsWith("https://")) throw new IllegalArgumentException("RSS 仅允许 HTTPS，另需 Python 主机许可清单");
            if(c.containsKey("kind") && (!(c.get("kind") instanceof String kind) || !Set.of("job","opportunity","release").contains(kind)))throw new IllegalArgumentException("RSS 信息类型错误");
        }
        return db.queryForObject("INSERT INTO sources(name,adapter,config,enabled,status) VALUES (:name,:adapter,CAST(:config AS jsonb),:enabled,:status) RETURNING id",Map.of("name",request.name(),"adapter",request.adapter(),"config",Json.encode(c),"enabled",request.enabled(),"status",request.adapter().equals("manual")?"manual_only":"unverified"),Long.class);
    }
    public void enabled(long id,boolean enabled) {if(db.update("UPDATE sources SET enabled=:enabled WHERE id=:id",Map.of("id",id,"enabled",enabled))==0) throw new NoSuchElementException();}
    @Transactional
    public long subscription(Contracts.Subscription request) {
        validateSubscription(request);
        lockMatching();
        return db.queryForObject("INSERT INTO subscriptions(name,rules,enabled) VALUES (:name,CAST(:rules AS jsonb),:enabled) RETURNING id",Map.of("name",request.name(),"rules",Json.encode(request.rules()),"enabled",request.enabled()),Long.class);
    }
    private void validateSubscription(Contracts.Subscription request) {
        Set<String> keys=Set.of("kind","country","city","province","company_type","category","q","minimumScore","employment_type","internship_type","recruitment_batch","remote","includeDemo");
        if(!keys.containsAll(request.rules().keySet())) throw new IllegalArgumentException("订阅条件包含不支持字段");
        for(var e:request.rules().entrySet()) {
            if(e.getKey().equals("minimumScore")) {if(!(e.getValue() instanceof Number n)||!Double.isFinite(n.doubleValue())||n.doubleValue()<0||n.doubleValue()>100)throw new IllegalArgumentException("minimumScore 范围0-100");}
            else if(Set.of("remote","includeDemo").contains(e.getKey())) {if(!(e.getValue() instanceof Boolean))throw new IllegalArgumentException("开关条件需为布尔值");}
            else if(!(e.getValue() instanceof String s)||s.length()>200)throw new IllegalArgumentException("订阅条件需为200字符以内文本");
        }
        Object kind=request.rules().get("kind");
        if(kind!=null && !Set.of("job","opportunity","release").contains(kind))throw new IllegalArgumentException("未知信息类型");
    }
    @Transactional
    public void updateSubscription(long id,Contracts.Subscription request) {
        validateSubscription(request);
        lockMatching();
        if(db.update("UPDATE subscriptions SET name=:name,rules=CAST(:rules AS jsonb),enabled=:enabled WHERE id=:id",Map.of("id",id,"name",request.name(),"rules",Json.encode(request.rules()),"enabled",request.enabled()))==0)throw new NoSuchElementException();
    }
    public List<Map<String,Object>> subscriptions() {var rows=db.queryForList("SELECT * FROM subscriptions ORDER BY id DESC",Map.of());rows.forEach(r->r.put("rules",Json.map(r.get("rules"))));return rows;}
    @Transactional
    public void saveApplication(long id,Contracts.Application app) {
        if(!"job".equals(db.queryForObject("SELECT kind FROM items WHERE id=:id",Map.of("id",id),String.class)))throw new IllegalArgumentException("只能记录岗位投递");
        var p=new HashMap<String,Object>();p.put("id",id);p.put("status",app.status());p.put("notes",Objects.toString(app.notes(),""));p.put("applied",app.appliedAt());p.put("assessment",app.assessmentAt());p.put("interview",app.interviewAt());p.put("nextAction",app.nextAction());
        db.update("INSERT INTO job_applications(item_id,status,notes,applied_at,assessment_at,interview_at,next_action) VALUES (:id,:status,:notes,:applied,:assessment,:interview,:nextAction) ON CONFLICT(item_id) DO UPDATE SET status=excluded.status,notes=excluded.notes,applied_at=excluded.applied_at,assessment_at=excluded.assessment_at,interview_at=excluded.interview_at,next_action=excluded.next_action,updated_at=now()",p);
        db.update("INSERT INTO application_history(item_id,snapshot) VALUES (:id,CAST(:json AS jsonb))",Map.of("id",id,"json",Json.encode(app)));
    }
    public List<Map<String,Object>> applications() {return db.queryForList("SELECT a.*,i.title,i.deadline,i.is_demo,i.payload->>'company' AS company,i.city FROM job_applications a JOIN items i ON i.id=a.item_id ORDER BY a.updated_at DESC,a.item_id DESC",Map.of());}
    public List<Map<String,Object>> history(long id) {return db.queryForList("SELECT * FROM application_history WHERE item_id=:id ORDER BY id DESC",Map.of("id",id)).stream().map(r->{r.put("snapshot",Json.map(r.get("snapshot")));return r;}).toList();}
    private record MatchSummary(String hardStatus,double score) {}
    private boolean satisfies(Map<String,Object> item,Map<String,Object> rules,MatchSummary match) {
        if(Boolean.TRUE.equals(item.get("is_demo")) && !Boolean.TRUE.equals(rules.get("includeDemo")))return false;
        var geography=new LinkedHashMap<String,Object>();
        for(String key:List.of("country","city","province"))if(rules.get(key)!=null && !rules.get(key).toString().isBlank())geography.put(key,rules.get(key));
        if(!geography.isEmpty()) {
            List<Map<String,Object>> places=new ArrayList<>();places.add(item);
            if(item.get("locations") instanceof List<?> locations)locations.forEach(x->places.add(Json.map(x)));
            if(places.stream().noneMatch(place->geography.entrySet().stream().allMatch(e->Objects.equals(place.get(e.getKey()),e.getValue()))))return false;
        }
        for(var entry:rules.entrySet()) {
            String key=entry.getKey();Object value=entry.getValue();
            if(value==null || value.toString().isBlank())continue;
            if(geography.containsKey(key))continue;
            if(key.equals("includeDemo")) {if(Boolean.FALSE.equals(value) && Boolean.TRUE.equals(item.get("is_demo")))return false;}
            else if(key.equals("minimumScore")) {if(match==null || match.hardStatus().equals("not_eligible") || match.score()<((Number)value).doubleValue())return false;}
            else if(key.equals("q")) {if(!Objects.toString(item.get("title"),"").concat(" ").concat(Objects.toString(item.get("body"),"")).concat(" ").concat(Objects.toString(item.get("company"),"")).toLowerCase(Locale.ROOT).contains(value.toString().toLowerCase(Locale.ROOT)))return false;}
            else if(key.equals("category")) {if(!Json.strings(item.get("categories")).contains(value.toString()))return false;}
            else if(!Objects.equals(item.get(key),value))return false;
        }
        return true;
    }
    @Transactional
    public Map<String,Object> refresh() {
        // 防止手动刷新与定时任务并发产生相互覆盖的匹配结果。
        lockMatching();
        var profileRow=db.queryForMap("SELECT settings,updated_at FROM user_profiles WHERE id=1",Map.of());
        var profile=Json.map(profileRow.get("settings"));var subs=subscriptions().stream().filter(s->Boolean.TRUE.equals(s.get("enabled"))).toList();
        // 匹配与订阅使用同一版本，ETL更新在本次事务提交后继续。
        var items=db.queryForList("SELECT i.id,i.version,i.payload,i.is_demo,"+ItemAvailability.OPEN_SQL+" AS notification_open,to_jsonb(e) AS employer,coalesce(e.revision,0) AS employer_revision,m.hard_status,m.score,(v.raw_id=p.raw_id) AS parser_only FROM items i"+EmployerRegistry.JOIN+ItemRepository.MATCH_JOIN+" LEFT JOIN item_versions v ON v.item_id=i.id AND v.version=i.version LEFT JOIN item_versions p ON p.item_id=i.id AND p.version=i.version-1 ORDER BY i.id FOR SHARE OF i",Map.of("matchRevision",MatchingEngine.REVISION));
        int count=0,computed=0,writes=0;
        Set<String> notifiedRaw=new HashSet<>();
        db.queryForList("SELECT split_part(a.dedup_key,':',2) AS subscription,a.item_id FROM alerts a JOIN item_versions v ON v.item_id=a.item_id AND v.version=CASE WHEN a.dedup_key ~ '^subscription:[0-9]+:[0-9]+:[0-9]+$' THEN split_part(a.dedup_key,':',4)::int ELSE NULL END JOIN item_versions current ON current.item_id=v.item_id JOIN items i ON i.id=current.item_id AND i.version=current.version WHERE v.raw_id=current.raw_id",Map.of()).forEach(a->notifiedRaw.add(a.get("subscription")+":"+a.get("item_id")));
        for(var row:items) {
            long id=((Number)row.get("id")).longValue();var item=EmployerRegistry.apply(Json.map(row.get("payload")),row.get("employer"));MatchSummary match=null;
            item.put("is_demo",row.get("is_demo"));
            if("job".equals(item.get("kind"))) {
                count++;
                if(row.get("hard_status")!=null) {
                    // 与列表/详情共用四项修订判断；订阅仍检查全部存量，新增规则不会漏通知。
                    match=new MatchSummary(row.get("hard_status").toString(),((Number)row.get("score")).doubleValue());
                } else {
                    var result=matcher.match(item,profile);
                    match=new MatchSummary(result.hardStatus(),result.score());
                    computed++;
                    writes+=db.update("""
                        INSERT INTO match_results(item_id,hard_status,score,explanation,item_version,
                            profile_updated_at,engine_revision,employer_revision)
                        VALUES (:id,:hard,:score,CAST(:json AS jsonb),:version,:profileRevision,:engineRevision,:employerRevision)
                        ON CONFLICT(item_id) DO UPDATE SET hard_status=excluded.hard_status,score=excluded.score,
                            explanation=excluded.explanation,item_version=excluded.item_version,
                            profile_updated_at=excluded.profile_updated_at,engine_revision=excluded.engine_revision,
                            employer_revision=excluded.employer_revision,calculated_at=now()
                        """,Map.of("id",id,"hard",result.hardStatus(),"score",result.score(),"json",Json.encode(result),
                            "version",row.get("version"),"profileRevision",profileRow.get("updated_at"),
                            "engineRevision",MatchingEngine.REVISION,"employerRevision",row.get("employer_revision")));
                }
            }
            // 新订阅可回看当前存量一次；已有同一原文的订阅提醒不因重解析再通知。
            boolean reparse=Boolean.TRUE.equals(row.get("parser_only"));
            for(var sub:subs) if(Boolean.TRUE.equals(row.get("notification_open")) && satisfies(item,Json.map(sub.get("rules")),match) && (!reparse || !notifiedRaw.contains(sub.get("id")+":"+id)))
                alert(id,"subscription:"+sub.get("id")+":"+id+":"+row.get("version"),"订阅「"+sub.get("name")+"」匹配："+item.get("title"));
        }
        reminders();
        return Map.of("matchedJobs",count,"computedJobs",computed,"matchWrites",writes);
    }
    private void lockMatching() {db.queryForObject("SELECT pg_advisory_xact_lock(754302)",Map.of(),Object.class);}
    public Map<String,Object> task(long id) {
        var rows=db.queryForList("SELECT id,task_type,source_id,state,attempts,error,result,created_at,started_at,finished_at FROM task_requests WHERE id=:id",Map.of("id",id));
        if(rows.isEmpty())throw new NoSuchElementException("任务不存在");
        var row=rows.getFirst();if(row.get("result")!=null)row.put("result",Json.map(row.get("result")));
        return row;
    }
    private void alert(long id,String key,String message) {db.update("INSERT INTO alerts(item_id,dedup_key,message) VALUES (:id,:key,:message) ON CONFLICT(dedup_key) DO NOTHING",Map.of("id",id,"key",key,"message",message));}
    private void reminders() {
        db.update("INSERT INTO alerts(item_id,dedup_key,message) SELECT i.id,'deadline:'||i.id||':'||i.deadline,'申请截止提醒：'||i.title||'（'||i.deadline||'）' FROM items i JOIN job_applications a ON a.item_id=i.id WHERE i.deadline BETWEEN (now() AT TIME ZONE 'Asia/Shanghai')::date AND (now() AT TIME ZONE 'Asia/Shanghai')::date+7 AND "+ItemAvailability.OPEN_SQL+" AND a.status NOT IN ('rejected','closed','offer') ON CONFLICT DO NOTHING",Map.of());
        for(String field:List.of("assessment_at","interview_at")) db.update("INSERT INTO alerts(item_id,dedup_key,message) SELECT a.item_id,'"+field+":'||a.item_id||':'||a."+field+",'已确认日程提醒：'||i.title||' '||a."+field+" FROM job_applications a JOIN items i ON i.id=a.item_id WHERE a."+field+" BETWEEN now() AND now()+interval '24 hours' AND a.status NOT IN ('closed','rejected') ON CONFLICT DO NOTHING",Map.of());
    }
    // 从历史原文证据分类，保留旧提醒；不把维护变更称为官网更新。
    private static final String ALERT_BASE="""
        WITH classified AS (
          SELECT a.*,i.is_demo,
            CASE WHEN split_part(a.dedup_key,':',1)='change'
              AND EXISTS(SELECT 1 FROM item_versions v JOIN item_versions p ON p.item_id=v.item_id AND p.version=v.version-1
                WHERE v.item_id=a.item_id AND v.version=CASE WHEN a.dedup_key ~ '^change:[0-9]+:[0-9]+$' THEN split_part(a.dedup_key,':',3)::int
                  WHEN a.dedup_key ~ '^subscription:[0-9]+:[0-9]+:[0-9]+$' THEN split_part(a.dedup_key,':',4)::int ELSE NULL END
                AND v.raw_id=p.raw_id) THEN 'maintenance'
              WHEN a.dedup_key LIKE 'change:%' THEN 'change'
              WHEN a.dedup_key LIKE 'subscription:%' THEN 'subscription'
              WHEN split_part(a.dedup_key,':',1) IN ('deadline','assessment_at','interview_at') THEN 'schedule'
              ELSE 'other' END AS alert_type
          FROM alerts a LEFT JOIN items i ON i.id=a.item_id
        )
        """;
    private Map<String,Object> alertParams(String state,String type,boolean includeDemo) {
        if(!Set.of("all","unread","read").contains(state) || !Set.of("all","actionable","change","maintenance","subscription","schedule","other").contains(type))throw new InputValidationException("提醒筛选参数无效");
        return new HashMap<>(Map.of("state",state,"type",type,"demo",includeDemo));
    }
    private static final String ALERT_WHERE=" WHERE (:demo OR NOT coalesce(is_demo,false)) AND (:state='all' OR (:state='unread' AND read_at IS NULL) OR (:state='read' AND read_at IS NOT NULL)) AND (:type='all' OR (:type='actionable' AND alert_type<>'maintenance') OR alert_type=:type) ";
    public List<Map<String,Object>> alerts() {return alerts(0,200);}
    public List<Map<String,Object>> alerts(int page,int size) {return alerts(page,size,"all","all",true);}
    public List<Map<String,Object>> alerts(int page,int size,String state,String type,boolean includeDemo) {
        if(page<0 || page>100000 || size<1 || size>200) throw new InputValidationException("提醒分页参数无效：page需为0–100000，size需为1–200");
        var params=alertParams(state,type,includeDemo);params.put("size",size);params.put("offset",(long)page*size);
        return db.queryForList(ALERT_BASE+"SELECT * FROM classified"+ALERT_WHERE+"ORDER BY id DESC LIMIT :size OFFSET :offset",params);
    }
    public Map<String,Object> alertSummary() {return alertSummary("all","all",true);}
    public Map<String,Object> alertSummary(String state,String type,boolean includeDemo) {
        return db.queryForMap(ALERT_BASE+"SELECT count(*) AS total,count(*) FILTER(WHERE read_at IS NULL) AS unread,coalesce(max(id),0) AS through_id FROM classified"+ALERT_WHERE,alertParams(state,type,includeDemo));
    }
    public void readAlert(long id) {
        if(db.update("UPDATE alerts SET read_at=coalesce(read_at,now()) WHERE id=:id",Map.of("id",id))==0)throw new NoSuchElementException("提醒不存在");
    }
    public Map<String,Object> readAlerts(String state,String type,boolean includeDemo,long throughId) {
        if(throughId<0)throw new InputValidationException("提醒截止标识无效");
        var params=alertParams(state,type,includeDemo);params.put("through",throughId);
        int updated=db.update(ALERT_BASE+"UPDATE alerts SET read_at=now() WHERE read_at IS NULL AND id IN (SELECT id FROM classified"+ALERT_WHERE+"AND id<=:through)",params);
        return Map.of("updated",updated);
    }
    public Map<String,Object> monitoring() {
        var sources=db.queryForList("SELECT * FROM sources ORDER BY id",Map.of());sources.forEach(s->s.put("config",Json.map(s.get("config"))));
        var runs=db.queryForList("SELECT r.*,s.name,extract(epoch FROM(coalesce(r.ended_at,now())-r.started_at)) AS duration_seconds FROM collection_runs r JOIN sources s ON s.id=r.source_id ORDER BY r.id DESC LIMIT 50",Map.of());runs.forEach(r->r.put("errors",r.get("errors").toString()));
        var tasks=db.queryForList("SELECT id,task_type,source_id,state,attempts,error,result,created_at FROM task_requests ORDER BY id DESC LIMIT 50",Map.of());tasks.forEach(t->{if(t.get("result")!=null)t.put("result",Json.map(t.get("result")));});
        return Map.of("sources",sources,"runs",runs,"tasks",tasks,"duplicateCandidates",db.queryForList("SELECT d.*,a.title AS title_a,b.title AS title_b FROM duplicate_candidates d JOIN items a ON a.id=d.item_a JOIN items b ON b.id=d.item_b LIMIT 100",Map.of()));
    }
    public Map<String,Object> aiStatus() {
        var usage=db.queryForList("SELECT month,provider,state,count(*) AS calls,sum(coalesce(actual_usd,reserved_usd)) AS cost_usd FROM ai_usage GROUP BY month,provider,state ORDER BY month DESC",Map.of());
        return Map.of("provider",System.getenv().getOrDefault("AI_PROVIDER","disabled"),"paidAuthorized",System.getenv().getOrDefault("AI_PAID_AUTHORIZED","false"),"budget",System.getenv().getOrDefault("AI_MONTHLY_BUDGET_USD","0"),"usage",usage);
    }
}
