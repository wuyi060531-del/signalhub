import json
import logging
from typing import Any
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import text
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError, InterfaceError
from .normalize import normalize, content, stable_hash, canonical_url
from .adapters import ADAPTERS
from .http import Fetcher
from .diagnostics import failure_context, safe_stack, log_failure

log = logging.getLogger(__name__)

def quality_error(exc: Exception) -> list[dict[str, str]]:
    if isinstance(exc, ValidationError):
        return [{'field': '.'.join(map(str, issue['loc'])) or 'record', 'message': issue['msg']}
                for issue in exc.errors(include_input=False, include_context=False, include_url=False)[:20]]
    safe = {'每条记录必须是JSON对象', '同一来源标识不能改变信息类型或演示属性', '官方链接已属于另一实体，需要人工审查'}
    return [{'field':'record', 'message':str(exc) if str(exc) in safe else '字段或原文证据无效，请核对该记录；技术错误类型见error'}]

def dump(value):
    return json.dumps(value, ensure_ascii=False, default=str)

def execute(conn, sql, **params):
    return conn.execute(text(sql),params)


TASK_LEASE_SECONDS = 15 * 60


class TaskLeaseLost(Exception):
    """The claimed attempt no longer owns the task."""


@dataclass(frozen=True)
class TaskLease:
    task_id: int
    attempt: int

    def require_current(self, conn):
        # Lock first, then check expiry with wall time. The reaper cannot take over
        # between this check and the writes committed by the same transaction.
        owned = execute(conn, """
            WITH locked AS MATERIALIZED (
                SELECT state, attempts, started_at FROM task_requests
                WHERE id=:id FOR UPDATE
            )
            SELECT 1 FROM locked WHERE state='running' AND attempts=:attempt
                AND started_at >= clock_timestamp() - :seconds * interval '1 second'
        """, id=self.task_id, attempt=self.attempt, seconds=TASK_LEASE_SECONDS).scalar()
        if owned is None:
            raise TaskLeaseLost()


