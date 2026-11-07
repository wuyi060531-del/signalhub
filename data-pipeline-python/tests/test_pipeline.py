from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from sqlalchemy import text
from signalhub.pipeline import Pipeline
from signalhub.worker import Worker
from signalhub.normalize import stable_hash
import httpx
import pytest

RAW=dict(kind='job',external_id='job1',title='数据工程实习',body='2027届；本科；要求 Python SQL',company='Example',company_type='foreign',country='CN',city='上海',url='https://example.com/job/1')

def scalar(db,sql):
    with db.connect() as c:return c.execute(text(sql)).scalar_one()

def test_idempotent_changes_and_provenance(db):
    p=Pipeline(db)
    assert p.run(1,[RAW])['inserted']==1
    assert p.run(1,[RAW])['deduplicated']==1
    assert p.run(1,[{**RAW,'body':RAW['body']+'；要求 Spark'}])['updated']==1
    assert scalar(db,'SELECT count(*) FROM items')==1
    assert scalar(db,'SELECT count(*) FROM item_versions')==2
    assert scalar(db,'SELECT count(*) FROM alerts')==1
    p.run(1,[{**RAW,'body':RAW['body']+'；要求 Spark'}])
    assert scalar(db,'SELECT count(*) FROM alerts')==1
    p.run(2,[{**RAW,'external_id':'other-id','body':RAW['body']+'；要求 Spark'}])
    assert scalar(db,'SELECT count(*) FROM item_sources')==2
    assert scalar(db,'SELECT count(*) FROM items')==1

def test_suspected_duplicates_not_auto_merged(db):
    Pipeline(db).run(1,[RAW,{**RAW,'external_id':'job2','url':'https://example.com/other'}])
    assert scalar(db,'SELECT count(*) FROM items')==2
    assert scalar(db,'SELECT count(*) FROM duplicate_candidates')==1

def test_invalid_records_retained_and_resume(db):
    result=Pipeline(db).run(1,[RAW,{'external_id':'bad','kind':'job'}, {**RAW,'external_id':'missing-url','url':None}])
    assert result['state']=='partial' and result['failed']==1 and result['parsed']==2
    assert scalar(db,'SELECT count(*) FROM raw_records')==3
    assert Pipeline(db).run(1,[RAW])['deduplicated']==1

def test_manual_import_links_saved_items_after_insert_update_duplicate_and_partial_failure(db):
    raw={**RAW,'title':'[合成测试] 数据工程实习','is_demo':True}
    p=Pipeline(db)
    inserted=p.run(1,[raw])
    item_id=scalar(db,'SELECT id FROM items')
    assert inserted['inserted']==1 and inserted['item_ids']==[item_id] and inserted['item_count']==1
    updated=p.run(1,[{**raw,'body':raw['body']+'；要求 Spark'}])
    assert updated['updated']==1 and updated['item_ids']==[item_id]
    partial=p.run(1,[{**raw,'body':raw['body']+'；要求 Spark'},
                     {'external_id':'bad','kind':'job'},
                     {**raw,'external_id':'another-source-id','url':raw['url'],'body':raw['body']+'；要求 Spark'}])
    assert partial['state']=='partial' and partial['failed']==1 and partial['deduplicated']==2
    assert partial['item_ids']==[item_id] and partial['item_count']==1
    assert scalar(db,'SELECT count(*) FROM items')==1
    failed=p.run(1,[{'external_id':'bad-only','kind':'job'}])
    assert failed['item_ids']==[] and failed['item_count']==0

def test_manual_import_links_are_bounded_without_losing_saved_count(db):
    records=[{**RAW,'title':'[合成测试] 数据工程实习','is_demo':True,'external_id':f'job-{i}','url':f'https://example.com/job/{i}'} for i in range(23)]
    result=Pipeline(db).run(1,records+records)
    with db.connect() as c:ids=list(c.execute(text('SELECT id FROM items ORDER BY id')).scalars())
    assert result['inserted']==23 and result['deduplicated']==23
    assert result['item_ids']==ids[:20] and result['item_count']==23

