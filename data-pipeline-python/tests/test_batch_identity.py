import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from httpx import ReadTimeout
from sqlalchemy import text

from signalhub.pipeline import Pipeline
from signalhub.worker import Worker


A = dict(kind='job', external_id='synthetic-batch-key', title='[合成] 数据工程实习 A',
         body='要求 Python', url='https://example.com/synthetic/batch-key', is_demo=True)
B = {**A, 'title': '[合成] 数据工程实习 B', 'body': '要求 SQL'}
OTHER = {**A, 'external_id': 'synthetic-other', 'url': 'https://example.com/synthetic/other'}


def item_state(db):
    with db.connect() as conn:
        return conn.execute(text("""
            SELECT i.title, i.version, s.raw_id,
                   (SELECT count(*) FROM item_versions v WHERE v.item_id=i.id),
                   (SELECT count(*) FROM alerts a WHERE a.item_id=i.id)
            FROM item_sources s JOIN items i ON i.id=s.item_id
            WHERE s.source_id=1 AND s.external_id=:key
        """), {'key': A['external_id']}).one_or_none()


def submit_import(db, records):
    with db.begin() as conn:
        return conn.execute(text("""
            INSERT INTO task_requests(task_type,source_id,payload)
            VALUES ('import',1,CAST(:payload AS jsonb)) RETURNING id
        """), {'payload': json.dumps({'records': records})}).scalar_one()


@pytest.mark.parametrize('existing', [False, True], ids=['new-key', 'existing-key'])
def test_conflicting_key_replay_and_reverse_never_publish_a_winner(db, existing):
    pipeline = Pipeline(db)
    if existing:
        assert pipeline.run(1, [A])['inserted'] == 1
        assert pipeline.run(1, [B])['updated'] == 1
    before = item_state(db)

    observed = []
    for rows in ([A, OTHER, B], [A, OTHER, B], [A, OTHER, B], [B, OTHER, A]):
        task_id = submit_import(db, rows)
        result = Worker(db).tick()
        with db.connect() as conn:
            state, attempts, stored = conn.execute(text(
                'SELECT state,attempts,result FROM task_requests WHERE id=:id'
            ), {'id': task_id}).one()
            raw = dict(conn.execute(text("""
                SELECT id, body->>'title' FROM raw_records WHERE source_id=1 AND external_id=:key
            """), {'key': A['external_id']}).all())
        current = item_state(db)
        observed.append((current, state, attempts, result, stored, raw))

    assert all(current == before for current, *_ in observed), [
        (current, state, result['updated']) for current, state, _, result, _, _ in observed
    ]
    for index, (_, state, attempts, result, stored, raw) in enumerate(observed):
        assert (state, attempts, stored) == ('failed', 1, result)
        assert (result['state'], result['collected'], result['parsed'], result['failed']) == ('partial', 3, 1, 2)
        assert result['updated'] == 0 and not result.get('retryable')
        assert result['item_count'] == 1 and len(result['item_ids']) == 1
        assert result['inserted'] == (index == 0)
        assert result['deduplicated'] == (index != 0)
        assert sorted(raw.values()) == sorted([A['title'], B['title']])
        assert [error['record_index'] for error in result['errors']] == [1, 3]
        assert {error['raw_id'] for error in result['errors']} == set(raw)
        assert all(error['error'] == 'BatchExternalIdConflict' and
                   error['details'][0]['field'] == 'external_id' for error in result['errors'])
        assert A['title'] not in json.dumps(result['errors'], ensure_ascii=False)

    corrected = pipeline.run(1, [A])
    assert corrected['updated' if existing else 'inserted'] == 1
    assert item_state(db)[3:] == ((3, 2) if existing else (1, 0))


def test_same_normalized_content_deduplicates_and_later_batch_can_update(db):
    pipeline = Pipeline(db)
    same = {**A, 'url': A['url'] + '?utm_source=synthetic', '_raw': {'source_metadata': 'synthetic'}}
    first = pipeline.run(1, [A, same, same])
    assert first['state'] == 'success' and first['inserted'] == 1 and first['deduplicated'] == 2
    with db.connect() as conn:
        latest_raw = conn.execute(text(
            "SELECT id FROM raw_records WHERE body->>'source_metadata'='synthetic'"
        )).scalar_one()
    assert item_state(db)[1:] == (1, latest_raw, 1, 0)
    assert pipeline.run(1, [B])['updated'] == 1
    after_update = item_state(db)
    assert after_update[0:2] == (B['title'], 2) and after_update[3:] == (2, 1)
    repeat = pipeline.run(1, [B, B])
    assert repeat['deduplicated'] == 2 and item_state(db) == after_update


def test_invalid_contender_cannot_pick_a_valid_winner_for_same_key(db):
    bad = {**B, 'days_per_week': 9}
    result = Pipeline(db).run(1, [A, bad])
    assert (result['state'], result['parsed'], result['failed']) == ('partial', 0, 2)
    assert item_state(db) is None
    assert [error['record_index'] for error in result['errors']] == [1, 2]
    assert result['errors'][0]['error'] == 'BatchExternalIdConflict'
    assert result['errors'][1]['error'] == 'ValidationError'


def test_concurrent_conflicting_batches_cannot_write_canonical_state(db):
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(Pipeline(db).run, 1, [A, B])
        reverse = pool.submit(Pipeline(db).run, 1, [B, A])
        results = [first.result(timeout=10), reverse.result(timeout=10)]
    assert [result['state'] for result in results] == ['partial', 'partial']
    assert [result['failed'] for result in results] == [2, 2]
    assert item_state(db) is None
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM raw_records')).scalar_one() == 2
        for table in ('items', 'item_sources', 'item_versions', 'alerts'):
            assert conn.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() == 0


def test_failed_stream_keeps_raw_evidence_and_non_conflicting_prefix(db):
    def rows():
        yield A
        yield OTHER
        yield B
        raise ReadTimeout('synthetic late fetch failure')

    result = Pipeline(db).run(1, rows())
    assert (result['state'], result['collected'], result['parsed'], result['failed']) == ('failed', 3, 1, 2)
    assert [error['error'] for error in result['errors']] == ['BatchExternalIdConflict', 'BatchExternalIdConflict', 'ReadTimeout']
    assert item_state(db) is None
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM raw_records')).scalar_one() == 3
        assert conn.execute(text('SELECT external_id FROM item_sources')).scalar_one() == OTHER['external_id']