class Pipeline:
    def __init__(self, engine, fetcher=None, *, lease: TaskLease | None = None):
        self.engine = engine
        self.fetcher = fetcher
        self.lease = lease

    @contextmanager
    def _write(self):
        with self.engine.begin() as conn:
            if self.lease is not None:
                self.lease.require_current(conn)
            yield conn

    def source(self, source_id):
        with self.engine.connect() as conn:
            row = execute(conn,'SELECT * FROM sources WHERE id=:id',id=source_id).mappings().one()
            return dict(row)

    def ingest_one(self, source, raw):
        external_id = str(raw.get('external_id','')) if isinstance(raw,dict) else ''
        original = raw.get('_raw',raw) if isinstance(raw,dict) else raw
        with self._write() as conn:
            raw_id = execute(conn,'''INSERT INTO raw_records(source_id,external_id,raw_hash,body)
                VALUES (:source,:ext,:hash,CAST(:body AS jsonb)) ON CONFLICT(source_id,external_id,raw_hash)
                DO UPDATE SET raw_hash=excluded.raw_hash RETURNING id''',source=source['id'],ext=external_id,hash=stable_hash(original),body=dump(original)).scalar_one()
        if not isinstance(raw,dict): raise ValueError('每条记录必须是JSON对象')
        item = normalize({k:v for k,v in raw.items() if k != '_raw'})
        payload = content(item)
        new_hash = stable_hash(payload)
        canonical = (f"demo:{source['id']}:" if item.is_demo else '') + item.kind + ':' + (canonical_url(item.url) if item.url else f"source:{source['id']}:{external_id}")
        with self._write() as conn:
            # 同一来源标识和同一 canonical URL 都串行化，避免并发创建/版本号竞争。
            execute(conn,'SELECT pg_advisory_xact_lock(hashtext(:key))',key=f"source:{source['id']}:{external_id}")
            execute(conn,'SELECT pg_advisory_xact_lock(hashtext(:key))',key=canonical)
            old = execute(conn,'''SELECT i.* FROM items i JOIN item_sources s ON s.item_id=i.id
                WHERE s.source_id=:source AND s.external_id=:ext FOR UPDATE OF i''',source=source['id'],ext=external_id).mappings().first()
            if old is None:
                old = execute(conn,'SELECT i.* FROM items i JOIN canonical_aliases a ON a.item_id=i.id WHERE a.canonical_key=:key FOR UPDATE OF i',key=canonical).mappings().first()
            if old is not None:
                if old['kind'] != item.kind or old['is_demo'] != item.is_demo:
                    raise ValueError('同一来源标识不能改变信息类型或演示属性')
                alias = old['id'] if canonical == old['canonical_key'] else execute(conn,'SELECT item_id FROM canonical_aliases WHERE canonical_key=:key',key=canonical).scalar()
                if alias is not None and alias != old['id']:
                    # 不覆盖另一实体的 URL 所有权或用户投递记录；保留原文并报告质量错误。
                    raise ValueError('官方链接已属于另一实体，需要人工审查')
            params = dict(key=canonical,kind=item.kind,title=item.title,country=item.country,city=item.city,
                company_type=item.company_type,category=item.categories[0] if item.categories else None,
                employment_type=item.employment_type,education=item.education,graduation_year=item.graduation_year,
                deadline=item.deadline,published_at=item.published_at,payload=dump(payload),hash=new_hash,demo=item.is_demo,company=None)
            if item.company:
                params['company'] = execute(conn,'''INSERT INTO companies(name,company_type) VALUES (:name,:type)
                    ON CONFLICT(name) DO UPDATE SET company_type=CASE WHEN excluded.company_type='unknown' THEN companies.company_type ELSE excluded.company_type END RETURNING id''',name=item.company,type=item.company_type).scalar_one()
            if old is None:
                item_id = execute(conn,'''INSERT INTO items(canonical_key,kind,title,company_id,country,city,company_type,category,employment_type,education,graduation_year,deadline,published_at,payload,content_hash,is_demo)
                    VALUES (:key,:kind,:title,:company,:country,:city,:company_type,:category,:employment_type,:education,:graduation_year,:deadline,:published_at,CAST(:payload AS jsonb),:hash,:demo) RETURNING id''',**params).scalar_one()
                version, outcome, changed = 1,'inserted',list(payload)
            elif old['content_hash'] == new_hash:
                item_id, version, outcome, changed = old['id'],old['version'],'deduplicated',[]
            else:
                item_id, version, outcome = old['id'],old['version']+1,'updated'
                # 字段删除也是内容变化；仅比较新字段会递增版本却漏写快照。
                changed = [k for k in sorted(old['payload'].keys() | payload.keys())
                           if k not in old['payload'] or k not in payload or payload[k] != old['payload'][k]]
                execute(conn,'''UPDATE items SET title=:title,company_id=:company,country=:country,city=:city,company_type=:company_type,
                    category=:category,employment_type=:employment_type,education=:education,graduation_year=:graduation_year,
                    deadline=:deadline,published_at=:published_at,payload=CAST(:payload AS jsonb),content_hash=:hash,version=:version,updated_at=now() WHERE id=:id''',**params,version=version,id=item_id)
            execute(conn,'INSERT INTO canonical_aliases(canonical_key,item_id) VALUES (:key,:id) ON CONFLICT DO NOTHING',key=canonical,id=item_id)
            execute(conn,'''INSERT INTO item_sources(source_id,external_id,item_id,url,raw_id) VALUES (:source,:ext,:item,:url,:raw)
                ON CONFLICT(source_id,external_id) DO UPDATE SET url=excluded.url,raw_id=excluded.raw_id''',source=source['id'],ext=external_id,item=item_id,url=item.url,raw=raw_id)
            if changed:
                execute(conn,'''INSERT INTO item_versions(item_id,version,payload,changed_fields,raw_id)
                    VALUES (:id,:v,CAST(:payload AS jsonb),CAST(:changed AS jsonb),:raw)''',id=item_id,v=version,payload=dump(payload),changed=dump(changed),raw=raw_id)
                execute(conn,'DELETE FROM job_skills WHERE item_id=:id',id=item_id)
                for skill in item.skills:
                    execute(conn,'''INSERT INTO job_skills(item_id,skill,requirement,evidence) VALUES (:id,:skill,:req,:evidence)
                        ON CONFLICT(item_id,skill) DO NOTHING''',id=item_id,skill=skill.name,req=skill.requirement,evidence=skill.evidence)
                # 同一原文的重新解析仍保存内容版本，但不冒充来源发生变化。
                previous_raw = execute(conn,'SELECT raw_id FROM item_versions WHERE item_id=:id AND version=:v',id=item_id,v=version-1).scalar() if outcome == 'updated' else None
                if outcome == 'updated' and previous_raw != raw_id:
                    execute(conn,'''INSERT INTO alerts(item_id,dedup_key,message) VALUES (:id,:key,:msg) ON CONFLICT DO NOTHING''',id=item_id,key=f'change:{item_id}:{version}',msg=f'{item.title} 更新：'+', '.join(changed))
                # 同名同企业仅作为低置信度候选，不自动合并。
                execute(conn,'''INSERT INTO duplicate_candidates(item_a,item_b,reason,confidence)
                    SELECT least(id,:id),greatest(id,:id),'同标题、企业和城市；需人工审查',0.65 FROM items
                    WHERE id<>:id AND title=:title AND company_id=:company AND city IS NOT DISTINCT FROM :city AND is_demo=:demo AND kind=:kind
                    ON CONFLICT DO NOTHING''',id=item_id,**params)
            return outcome,item_id

    def run(self, source_id: int, records: Iterable[Any] | None = None, *,
            force: bool = False, refresh_source: bool = True) -> dict[str, Any]:
        if not refresh_source and records is None:
            raise ValueError('离线重解析必须显式提供存档记录')
        source = self.source(source_id)
        mode='archive_reparse' if not refresh_source else 'collect' if records is None else 'import'
        with self._write() as conn:
            run_id = execute(conn,'INSERT INTO collection_runs(source_id,mode) VALUES (:id,:mode) RETURNING id',id=source_id,mode=mode).scalar_one()
        counters = dict(collected=0,parsed=0,failed=0,deduplicated=0,updated=0,inserted=0)
        # 导入完成后可直接打开已保存实体；去重和部分失败也保留成功项。
        # 仅手动导入返回，限制预览大小，不把采集/重解析结果变成长列表。
        import_items = {} if mode == 'import' and source['adapter'] == 'manual' else None
        errors, state, response, not_modified, retryable = [],'success',None,False,False
        stage = 'fetch' if records is None else 'ingest'
        traces = []
        owned_fetcher = None
        try:
            if records is None:
                if not source['enabled']: raise ValueError('数据源已禁用')
                headers = {'User-Agent':'SignalHub/0.1 public-read-only'}
                if source['etag'] and not force: headers['If-None-Match'] = source['etag']
                if source['last_modified'] and not force: headers['If-Modified-Since'] = source['last_modified']
                fetcher = self.fetcher
                if fetcher is None:
                    owned_fetcher = fetcher = Fetcher()
                records,response,not_modified = ADAPTERS[source['adapter']]().fetch(source['config'],fetcher,headers)
            stage = 'ingest'
            for raw in records:
                counters['collected'] += 1
                try:
                    result,item_id = self.ingest_one(source,raw)
                    counters['parsed'] += 1
                    counters[result] += 1
                    if import_items is not None:
                        import_items[item_id] = None
                except TaskLeaseLost:
                    raise
                except Exception as exc:
                    counters['failed'] += 1
                    if isinstance(exc,(OperationalError,InterfaceError)):raise
                    issue = {**failure_context(exc, stage=stage), 'record_index': counters['collected'],
                             'details': quality_error(exc)}
                    if len(traces) < 3:
                        traces.append({**failure_context(exc, stage=stage), 'record_index': counters['collected'],
                                       'stack': safe_stack(exc.__traceback__)})
                    if hasattr(exc,'errors'):
                        issue['fields'] = [{'field':str(x['loc']),'reason':x['type']} for x in exc.errors(include_input=False)]
                    errors.append(issue)
            if errors: state = 'partial'
            if not_modified: state = 'not_modified'
        except TaskLeaseLost:
            raise
        except Exception as exc:
            state = 'failed'
            retryable=isinstance(exc,(OperationalError,InterfaceError))
            issue = failure_context(exc, stage=stage)
            errors.append(issue)
            traces.append({**issue, 'stack': safe_stack(exc.__traceback__)})
        finally:
            # Some adapters fetch lazily while the records are being consumed.
            if owned_fetcher is not None:
                owned_fetcher.client.close()
        with self._write() as conn:
            execute(conn,'''UPDATE collection_runs SET state=:state,ended_at=now(),collected=:collected,parsed=:parsed,failed=:failed,
                deduplicated=:deduplicated,updated=:updated,inserted=:inserted,errors=CAST(:errors AS jsonb) WHERE id=:id''',**counters,state=state,errors=dump(errors),id=run_id)
            if refresh_source and state in ('success','not_modified'):
                execute(conn,'''UPDATE sources SET last_success=now(),status=CASE WHEN adapter='manual' THEN status ELSE 'verified' END,
                    etag=coalesce(:etag,etag),last_modified=coalesce(:modified,last_modified) WHERE id=:id''',id=source_id,etag=response.headers.get('etag') if response else None,modified=response.headers.get('last-modified') if response else None)
            elif refresh_source and source['adapter'] != 'manual': execute(conn,"UPDATE sources SET status='unavailable' WHERE id=:id",id=source_id)
        if errors:
            # 每次运行仅一条摘要，最多三份调用位置；不按每条坏记录刷屏。
            log_failure(log, 'collection_failed', source_id=source_id, run_id=run_id,
                        adapter=source['adapter'], mode=mode, state=state,
                        error_count=len(errors), failures=traces[:3])
        result=dict(run_id=run_id,state=state,**counters,errors=errors)
        if import_items is not None:
            result.update(item_ids=list(import_items)[:20],item_count=len(import_items))
        if retryable:result['retryable']=True
        if not refresh_source:result['mode']='archive_reparse'
        return result