def test_concurrent_ingest_no_duplicate_versions(db):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda x:Pipeline(db).run(1,[RAW]),range(2)))
    assert scalar(db,'SELECT count(*) FROM items')==1
    assert scalar(db,'SELECT count(*) FROM item_versions')==1
    assert sum(r['inserted'] for r in results)==1

def test_failure_keeps_etag_and_records_run(db):
    with db.begin() as c:c.execute(text("INSERT INTO sources(name,adapter,enabled,etag,config) VALUES ('bad network','github',true,'old','{\"repo\":\"test/repo\"}')"))
    source=scalar(db,"SELECT id FROM sources WHERE name='bad network'")
    class Broken:
        def get(self,*a):raise httpx.ReadTimeout('test')
    result=Pipeline(db,Broken()).run(source)
    assert result['state']=='failed'
    assert 'item_ids' not in result and 'item_count' not in result
    assert scalar(db,f'SELECT etag FROM sources WHERE id={source}')=='old'
    assert scalar(db,f"SELECT state FROM collection_runs WHERE source_id={source}")=='failed'

def test_pipeline_owns_network_client_only_for_collect_and_closes_after_lazy_failure(db, monkeypatch):
    from signalhub import pipeline
    clients = []
    def fetcher():
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        clients.append(client)
        return SimpleNamespace(client=client)

    class LazyAdapter:
        def fetch(self, config, fetcher, headers):
            def rows():
                assert not fetcher.client.is_closed
                yield RAW
                raise httpx.ReadTimeout('synthetic fetch failure')
            return rows(), None, False

    monkeypatch.setattr(pipeline, 'Fetcher', fetcher)
    monkeypatch.setitem(pipeline.ADAPTERS, 'github', LazyAdapter)
    assert Pipeline(db).run(1, [RAW])['state'] == 'success'
    assert not clients
    with db.begin() as conn:
        source = conn.execute(text("INSERT INTO sources(name,adapter,enabled) VALUES ('synthetic lazy','github',true) RETURNING id")).scalar_one()
    result = Pipeline(db).run(source)
    assert result['state'] == 'failed' and result['parsed'] == 1
    assert len(clients) == 1 and clients[0].is_closed

def test_crashed_task_recovered(db):
    with db.begin() as c:
        c.execute(text("INSERT INTO task_requests(task_type,source_id,payload,state,attempts,started_at) VALUES ('import',1,'{\"records\":[]}','running',1,now()-interval '16 minutes')"))
    assert Worker(db).tick()['state']=='success'
    assert scalar(db,'SELECT state FROM task_requests')=='done'
    assert scalar(db,'SELECT attempts FROM task_requests')==2

def test_database_failure_does_not_commit_half_item(db,monkeypatch):
    p=Pipeline(db)
    original=p.ingest_one
    from signalhub import pipeline
    execute=pipeline.execute
    def fail(conn,sql,**kwargs):
        if 'INSERT INTO item_versions' in sql:raise RuntimeError('simulated database unavailable')
        return execute(conn,sql,**kwargs)
    monkeypatch.setattr(pipeline,'execute',fail)
    result=p.run(1,[RAW])
    assert result['failed']==1 and scalar(db,'SELECT count(*) FROM items')==0
    assert scalar(db,'SELECT count(*) FROM raw_records')==1
    monkeypatch.setattr(pipeline,'execute',execute)
    assert p.run(1,[RAW])['inserted']==1

def test_changed_official_url_keeps_alias_history(db):
    p=Pipeline(db);p.run(1,[RAW]);p.run(1,[{**RAW,'url':'https://example.com/new-official'}])
    p.run(2,[{**RAW,'external_id':'source-b','url':'https://example.com/new-official'}])
    assert scalar(db,'SELECT count(*) FROM items')==1
    assert scalar(db,'SELECT count(*) FROM canonical_aliases')==2

