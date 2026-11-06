package io.signalhub;
import org.springframework.stereotype.Repository;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import java.time.LocalDate;
import java.util.*;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.annotation.Isolation;
@Repository
public class ItemRepository {
    private final NamedParameterJdbcTemplate db;
    public ItemRepository(NamedParameterJdbcTemplate db) { this.db=db; }
    private static final String NON_MAINLAND="香港|澳门|澳門|台湾|臺灣|hong[ -]?kong|maca[ou]|taiwan|taipei|台北|臺北|kaohsiung|高雄|taichung|台中|臺中";
    private static final java.util.regex.Pattern NON_MAINLAND_PATTERN=java.util.regex.Pattern.compile(NON_MAINLAND,java.util.regex.Pattern.CASE_INSENSITIVE);
    private static final String MAINLAND_SQL="i.country='CN' AND concat_ws(' ',i.city,i.payload->>'province') !~* '"+NON_MAINLAND+"'";
    static final String MATCH_JOIN=" LEFT JOIN match_results m ON m.item_id=i.id AND m.item_version=i.version AND m.profile_updated_at=(SELECT updated_at FROM user_profiles WHERE id=1) AND m.engine_revision=:matchRevision AND m.employer_revision=coalesce(e.revision,0) ";
    private static final String MATCH_STATE="CASE WHEN i.kind<>'job' THEN 'not_applicable' WHEN m.item_id IS NULL THEN 'pending' ELSE 'current' END AS matching_status";
    private static final String EMPLOYER_KEY="nullif(lower(btrim(i.payload->>'company')),'')";
    private static final String RECOMMENDATION_ORDER="CASE WHEN (i.country='CN' AND lower(btrim(i.city)) IN ('成都','成都市','chengdu','重庆','重庆市','chongqing')) OR EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(i.payload->'locations')='array' THEN i.payload->'locations' ELSE '[]'::jsonb END) place WHERE place->>'country'='CN' AND lower(btrim(place->>'city')) IN ('成都','成都市','chengdu','重庆','重庆市','chongqing')) THEN 0 ELSE 1 END,m.score DESC NULLS LAST,i.updated_at DESC,i.id DESC";
    private static final String READING_JOIN=" LEFT JOIN LATERAL (SELECT content_hash,payload FROM reading_translations WHERE item_id=i.id AND language='zh-CN' ORDER BY (content_hash=i.content_hash) DESC,created_at DESC LIMIT 1) rt ON true LEFT JOIN LATERAL (SELECT content_hash,result FROM reading_translation_jobs WHERE item_id=i.id AND state='done' AND provider_revision=(SELECT provider_revision FROM translation_runtime WHERE id=1) ORDER BY (content_hash=i.content_hash) DESC,depth DESC,id DESC LIMIT 1) mt ON true ";
    private static final String READING_FIELDS=",rt.payload AS reading_payload,rt.content_hash AS reading_hash,mt.result AS machine_payload,mt.content_hash AS machine_hash,EXISTS(SELECT 1 FROM reading_translation_jobs j WHERE j.item_id=i.id AND j.content_hash=i.content_hash AND j.provider_revision=(SELECT provider_revision FROM translation_runtime WHERE id=1) AND j.state IN ('pending','running')) AS translation_processing,(SELECT error FROM reading_translation_jobs j WHERE j.item_id=i.id AND j.content_hash=i.content_hash AND j.provider_revision=(SELECT provider_revision FROM translation_runtime WHERE id=1) AND j.state='failed' ORDER BY j.id DESC LIMIT 1) AS translation_error,";
    public record Filter(String where,Map<String,Object> params) {}
    public Filter filter(Map<String,String> query) {
        StringBuilder sql=new StringBuilder(" WHERE true "); Map<String,Object> p=new HashMap<>(); p.put("matchRevision",MatchingEngine.REVISION);
        for(String key:List.of("kind","company_type","education","employment_type")) {
            String value=query.get(key);
            if(value!=null && !value.isBlank()) {
                if(key.equals("company_type"))
                    sql.append(" AND (CASE WHEN i.kind='job' THEN CASE WHEN e.status='verified' THEN CASE WHEN e.origin='foreign' THEN 'foreign' ELSE e.ownership END ELSE 'unknown' END ELSE i.company_type END)=:company_type");
                else sql.append(" AND i.").append(key).append("=:").append(key);
                p.put(key,value);
            }
        }
        for(String key:List.of("internship_type","recruitment_batch","status")) {
            String value=query.get(key);
            if(value!=null && !value.isBlank()) {sql.append(" AND i.payload->>'").append(key).append("'=:").append(key);p.put(key,value);}
        }
        String remote=query.get("remote");
        if(remote!=null && !remote.isBlank()) {
            if(!Set.of("true","false","unknown").contains(remote))throw new IllegalArgumentException("remote只接受true/false/unknown");
            if(remote.equals("unknown"))sql.append(" AND i.payload->>'remote' IS NULL");
            else {sql.append(" AND i.payload->>'remote'=:remote");p.put("remote",remote);}
        }
        String domain=query.get("domain");
        var locationQuery=new LinkedHashMap<String,String>();
        for(String key:List.of("country","city","province"))if(query.get(key)!=null && !query.get(key).isBlank())locationQuery.put(key,query.get(key));
        if(Set.of("domestic","foreign","unclassified","mainland").contains(Objects.toString(domain,""))) {
            sql.append(" AND i.kind='job' AND "+MAINLAND_SQL);
            if(locationQuery.containsKey("country") && !locationQuery.get("country").equals("CN"))sql.append(" AND false");
            locationQuery.put("country","CN");
        }
        if(!locationQuery.isEmpty()) {
            var primary=new ArrayList<String>();
            for(var e:locationQuery.entrySet()) {
                String key=e.getKey();p.put(key,e.getValue());
                primary.add((key.equals("province")?"i.payload->>'province'":"i."+key)+"=:"+key);
            }
            // 国家、城市、省份必须来自同一个地点，不能跨两个地点拼出虚假匹配。
            p.put("locations",Json.encode(Map.of("locations",List.of(locationQuery))));
            sql.append(" AND ((").append(String.join(" AND ",primary)).append(") OR i.payload @> CAST(:locations AS jsonb))");
        }
        if("domestic".equals(domain)) sql.append(" AND e.status='verified' AND e.origin='china_local'");
        if("foreign".equals(domain)) sql.append(" AND e.status='verified' AND e.origin='foreign'");
        if("unclassified".equals(domain)) sql.append(" AND (e.status IS NULL OR e.status<>'verified')");
        if("all".equals(domain)) sql.append(" AND i.kind='job'");
        String view=query.getOrDefault("view","all");
        if(!Set.of("all","target","leads","attention").contains(view))throw new IllegalArgumentException("岗位视图无效");
        if(!view.equals("all")) {
            // Persisted result is joined only when every input revision is current. Filter before pagination.
            sql.append(" AND i.kind='job' AND m.explanation->>'targetDirection'='true'");
            if(!view.equals("target")) {
                sql.append(" AND "+MAINLAND_SQL+" AND i.employment_type='internship' AND NOT i.is_demo");
                sql.append(" AND i.payload->>'url' ~ '^https://[^/]+/' AND EXISTS(SELECT 1 FROM item_sources x JOIN raw_records r ON r.id=x.raw_id WHERE x.item_id=i.id)");
                sql.append(" AND "+ItemAvailability.OPEN_SQL);
                // Manual statements remain human assertions. A pasted link alone is insufficient.
                sql.append(" AND (i.payload->>'source_verified_at' IS NOT NULL OR EXISTS(SELECT 1 FROM item_sources x JOIN sources src ON src.id=x.source_id WHERE x.item_id=i.id AND src.adapter IN ('greenhouse','ashby','smartrecruiters','lever'))) ");
                if(view.equals("attention"))sql.append(" AND m.hard_status='eligible' AND m.explanation->>'bachelorStatus'='confirmed'");
                else sql.append(" AND m.hard_status<>'not_eligible'");
            }
        }
        if("true".equals(query.get("hideIneligible"))) sql.append(" AND (m.hard_status IS NULL OR m.hard_status<>'not_eligible')");
        String hard=query.get("hard_status");
        if(hard!=null && !hard.isBlank()) {
            if(!Set.of("eligible","insufficient_information","not_eligible","pending").contains(hard))throw new IllegalArgumentException("资格状态无效");
            if(hard.equals("pending"))sql.append(" AND m.item_id IS NULL");
            else {sql.append(" AND m.hard_status=:hardStatus");p.put("hardStatus",hard);}
        }
        if(query.get("q")!=null && !query.get("q").isBlank()) { sql.append(" AND (lower(i.title) LIKE :q OR lower(i.payload->>'body') LIKE :q OR lower(i.payload->>'company') LIKE :q)"); p.put("q","%"+query.get("q").toLowerCase(Locale.ROOT).replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"); }
        if(query.get("category")!=null && !query.get("category").isBlank()) { sql.append(" AND jsonb_exists(i.payload->'categories',:category)"); p.put("category",query.get("category")); }
        if(!"true".equals(query.get("includeDemo"))) sql.append(" AND NOT i.is_demo");
        if(query.get("source")!=null && !query.get("source").isBlank()) { sql.append(" AND EXISTS(SELECT 1 FROM item_sources s WHERE s.item_id=i.id AND s.source_id=:source)"); p.put("source",Long.parseLong(query.get("source"))); }
        if(query.get("from")!=null && !query.get("from").isBlank()) { sql.append(" AND i.first_seen>=:fromDate"); p.put("fromDate",LocalDate.parse(query.get("from")).atStartOfDay().atOffset(java.time.ZoneOffset.ofHours(8))); }
        if(query.get("to")!=null && !query.get("to").isBlank()) { sql.append(" AND i.first_seen<:toDate"); p.put("toDate",LocalDate.parse(query.get("to")).plusDays(1).atStartOfDay().atOffset(java.time.ZoneOffset.ofHours(8))); }
        return new Filter(sql.toString(),p);
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> search(Map<String,String> query,int page,int size) {
        if(page<0 || page>100000 || size<1 || size>100) throw new IllegalArgumentException("分页超出范围");
        Filter f=filter(query); var p=new HashMap<>(f.params()); p.put("limit",size); p.put("offset",(long)page*size);
        long total=db.queryForObject("SELECT count(*) FROM items i"+EmployerRegistry.JOIN+MATCH_JOIN+f.where(),p,Long.class);
        p.put("matchRevision",MatchingEngine.REVISION);
        var rows=db.queryForList("SELECT i.*,to_jsonb(e) AS employer,m.hard_status,m.score,m.explanation"+READING_FIELDS+MATCH_STATE+",a.status AS application_status FROM items i"+EmployerRegistry.JOIN+READING_JOIN+MATCH_JOIN+" LEFT JOIN job_applications a ON a.item_id=i.id"+f.where()+" ORDER BY "+sort(query)+" LIMIT :limit OFFSET :offset",p);
        rows.forEach(this::decode);
        attachProvenance(rows);
        return Map.of("items",rows,"total",total,"page",page,"size",size,"sort",sortKey(query));
    }
    private void attachProvenance(List<Map<String,Object>> rows) {
        if(rows.isEmpty())return;
        var ids=rows.stream().map(row->row.get("id")).toList();
        var sources=db.queryForList("SELECT x.item_id,s.name,s.adapter,x.url,r.fetched_at AS archived_at FROM item_sources x JOIN sources s ON s.id=x.source_id LEFT JOIN raw_records r ON r.id=x.raw_id WHERE x.item_id IN (:ids) ORDER BY x.item_id,s.id",Map.of("ids",ids));
        for(var row:rows)row.put("provenance",sources.stream().filter(x->Objects.equals(x.get("item_id"),row.get("id"))).toList());
    }
    private static String sortKey(Map<String,String> query) {
        return query.getOrDefault("sort",Set.of("release","opportunity").contains(query.getOrDefault("kind",""))?"updated_desc":"match_desc");
    }
    private static String sort(Map<String,String> query) {
        return switch(sortKey(query)) {
            case "match_desc" -> "m.score DESC NULLS LAST,i.updated_at DESC,i.id DESC";
            case "match_asc" -> "m.score ASC NULLS LAST,i.updated_at DESC,i.id DESC";
            case "published_desc" -> "i.published_at DESC NULLS LAST,i.id DESC";
            case "first_seen_desc" -> "i.first_seen DESC,i.id DESC";
            case "deadline_asc" -> "CASE WHEN i.deadline IS NULL THEN 2 WHEN i.deadline<(now() AT TIME ZONE 'Asia/Shanghai')::date THEN 1 ELSE 0 END,i.deadline ASC,i.id DESC";
            case "updated_desc" -> "i.updated_at DESC,i.id DESC";
            case "recommendation" -> RECOMMENDATION_ORDER;
            default -> throw new IllegalArgumentException("不支持的排序方式");
        };
    }
    private void decode(Map<String,Object> row) {
        row.put("employer",Json.map(row.get("employer")));
        row.put("payload",Json.map(row.get("payload")));
        row.put("bachelor_status",MatchingEngine.bachelorStatus(Json.map(row.get("payload"))));
        var payload=Json.map(row.get("payload"));
        if("job".equals(row.get("kind")))row.put("recruitment",RecruitmentEvidence.evaluate(payload,row.get("deadline"),
            java.time.Clock.systemUTC(),Boolean.TRUE.equals(row.get("is_demo"))));
        boolean secondary=payload.get("locations") instanceof List<?> places && places.stream().anyMatch(place->"CN".equals(Json.map(place).get("country")));
        boolean nonMainland=NON_MAINLAND_PATTERN.matcher(Objects.toString(row.get("city"),"")+" "+Objects.toString(payload.get("province"),"")).find();
        row.put("mainland_work_status",nonMainland?"non_mainland":"CN".equals(row.get("country"))?"confirmed_primary":secondary?"secondary_review":row.get("country")==null?"unknown":"overseas_primary");
        Object translated=row.remove("reading_payload"), hash=row.remove("reading_hash");
        var reading=new LinkedHashMap<String,Object>();
        Object machine=row.remove("machine_payload"),machineHash=row.remove("machine_hash");
        boolean reviewedCurrent=hash!=null && Objects.equals(hash,row.get("content_hash"));
        boolean machineCurrent=machineHash!=null && Objects.equals(machineHash,row.get("content_hash"));
        reading.put("status",reviewedCurrent||machineCurrent?"current":hash!=null||machineHash!=null?"stale":"missing");
        if(reviewedCurrent) {
            var reviewed=Json.map(translated);
            if(machineCurrent) {
                var merged=new LinkedHashMap<>(Json.map(machine));var fields=new ArrayList<String>();
                for(String key:List.of("title_zh","summary_zh","body_zh"))if(reviewed.get(key) instanceof String text && !text.isBlank()) {merged.put(key,text);fields.add(key);}
                merged.put("reviewed_fields",fields);merged.put("attribution",reviewed.get("attribution")+"；其余字段："+Json.map(machine).get("attribution"));
                reading.put("translation",merged);
            } else reading.put("translation",reviewed);
        } else if(machineCurrent)reading.put("translation",Json.map(machine));
        reading.put("processing",row.remove("translation_processing"));reading.put("error",row.remove("translation_error"));
        row.put("reading",reading);
        if(row.get("explanation")!=null) row.put("explanation",Json.map(row.get("explanation")));
        if(row.get("deadline") instanceof java.sql.Date d) row.put("deadline_status",d.toLocalDate().isBefore(LocalDate.now(java.time.ZoneId.of("Asia/Shanghai")))?"expired":"open");
        else row.put("deadline_status","unknown");
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> detail(long id) {
        var rows=db.queryForList("SELECT i.*,to_jsonb(e) AS employer,m.hard_status,m.score,m.explanation"+READING_FIELDS+MATCH_STATE+" FROM items i"+EmployerRegistry.JOIN+READING_JOIN+MATCH_JOIN+" WHERE i.id=:id",Map.of("id",id,"matchRevision",MatchingEngine.REVISION));
        if(rows.isEmpty()) throw new NoSuchElementException("信息不存在");
        Map<String,Object> row=rows.getFirst(); decode(row);attachProvenance(rows);
        var rawRows=db.queryForList("SELECT s.adapter,r.body FROM item_versions v JOIN raw_records r ON r.id=v.raw_id JOIN sources s ON s.id=r.source_id WHERE v.item_id=:id AND v.version=:version",Map.of("id",id,"version",row.get("version")));
        row.put("original",OriginalContent.from(Json.map(row.get("payload")),rawRows.isEmpty()?"":rawRows.getFirst().get("adapter").toString(),rawRows.isEmpty()?Map.of():Json.map(rawRows.getFirst().get("body"))));
        row.put("sources",db.queryForList("SELECT s.name,s.status,x.url,x.external_id,x.raw_id FROM item_sources x JOIN sources s ON s.id=x.source_id WHERE x.item_id=:id",Map.of("id",id)));
        row.put("versions",db.queryForList("SELECT version,changed_fields,payload,created_at FROM item_versions WHERE item_id=:id ORDER BY version DESC",Map.of("id",id)).stream().map(v -> {v.put("payload",Json.map(v.get("payload")));v.put("changed_fields",v.get("changed_fields").toString());return v;}).toList());
        row.put("skills",db.queryForList("SELECT * FROM job_skills WHERE item_id=:id ORDER BY skill",Map.of("id",id)));
        row.put("ai",db.queryForList("SELECT provider,result,created_at FROM ai_enrichments WHERE item_id=:id AND content_hash=:hash AND profile_updated_at=(SELECT updated_at FROM user_profiles WHERE id=1)",Map.of("id",id,"hash",row.get("content_hash"))).stream().map(v -> {v.put("result",Json.map(v.get("result")));return v;}).toList());
        return row;
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public List<Map<String,Object>> readingMany(List<Long> ids) {
        if(ids.isEmpty()||ids.size()>20||ids.stream().anyMatch(id->id<=0))throw new IllegalArgumentException("最多20个正整数ID");
        var rows=db.queryForList("SELECT i.id,i.content_hash"+READING_FIELDS+"i.kind FROM items i"+READING_JOIN+" WHERE i.id IN (:ids)",Map.of("ids",ids));
        rows.forEach(this::decode);
        return rows.stream().map(row->Map.of("id",row.get("id"),"content_hash",row.get("content_hash"),"reading",row.get("reading"))).toList();
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> jobOverview() {
        return Map.of("classification",classificationSummary(),"attention",overviewPreview("attention"),"leads",overviewPreview("leads"),"target",overviewPreview("target"));
    }
    private Map<String,Object> overviewPreview(String view) {
        var query=Map.of("domain","mainland","view",view,"includeDemo","false");
        Filter f=filter(query);String where=f.where();
        if(!view.equals("attention")) {
            // The same view predicates define both counts and previews. SQL NULL is not a match.
            String previous=view.equals("leads")?"attention":"leads";
            where+=" AND NOT coalesce("+predicate(filter(Map.of("domain","mainland","view",previous)))+",false)";
        }
        if(view.equals("target"))where+=" AND "+ItemAvailability.OPEN_SQL+" AND m.hard_status IS DISTINCT FROM 'not_eligible'";
        long total=db.queryForObject("SELECT count(*) FROM items i"+EmployerRegistry.JOIN+MATCH_JOIN+where,f.params(),Long.class);
        // Rank the complete eligible pool before LIMIT: prolific employers cannot hide a later employer.
        // Blank/unknown company names share one NULL partition rather than getting a partition per item.
        String ranked="WITH ranked AS (SELECT i.id,row_number() OVER (PARTITION BY "+EMPLOYER_KEY+" ORDER BY "+RECOMMENDATION_ORDER+") AS employer_rank,row_number() OVER (ORDER BY "+RECOMMENDATION_ORDER+") AS preview_rank FROM items i"+EmployerRegistry.JOIN+MATCH_JOIN+where+") ";
        var rows=db.queryForList(ranked+"SELECT i.*,to_jsonb(e) AS employer,m.hard_status,m.score,m.explanation"+READING_FIELDS+MATCH_STATE+",a.status AS application_status FROM ranked r JOIN items i ON i.id=r.id"+EmployerRegistry.JOIN+READING_JOIN+MATCH_JOIN+" LEFT JOIN job_applications a ON a.item_id=i.id WHERE r.employer_rank<=2 ORDER BY r.preview_rank LIMIT 5",f.params());
        rows.forEach(this::decode);attachProvenance(rows);
        return Map.of("items",rows,"total",total,"page",0,"size",5,"sort","recommendation","maxPerEmployer",2);
    }
    private static String predicate(Filter filter) {
        return "("+filter.where().substring(" WHERE ".length())+")";
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> jobCoverage(String domain) {
        if(!Set.of("domestic","foreign","unclassified","mainland","all").contains(domain))throw new IllegalArgumentException("岗位范围无效");
        Filter f=filter(Map.of("domain",domain,"includeDemo","false"));
        var result=new LinkedHashMap<>(db.queryForMap("SELECT count(*) AS jobs,count(DISTINCT "+EMPLOYER_KEY+") AS \"employerCount\",count(*) FILTER(WHERE m.item_id IS NULL) AS pending,count(*) FILTER(WHERE i.employment_type='internship') AS internships,count(*) FILTER(WHERE i.employment_type='internship' AND ((i.education='bachelor' AND i.payload->>'student_required'='true') OR (i.payload->>'bachelor_student_evidence' IS NOT NULL AND coalesce(i.education,'') NOT IN ('master','doctor'))) AND i.payload->>'accepts_bachelor' IS DISTINCT FROM 'false') AS \"bachelorStudentInternships\",count(*) FILTER(WHERE i.employment_type='campus') AS campus"
            +",count(*) FILTER(WHERE "+predicate(filter(Map.of("domain",domain,"view","target")))+") AS target"
            +",count(*) FILTER(WHERE "+predicate(filter(Map.of("domain",domain,"view","leads")))+") AS leads"
            +",count(*) FILTER(WHERE "+predicate(filter(Map.of("domain",domain,"view","attention")))+") AS attention"
            +" FROM items i"+EmployerRegistry.JOIN+MATCH_JOIN+f.where(),f.params()));
        var sources=db.queryForList("SELECT s.id,s.name,s.adapter,count(DISTINCT i.id) AS jobs FROM items i"+EmployerRegistry.JOIN+MATCH_JOIN+" JOIN item_sources x ON x.item_id=i.id JOIN sources s ON s.id=x.source_id"+f.where()+" GROUP BY s.id,s.name,s.adapter ORDER BY jobs DESC,s.id",f.params());
        result.put("domain",domain);result.put("all",result.get("jobs"));result.put("sourceCount",sources.size());result.put("sources",sources);
        return result;
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> classificationSummary() {
        var result=new LinkedHashMap<String,Object>();
        for(String domain:List.of("domestic","foreign","unclassified","mainland","all")) {
            result.put(domain,jobCoverage(domain));
        }
        result.put("unknownCompanyWorldwide",db.queryForObject("SELECT count(*) FROM items i"+EmployerRegistry.JOIN+" WHERE i.kind='job' AND NOT i.is_demo AND (e.status IS NULL OR e.status<>'verified')",Map.of(),Long.class));
        result.put("secondaryMainlandListed",db.queryForObject("SELECT count(*) FROM items i WHERE i.kind='job' AND NOT i.is_demo AND i.country IS DISTINCT FROM 'CN' AND i.payload @> '{\"locations\":[{\"country\":\"CN\"}]}'::jsonb",Map.of(),Long.class));
        result.put("explicitNonMainland",db.queryForObject("SELECT count(*) FROM items i WHERE i.kind='job' AND NOT i.is_demo AND i.country='CN' AND concat_ws(' ',i.city,i.payload->>'province') ~* '"+NON_MAINLAND+"'",Map.of(),Long.class));
        result.put("scope","中心仅含主要工作国家明确CN且没有港澳台地点冲突的唯一真实岗位；主地点海外、附加大陆的记录保留在全部存档待核验；实习/校招是来源类型标签，非个人资格确认");
        return result;
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> stats(Map<String,String> query) {
        var q=new HashMap<>(query); q.put("kind","job"); Filter f=filter(q);
        var sample=db.queryForObject("SELECT count(*) FROM items i"+EmployerRegistry.JOIN+MATCH_JOIN+f.where(),f.params(),Long.class);
        var skills=db.queryForList("SELECT s.skill,s.requirement,count(DISTINCT i.id) AS jobs FROM items i"+EmployerRegistry.JOIN+MATCH_JOIN+" JOIN job_skills s ON i.id=s.item_id"+f.where()+" GROUP BY s.skill,s.requirement ORDER BY jobs DESC,s.skill",f.params());
        var sources=db.queryForList("SELECT DISTINCT src.id,src.name,src.status FROM items i"+EmployerRegistry.JOIN+MATCH_JOIN+" JOIN item_sources x ON x.item_id=i.id JOIN sources src ON src.id=x.source_id"+f.where(),f.params());
        return Map.of("sampleSize",sample,"skills",skills,"sources",sources,"filters",q,"generatedAt",java.time.OffsetDateTime.now(),"timeBasis","first_seen，Asia/Shanghai；并非招聘发布时间","limitation","有限样本无法代表整个招聘市场；每个规范化岗位仅统计一次；演示数据默认排除");
    }
}
