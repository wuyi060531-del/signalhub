"""异常注入使用合成数据和 Mock HTTP，不访问真实来源或付费服务。"""
import json
import logging
import socket

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from signalhub.diagnostics import failure_context, safe_stack, SourceAccessError
from signalhub.pipeline import Pipeline
from signalhub.worker import Worker

SECRET = 'Token=private-test-value password=do-not-log personal@example.com'


def http_error(status):
    request = httpx.Request('GET', 'https://example.com/private?token=secret')
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(SECRET, request=request, response=response)


@pytest.mark.parametrize('exc,category,status', [
    (http_error(404), 'http_not_found', 404),
    (http_error(429), 'http_rate_limited', 429),
    (http_error(403), 'source_access_restricted', 403),
    (http_error(401), 'source_access_restricted', 401),
    (http_error(503), 'http_error', 503),
    (socket.gaierror(SECRET), 'dns_error', None),
    (httpx.ReadTimeout(SECRET), 'network_timeout', None),
    (httpx.ConnectError(SECRET), 'network_error', None),
    (KeyError(SECRET), 'source_format_or_config', None),
    (SourceAccessError(SECRET), 'source_policy_rejected', None),
    (OperationalError(SECRET, {'password': SECRET}, RuntimeError(SECRET)), 'database_error', None),
])
def test_failed_collection_has_safe_persisted_context(db, caplog, exc, category, status):
    with db.begin() as conn:
        source = conn.execute(text("INSERT INTO sources(name,adapter,config,enabled,etag) VALUES ('合成诊断','greenhouse','{\"board\":\"test\"}',true,'old') RETURNING id")).scalar_one()
    class Broken:
        def get(self, *args, **kwargs):
            raise exc
    caplog.set_level(logging.WARNING)
    result = Pipeline(db, Broken()).run(source)
    assert result['state'] == 'failed'
    context = result['errors'][0]
    assert context['category'] == category and context['stage'] == 'fetch'
    assert context.get('http_status') == status
    with db.connect() as conn:
        saved = conn.execute(text('SELECT errors FROM collection_runs')).scalar_one()
        assert saved == result['errors']
        assert conn.execute(text('SELECT etag FROM sources WHERE id=:id'), {'id': source}).scalar_one() == 'old'
    events = [json.loads(r.message) for r in caplog.records if r.name == 'signalhub.pipeline']
    assert len(events) == 1 and events[0]['source_id'] == source and events[0]['run_id'] == result['run_id']
    assert events[0]['failures'][0]['stack']
    combined = json.dumps(saved) + caplog.text
    for value in (SECRET, 'secret', 'personal@example.com', 'private-test-value'):
        assert value not in combined


def test_dns_cause_and_stack_do_not_format_exception_message():
    try:
        try:
            raise socket.gaierror(SECRET)
        except socket.gaierror as exc:
            raise httpx.ConnectError(SECRET) from exc
    except httpx.ConnectError as exc:
        assert failure_context(exc, stage='fetch')['category'] == 'dns_error'
        frames = safe_stack(exc.__traceback__)
    assert frames and SECRET not in json.dumps(frames)


def test_partial_batch_logs_once_and_keeps_valid_rows(db, caplog):
    raw = {'kind': 'job', 'title': '合成 Java 实习', 'external_id': 'synthetic',
           'body': 'Java', 'is_demo': True}
    result = Pipeline(db).run(1, [None] * 30 + [raw])
    assert result['state'] == 'partial' and result['inserted'] == 1 and result['failed'] == 30
    assert result['errors'][0]['category'] == 'record_validation'
    events = [json.loads(r.message) for r in caplog.records if r.name == 'signalhub.pipeline']
    assert len(events) == 1 and len(events[0]['failures']) == 3
    assert events[0]['error_count'] == 30


def test_worker_failure_context_is_safe_and_attempts_remain_bounded(db, monkeypatch, caplog):
    with db.begin() as conn:
        conn.execute(text("INSERT INTO task_requests(task_type,source_id,payload) VALUES ('import',1,'{\"records\":[]}'::jsonb)"))
    def broken(*args, **kwargs):
        raise OperationalError(SECRET, {'password': SECRET}, RuntimeError(SECRET))
    monkeypatch.setattr(Pipeline, 'run', broken)
    for _ in range(3):
        assert Worker(db).tick()['category'] == 'database_error'
    assert Worker(db).tick() is None
    with db.connect() as conn:
        task = conn.execute(text('SELECT state,attempts,error FROM task_requests')).mappings().one()
        assert task['state'] == 'failed' and task['attempts'] == 3
        assert json.loads(task['error'])['category'] == 'database_error'
    assert SECRET not in caplog.text
    assert len([r for r in caplog.records if r.name == 'signalhub.worker']) == 3


def test_queue_database_outage_is_safe_rate_limited_and_recovers(db, monkeypatch, caplog):
    worker = Worker(db)
    tick = worker._tick
    def broken():
        raise OperationalError(SECRET, {'password': SECRET}, RuntimeError(SECRET))
    monkeypatch.setattr(worker, '_tick', broken)
    for _ in range(5):
        assert worker.tick()['stage'] == 'task_queue'
    assert len([r for r in caplog.records if r.name == 'signalhub.worker']) == 1
    monkeypatch.setattr(worker, '_tick', tick)
    assert worker.tick() is None
    monkeypatch.setattr(worker, '_tick', broken)
    assert worker.tick()['category'] == 'database_error'
    assert len([r for r in caplog.records if r.name == 'signalhub.worker']) == 2
    assert SECRET not in caplog.text