def test_identifier_kind_demo_and_alias_conflicts_do_not_overwrite(db):
    p=Pipeline(db);p.run(1,[RAW,{**RAW,'external_id':'other','url':'https://example.com/job/other'}])
    for change in [dict(kind='release'),dict(is_demo=True),dict(url='https://example.com/job/other')]:
        result=p.run(1,[{**RAW,**change}])
        assert result['state']=='partial' and result['failed']==1
    assert scalar(db,'SELECT count(*) FROM items')==2
    assert scalar(db,'SELECT max(version) FROM items')==1
    assert scalar(db,'SELECT count(*) FROM raw_records')==5

def test_paid_ai_block_is_visible_as_failed_task(db,monkeypatch):
    monkeypatch.setenv('AI_PROVIDER','compatible');monkeypatch.delenv('AI_API_KEY',raising=False)
    _,item_id=Pipeline(db).ingest_one(Pipeline(db).source(1),RAW)
    with db.begin() as c:c.execute(text("INSERT INTO task_requests(task_type,source_id,payload) VALUES ('enrich',1,CAST(:p AS jsonb))"),{'p':'{"item_id":'+str(item_id)+'}'})
    assert Worker(db).tick()['state']=='blocked'
    assert scalar(db,'SELECT state FROM task_requests')=='failed'

def test_force_refresh_bypasses_cache_but_normal_run_keeps_it(db):
    with db.begin() as c:c.execute(text("INSERT INTO sources(name,adapter,enabled,etag,config) VALUES ('cache-source','greenhouse',true,'old','{\"board\":\"test\"}')"))
    source=scalar(db,"SELECT id FROM sources WHERE name='cache-source'")
    calls=[]
    class Fetch:
        def get(self,url,headers):
            calls.append(dict(headers));return httpx.Response(200,json={'jobs':[]},headers={'etag':'new'})
    p=Pipeline(db,Fetch());p.run(source);p.run(source,force=True)
    assert calls[0]['If-None-Match']=='old' and 'If-None-Match' not in calls[1]

def test_worker_unexpected_failure_is_bounded_to_three_attempts(db,monkeypatch):
    with db.begin() as c:c.execute(text("INSERT INTO task_requests(task_type,source_id,payload) VALUES ('import',1,'{\"records\":[]}')"))
    def broken(*a,**k):raise RuntimeError('synthetic unexpected failure')
    monkeypatch.setattr(Pipeline,'run',broken)
    for _ in range(3):assert Worker(db).tick()['state']=='failed'
    assert Worker(db).tick() is None
    assert scalar(db,'SELECT state FROM task_requests')=='failed' and scalar(db,'SELECT attempts FROM task_requests')==3

def test_malformed_row_is_retained_without_aborting_remaining_batch(db):
    result=Pipeline(db).run(1,[RAW,None,'invalid row',{**RAW,'external_id':'second','url':'https://example.com/2'}])
    assert result['state']=='partial' and result['parsed']==2 and result['failed']==2
    assert scalar(db,'SELECT count(*) FROM raw_records')==4
    assert scalar(db,'SELECT count(*) FROM items')==2


def test_expired_worker_cannot_overwrite_new_lease_result(db,monkeypatch):
    from threading import Event
    entered,release=Event(),Event()
    calls=[]
    with db.begin() as c:c.execute(text("INSERT INTO task_requests(task_type,source_id,payload) VALUES ('import',1,'{\"records\":[]}')"))
    def delayed(*args,**kwargs):
        calls.append(True)
        if len(calls)==1:
            entered.set();assert release.wait(10)
            return {'state':'success','owner':'old'}
        return {'state':'success','owner':'new'}
    monkeypatch.setattr(Pipeline,'run',delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old=pool.submit(Worker(db).tick)
        try:
            assert entered.wait(5)
            with db.begin() as c:c.execute(text("UPDATE task_requests SET started_at=now()-interval '16 minutes'"))
            assert Worker(db).tick()['owner']=='new'
        finally:release.set()
        assert old.result()['state']=='superseded'
    assert scalar(db,"SELECT result->>'owner' FROM task_requests")=='new'
    assert scalar(db,'SELECT attempts FROM task_requests')==2
    assert scalar(db,'SELECT state FROM task_requests')=='done'


def test_expired_worker_exception_cannot_requeue_completed_new_lease(db,monkeypatch):
    from threading import Event
    entered,release=Event(),Event()
    calls=[]
    with db.begin() as c:c.execute(text("INSERT INTO task_requests(task_type,source_id,payload) VALUES ('import',1,'{\"records\":[]}')"))
    def delayed(*args,**kwargs):
        calls.append(True)
        if len(calls)==1:
            entered.set();assert release.wait(10)
            raise RuntimeError('old lease failed')
        return {'state':'success','owner':'new'}
    monkeypatch.setattr(Pipeline,'run',delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old=pool.submit(Worker(db).tick)
        try:
            assert entered.wait(5)
            with db.begin() as c:c.execute(text("UPDATE task_requests SET started_at=now()-interval '16 minutes'"))
            assert Worker(db).tick()['owner']=='new'
        finally:release.set()
        assert old.result()['state']=='superseded'
    assert scalar(db,'SELECT state FROM task_requests')=='done'
    assert scalar(db,'SELECT error FROM task_requests') is None


@pytest.mark.parametrize("pause_at", ["fetch", "normalize", "finish"])
def test_expired_collect_cannot_change_new_attempt_data(db, monkeypatch, pause_at):
    from signalhub import pipeline

    paused, resume = Event(), Event()
    initial = {**RAW, "body": "Required: Python.", "is_demo": True}
    stale = {**initial, "body": "Required: Python and Java."}
    current = {**initial, "body": "Required: Python and SQL."}
    old_response = httpx.Response(200, headers={"ETag": "old", "Last-Modified": "old"})
    new_response = httpx.Response(200, headers={"ETag": "new", "Last-Modified": "new"})
    with db.begin() as conn:
        source = conn.execute(text(
            "INSERT INTO sources(name,adapter,enabled) VALUES ('synthetic-lease','github',true) RETURNING id"
        )).scalar_one()
    assert Pipeline(db).run(source, [initial])["inserted"] == 1
    with db.begin() as conn:
        task_id = conn.execute(text(
            "INSERT INTO task_requests(task_type,source_id,payload) VALUES ('collect',:source,'{}') RETURNING id"
        ), {"source": source}).scalar_one()

    def pause():
        paused.set()
        assert resume.wait(15)

    def old_records():
        # Commit a legitimate duplicate while the first attempt still owns the lease.
        yield initial
        pause()
        raise ValueError("synthetic late fetch error")

    class SyntheticAdapter:
        def fetch(self, config, fetcher, headers):
            if paused.is_set():
                return [current], new_response, False
            if pause_at == "fetch":
                pause()
            records = old_records() if pause_at == "finish" else [stale]
            return records, old_response, False

    normalize = pipeline.normalize

    def normalize_with_pause(raw):
        if pause_at == "normalize" and raw["body"] == stale["body"]:
            pause()
        return normalize(raw)

    monkeypatch.setitem(pipeline.ADAPTERS, "github", SyntheticAdapter)
    monkeypatch.setattr(pipeline, "normalize", normalize_with_pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(Worker(db).tick)
        try:
            assert paused.wait(5)
            with db.begin() as conn:
                assert conn.execute(text("SELECT attempts FROM task_requests")).scalar_one() == 1
                conn.execute(text("UPDATE task_requests SET started_at=now()-interval '16 minutes'"))
                old_run = conn.execute(text("""
                    UPDATE collection_runs SET started_at=now()-interval '16 minutes'
                    WHERE state='running' RETURNING id
                """)).scalar_one()
            result = Worker(db).tick()
            assert result["updated"] == 1
            last_success = scalar(db, f"SELECT last_success FROM sources WHERE id={source}")
        finally:
            resume.set()
        assert old.result(timeout=5) == {"state": "superseded", "task_id": task_id}

    with db.connect() as conn:
        assert conn.execute(text("SELECT version,payload->>'body' FROM items")).one() == (2, current["body"])
        assert conn.execute(text("SELECT version,payload->>'body' FROM item_versions ORDER BY version")).all() == [
            (1, initial["body"]), (2, current["body"]),
        ]
        assert conn.execute(text("""
            SELECT i.version,r.body->>'body' FROM item_sources s
            JOIN items i ON s.item_id=i.id JOIN raw_records r ON r.id=s.raw_id
        """)).one() == (2, current["body"])
        assert conn.execute(text("""
            SELECT state,attempts,result,error FROM task_requests WHERE id=:id
        """), {"id": task_id}).one() == ("done", 2, result, None)
        assert conn.execute(text("""
            SELECT state,collected,updated FROM collection_runs WHERE id IN (:old,:new) ORDER BY id
        """), {"old": old_run, "new": result["run_id"]}).all() == [
            ("interrupted", 0, 0), ("success", 1, 1),
        ]
        assert conn.execute(text("""
            SELECT status,etag,last_modified,last_success FROM sources WHERE id=:id
        """), {"id": source}).one() == ("verified", "new", "new", last_success)
        assert conn.execute(text("SELECT split_part(dedup_key,':',3) FROM alerts")).scalars().all() == ["2"]
        raw_count = 3 if pause_at == "normalize" else 2
        assert conn.execute(text("SELECT count(*) FROM raw_records")).scalar_one() == raw_count


def test_expired_collect_stops_writing_before_any_takeover(db, monkeypatch):
    from signalhub import pipeline

    class ExpiringAdapter:
        def fetch(self, config, fetcher, headers):
            with db.begin() as conn:
                conn.execute(text("UPDATE task_requests SET started_at=now()-interval '16 minutes'"))
            return [{**RAW, "is_demo": True}], httpx.Response(200), False

    with db.begin() as conn:
        source = conn.execute(text(
            "INSERT INTO sources(name,adapter,enabled) VALUES ('synthetic-expiry','github',true) RETURNING id"
        )).scalar_one()
        task_id = conn.execute(text(
            "INSERT INTO task_requests(task_type,source_id,payload) VALUES ('collect',:source,'{}') RETURNING id"
        ), {"source": source}).scalar_one()
    monkeypatch.setitem(pipeline.ADAPTERS, "github", ExpiringAdapter)
    assert Worker(db).tick() == {"state": "superseded", "task_id": task_id}
    assert scalar(db, "SELECT state FROM task_requests") == "running"
    assert scalar(db, "SELECT count(*) FROM raw_records") == 0
    assert scalar(db, "SELECT count(*) FROM items") == 0
    assert scalar(db, "SELECT state FROM collection_runs") == "running"


def test_transient_database_failure_retries_idempotently(db,monkeypatch):
    from sqlalchemy.exc import OperationalError
    import json
    with db.begin() as c:c.execute(text("INSERT INTO task_requests(task_type,source_id,payload) VALUES ('import',1,CAST(:p AS jsonb))"),{'p':json.dumps({'records':[RAW,{**RAW,'external_id':'job2','url':'https://example.com/job/2'}]})})
    ingest=Pipeline.ingest_one
    broken=[True]
    def flaky(self,source,raw):
        if raw['external_id']=='job2' and broken[0]:
            broken[0]=False
            raise OperationalError('synthetic',{},RuntimeError('temporary connection lost'))
        return ingest(self,source,raw)
    monkeypatch.setattr(Pipeline,'ingest_one',flaky)
    first=Worker(db).tick()
    assert first['retryable'] and first['inserted']==1
    assert scalar(db,'SELECT state FROM task_requests')=='pending'
    second=Worker(db).tick()
    assert second['state']=='success' and second['deduplicated']==1 and second['inserted']==1
    assert scalar(db,'SELECT attempts FROM task_requests')==2
    assert scalar(db,'SELECT count(*) FROM item_versions')==2


def test_persistent_database_failure_stops_after_three_claims(db,monkeypatch):
    from sqlalchemy.exc import OperationalError
    import json
    with db.begin() as c:c.execute(text("INSERT INTO task_requests(task_type,source_id,payload) VALUES ('import',1,CAST(:p AS jsonb))"),{'p':json.dumps({'records':[RAW]})})
    def broken(*a,**k):raise OperationalError('synthetic',{},RuntimeError('connection unavailable'))
    monkeypatch.setattr(Pipeline,'ingest_one',broken)
    for _ in range(3):assert Worker(db).tick()['retryable']
    assert Worker(db).tick() is None
    assert scalar(db,'SELECT state FROM task_requests')=='failed'
    assert scalar(db,'SELECT finished_at IS NOT NULL FROM task_requests')

def test_archive_reparse_does_not_claim_fresh_network_verification(db):
    import pytest
    with db.begin() as c:c.execute(text("UPDATE sources SET status='unavailable',etag='historical',last_success=now()-interval '2 days' WHERE id=1"))
    before=scalar(db,'SELECT last_success FROM sources WHERE id=1')
    p=Pipeline(db)
    with pytest.raises(ValueError):p.run(1,refresh_source=False)
    result=p.run(1,[RAW],refresh_source=False)
    assert result['inserted']==1 and result['mode']=='archive_reparse'
    assert 'item_ids' not in result and 'item_count' not in result
    assert scalar(db,'SELECT last_success FROM sources WHERE id=1')==before
    assert scalar(db,'SELECT status FROM sources WHERE id=1')=='unavailable'
    assert scalar(db,'SELECT etag FROM sources WHERE id=1')=='historical'
    assert scalar(db,'SELECT mode FROM collection_runs')=='archive_reparse'


def test_group_condition_change_versions_alerts_and_failure_recovery(db,monkeypatch):
    from signalhub import pipeline
    raw={**RAW,'body':'2026/2027届；硕士在读；要求Python、Java、SQL任意两种'}
    p=Pipeline(db)
    assert p.run(1,[raw])['inserted']==1
    with db.connect() as c:
        payload=c.execute(text('SELECT payload FROM items')).scalar_one()
    assert payload['skill_groups'][0]['minimum']==2 and payload['graduation_years']==[2026,2027]
    assert payload['student_required'] is True
    assert p.run(1,[raw])['deduplicated']==1
    changed={**raw,'body':raw['body'].replace('两种','三种')}
    original=pipeline.execute
    def fail(conn,sql,**kwargs):
        if 'INSERT INTO item_versions' in sql:raise RuntimeError('synthetic group update failure')
        return original(conn,sql,**kwargs)
    monkeypatch.setattr(pipeline,'execute',fail)
    assert p.run(1,[changed])['failed']==1
    assert scalar(db,'SELECT version FROM items')==1
    assert scalar(db,"SELECT (payload->'skill_groups'->0->>'minimum')::int FROM items")==2
    monkeypatch.setattr(pipeline,'execute',original)
    assert p.run(1,[changed])['updated']==1
    assert p.run(1,[changed])['deduplicated']==1
    assert scalar(db,'SELECT count(*) FROM item_versions')==2
    assert scalar(db,'SELECT count(*) FROM alerts')==1
    assert scalar(db,'SELECT count(*) FROM raw_records')==2


def test_experience_update_failure_preserves_old_bound_and_retry_alert_once(db,monkeypatch):
    from signalhub import pipeline
    raw={**RAW,'title':'数据工程师','body':'本科2027届；工作经验：3年以上；要求Python SQL'}
    p=Pipeline(db);assert p.run(1,[raw])['inserted']==1
    changed={**raw,'body':raw['body'].replace('3年以上','4年以上')}
    original=pipeline.execute
    def fail(conn,sql,**kwargs):
        if 'INSERT INTO item_versions' in sql:raise RuntimeError('synthetic experience update failure')
        return original(conn,sql,**kwargs)
    monkeypatch.setattr(pipeline,'execute',fail)
    assert p.run(1,[changed])['failed']==1
    assert scalar(db,'SELECT version FROM items')==1
    assert scalar(db,"SELECT (payload->'experience_requirements'->0->>'minimum_years')::float FROM items")==3
    monkeypatch.setattr(pipeline,'execute',original)
    assert p.run(1,[changed])['updated']==1 and p.run(1,[changed])['deduplicated']==1
    assert scalar(db,'SELECT count(*) FROM item_versions')==2 and scalar(db,'SELECT count(*) FROM alerts')==1


def test_quality_feedback_explains_evidence_without_echoing_raw_input(db):
    import json
    from signalhub.pipeline import quality_error
    raw={**RAW, 'external_id':'bad-evidence', 'body':'要求SQL；private-test-value', 'is_demo':True,
         'skills':[dict(name='Python', requirement='required', evidence='missing-evidence')]}
    result=Pipeline(db).run(1,[raw])
    assert result['failed']==1 and result['inserted']==0
    details=result['errors'][0]['details']
    assert any('原文证据' in detail['message'] for detail in details)
    assert 'private-test-value' not in json.dumps(result['errors'])
    assert scalar(db,'SELECT count(*) FROM raw_records')==1
    assert scalar(db,'SELECT count(*) FROM items')==0
    assert 'password=do-not-echo' not in str(quality_error(RuntimeError('password=do-not-echo')))


def test_same_archived_raw_reparse_keeps_versions_without_change_alert(db):
    p = Pipeline(db)
    archive = {"id": "public-original", "description": RAW['body']}
    assert p.run(1, [{**RAW, '_raw': archive}])['inserted'] == 1
    # 模拟解析规则增加结构字段，输入官方原文完全相同。
    parsed = {**RAW, '_raw': archive, 'remote': True}
    result = p.run(1, [parsed], refresh_source=False)
    assert result['updated'] == 1 and result['mode'] == 'archive_reparse'
    assert scalar(db, 'SELECT count(*) FROM item_versions') == 2
    assert scalar(db, 'SELECT count(*) FROM raw_records') == 1
    assert scalar(db, 'SELECT count(*) FROM alerts') == 0
    # 普通采集中的解析器变化也不得反复发通知。
    assert p.run(1, [{**parsed, 'remote': False}])['updated'] == 1
    assert scalar(db, 'SELECT count(*) FROM alerts') == 0
    changed = {**parsed, 'body': RAW['body'] + '；要求 Java', '_raw': {**archive, 'description': RAW['body'] + '；要求 Java'}}
    assert p.run(1, [changed])['updated'] == 1
    assert scalar(db, 'SELECT count(*) FROM alerts') == 1
    assert p.run(1, [changed])['deduplicated'] == 1
    assert scalar(db, 'SELECT count(*) FROM alerts') == 1


def test_new_nullable_contract_fields_always_get_a_traceable_version(db):
    import json
    raw={**RAW,'is_demo':True}
    p=Pipeline(db);assert p.run(1,[raw])['inserted']==1
    added=['bachelor_student_evidence','source_verified_at','source_verification_note']
    # Simulate an archived snapshot written before these optional fields existed.
    with db.begin() as c:
        payload=c.execute(text('SELECT payload FROM items')).scalar_one()
        legacy={k:v for k,v in payload.items() if k not in added}
        params={'payload':json.dumps(legacy),'hash':stable_hash(legacy)}
        c.execute(text('UPDATE items SET payload=CAST(:payload AS jsonb),content_hash=:hash'),params)
        c.execute(text('UPDATE item_versions SET payload=CAST(:payload AS jsonb)'),params)
    result=p.run(1,[raw],refresh_source=False)
    assert result['updated']==1
    with db.connect() as c:
        row=c.execute(text('SELECT i.version,v.changed_fields,v.raw_id FROM items i JOIN item_versions v ON v.item_id=i.id AND v.version=i.version')).one()
        assert row.version==2 and set(row.changed_fields)==set(added) and row.raw_id is not None
        assert c.execute(text('SELECT count(*) FROM raw_records')).scalar_one()==1
        assert c.execute(text('SELECT count(*) FROM alerts')).scalar_one()==0
    assert p.run(1,[raw],refresh_source=False)['deduplicated']==1


@pytest.mark.parametrize('legacy_value',[None,'retired-parser-value'])
def test_removed_legacy_fields_keep_snapshot_hash_skills_and_provenance_consistent(db,legacy_value):
    import json
    p=Pipeline(db);assert p.run(1,[RAW])['inserted']==1
    with db.begin() as c:
        payload=c.execute(text('SELECT payload FROM items')).scalar_one()
        legacy={**payload,'retired_field':legacy_value}
        params={'payload':json.dumps(legacy),'hash':stable_hash(legacy)}
        c.execute(text('UPDATE items SET payload=CAST(:payload AS jsonb),content_hash=:hash'),params)
        c.execute(text('UPDATE item_versions SET payload=CAST(:payload AS jsonb)'),params)
    # 模拟升级后删除旧规范字段，官方原文没有改变。
    result=p.run(1,[RAW],refresh_source=False)
    assert result['updated']==1
    with db.connect() as c:
        current=c.execute(text('SELECT i.version,i.payload,i.content_hash,v.payload AS snapshot,v.changed_fields,v.raw_id FROM items i JOIN item_versions v ON v.item_id=i.id AND v.version=i.version')).one()
        assert current.version==2 and current.payload==current.snapshot
        assert current.content_hash==stable_hash(current.snapshot)
        assert current.changed_fields==['retired_field'] and current.raw_id is not None
        assert c.execute(text('SELECT count(*) FROM raw_records')).scalar_one()==1
        assert c.execute(text('SELECT count(*) FROM alerts')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM job_skills')).scalar_one()>0
    assert p.run(1,[RAW],refresh_source=False)['deduplicated']==1


def test_github_first_page_validator_does_not_hide_later_release_changes(db):
    with db.begin() as c:
        source=c.execute(text("INSERT INTO sources(name,adapter,enabled,config) VALUES ('synthetic-github-pagination','github',true,'{\"repo\":\"synthetic/releases\"}') RETURNING id")).scalar_one()
    changed=False;calls=[]
    def release(identifier,body='synthetic release notes'):
        return dict(id=identifier,tag_name=f'v{identifier}',html_url=f'https://github.com/synthetic/releases/releases/tag/v{identifier}',body=body,draft=False)
    class Pages:
        def get(self,url,headers):
            calls.append((url,dict(headers)))
            if 'page=2' in url:return httpx.Response(200,json=[release(101,'changed synthetic release notes' if changed else 'synthetic release notes')])
            if any(k.lower() in ('if-none-match','if-modified-since') for k in headers):return httpx.Response(304)
            return httpx.Response(200,json=[release(n) for n in range(1,101)],headers={'ETag':'unchanged-page-one'})
    p=Pipeline(db,Pages());assert p.run(source)['inserted']==101
    changed=True
    second=p.run(source)
    assert second['state']=='success' and second['updated']==1 and second['deduplicated']==100
    assert p.run(source)['deduplicated']==101
    assert len(calls)==6
    assert scalar(db,'SELECT count(*) FROM items')==101
    assert scalar(db,'SELECT count(*) FROM item_versions')==102
    assert scalar(db,'SELECT count(*) FROM alerts')==1
