"""只读观察护栏；假连接/假时钟，不访问真实数据库、不启动或停止服务。"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('observe_runtime', ROOT / 'scripts/observe_runtime.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def test_observation_is_finite_and_rejects_invalid_intervals():
    observer.validate_options(0, 300)
    observer.validate_options(72, 60)
    for hours, interval in [(73, 300), (-1, 300), (float('nan'), 300), (float('inf'), 300), (1, 59), (1, 3601)]:
        with pytest.raises(RuntimeError):
            observer.validate_options(hours, interval)


def samples(hours=72):
    start = dict(type='start', duration_hours=hours, interval_seconds=3600)
    rows = [start]
    for n in range(73):
        rows.append(dict(type='sample', elapsed_seconds=n*3600, active_elapsed_seconds=n*3600, gap_seconds=0 if n == 0 else 3600,
                         ok=True, issues=[], warnings=[], log_bytes={'worker.log': n*10}))
    return rows + [dict(type='end', reason='duration_complete')]


def test_short_or_interrupted_and_sleep_gaps_never_count_as_continuous_72h():
    full = samples()
    assert observer.summarize(full)['continuous_72h_evidence'] is True
    for alter in ('short', 'interrupted', 'gap', 'failure', 'warning', 'no_end', 'active_short', 'missing_active'):
        rows = json.loads(json.dumps(full))
        if alter == 'short': rows[0]['duration_hours'] = 1
        if alter == 'interrupted': rows[-1]['reason'] = 'interrupted_by_user'
        if alter == 'gap': rows[30]['gap_seconds'] = 7200
        if alter == 'failure': rows[30]['ok'] = False
        if alter == 'warning': rows[30]['warnings'] = ['disk_free_below_512MiB']
        if alter == 'no_end': rows.pop()
        if alter == 'active_short': rows[-2]['active_elapsed_seconds'] = 71*3600
        if alter == 'missing_active': rows[30].pop('active_elapsed_seconds')
        assert observer.summarize(rows)['continuous_72h_evidence'] is False, alter


def test_counter_reset_is_not_reported_as_negative_business_writes():
    rows = samples()
    rows[1]['statistics_reset_at'] = rows[-2]['statistics_reset_at'] = 'same'
    rows[1]['table_writes'] = {'match_results': {'inserted': 1, 'updated': 5, 'deleted': 0}}
    rows[-2]['table_writes'] = {'match_results': {'inserted': 1, 'updated': 4, 'deleted': 0}}
    summary = observer.summarize(rows)
    assert summary['statistics_reset_or_counter_decrease'] is True and summary['table_write_growth'] is None
    rows[-2]['table_writes']['match_results']['updated'] = 7
    assert observer.summarize(rows)['table_write_growth']['match_results']['updated'] == 2


def test_private_outputs_are_bounded_and_symlinks_cannot_overwrite_files(tmp_path, monkeypatch):
    monkeypatch.setattr(observer, 'ROOT', tmp_path)
    folder = observer.new_run()
    path = folder / 'samples.jsonl'
    observer.append_row(path, {'type': 'start'})
    assert folder.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert observer.read_rows(path) == [{'type': 'start'}]
    monkeypatch.setattr(observer, 'MAX_BYTES', path.stat().st_size + 1)
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match='上限'):
        observer.append_row(path, {'too_large': 'x'*100})
    assert path.read_bytes() == original
    with pytest.raises(RuntimeError, match='上限'):
        observer.append_row(folder / 'oversize.jsonl', {'too_large': 'x'*100})
    outside = tmp_path / 'keep.json'
    outside.write_text('private value')
    link = folder / 'link.jsonl'
    link.symlink_to(outside)
    with pytest.raises(RuntimeError): observer.append_row(link, {'overwrite': True})
    with pytest.raises(RuntimeError): observer.read_rows(outside)
    assert outside.read_text() == 'private value'


class Cursor:
    def __init__(self, rows): self.rows = rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def __iter__(self): return iter(self.rows)


class Connection:
    def __init__(self, directory, wrong_database=False, pending_age=None, heartbeat_age=10, available=True):
        self.directory, self.wrong_database, self.queries = directory, wrong_database, []
        self.pending_age, self.heartbeat_age, self.available = pending_age, heartbeat_age, available
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, query, params=None):
        self.queries.append(query)
        if query.startswith('SELECT current_database()'):
            return Cursor([('other' if self.wrong_database else 'signalhub', str(self.directory), '170006')])
        if 'GROUP BY state' in query: return Cursor([('done', 2)])
        if 'max(CASE' in query: return Cursor([(self.pending_age, 12)])
        if query.startswith('SELECT available'): return Cursor([(self.available, self.heartbeat_age)])
        if 'pg_stat_user_tables' in query: return Cursor([('match_results', 0, 0, 0, 1, 0)])
        if 'stats_reset' in query: return Cursor([(None,)])
        if 'pg_stat_activity' in query: return Cursor([(3,)])
        if query.startswith('SELECT count(*)'): return Cursor([(0,)])
        return Cursor([])


def fake_runtime(tmp_path, connection):
    home = tmp_path / 'runtime'
    home.mkdir()
    return SimpleNamespace(database='signalhub', data=tmp_path / 'pgdata', home=home,
        read_state=lambda: {'backend': {'pid': 11}, 'worker': {'pid': 12}},
        alive=lambda record: True, pg_running=lambda: True,
        health=lambda: {'database': 'signalhub', 'pid': 11, 'status': 'ok'}, connect=lambda: connection)


def test_snapshot_database_is_read_only_and_contains_only_aggregate_diagnostics(tmp_path, monkeypatch):
    connection = Connection(tmp_path / 'pgdata')
    runtime = fake_runtime(tmp_path, connection)
    monkeypatch.setattr(observer.subprocess, 'check_output', lambda *a, **kw: '123')
    result = observer.snapshot(runtime)
    assert result['ok'] is True and result['health_verified'] and result['database_verified']
    assert connection.queries[0] == 'BEGIN READ ONLY' and connection.queries[-1] == 'ROLLBACK'
    assert all(q.split()[0] in {'BEGIN', 'SET', 'SELECT', 'ROLLBACK'} for q in connection.queries)
    assert not any('user_profiles' in q or 'payload' in q or 'job_applications' in q for q in connection.queries)
    assert result['oldest_task_age_seconds'] == {'pending': None, 'running': 12.0}
    assert result['translation_runtime']['heartbeat_age_seconds'] == 10.0
    assert result['table_writes']['match_results']['updated'] == 0


def test_wrong_database_identity_stops_before_business_table_queries_and_errors_do_not_leak(tmp_path, monkeypatch):
    connection = Connection(tmp_path / 'pgdata', wrong_database=True)
    runtime = fake_runtime(tmp_path, connection)
    monkeypatch.setattr(observer.subprocess, 'check_output', lambda *a, **kw: '123')
    result = observer.snapshot(runtime)
    assert result['ok'] is False and result['database_verified'] is False
    assert not any('task_requests' in q for q in connection.queries)
    def fail(): raise ValueError('postgresql://private:secret@example.com/secret')
    runtime.connect = fail
    result = observer.snapshot(runtime)
    assert result['issues'] == ['database_ValueError']
    assert 'secret' not in json.dumps(result)


def test_ctrl_c_stops_only_the_observer_and_writes_incomplete_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(observer, 'ROOT', tmp_path)
    monkeypatch.setattr(observer, 'snapshot', lambda runtime: dict(captured_at='synthetic', ok=True, issues=[], warnings=[], log_bytes={}))
    def interrupt(seconds): raise KeyboardInterrupt
    monkeypatch.setattr(observer.time, 'sleep', interrupt)
    summary = observer.observe(object(), 72, 300)
    assert summary['samples'] == 1 and summary['continuous_72h_evidence'] is False
    path = next((tmp_path / '.local/observations').glob('*/samples.jsonl'))
    assert observer.read_rows(path)[-1]['reason'] == 'interrupted_by_user'


def test_sleep_does_not_extend_wall_deadline_or_replay_missed_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(observer, 'ROOT', tmp_path)
    monkeypatch.setattr(observer, 'snapshot', lambda runtime: dict(captured_at='synthetic', ok=True, issues=[], warnings=[], log_bytes={}))
    clock = {'wall': 0, 'active': 0, 'sleeps': 0}
    monkeypatch.setattr(observer.time, 'time', lambda: clock['wall'])
    monkeypatch.setattr(observer.time, 'monotonic', lambda: clock['active'])
    def slept(seconds):
        clock.update(wall=7200, active=60, sleeps=clock['sleeps'] + 1)
    monkeypatch.setattr(observer.time, 'sleep', slept)
    summary = observer.observe(object(), 1, 300)
    assert clock['sleeps'] == 1 and summary['samples'] == 2
    assert summary['gap_count'] == 1 and summary['continuous_72h_evidence'] is False


def test_old_pending_and_available_translation_heartbeat_warn_without_claiming_a_fault(tmp_path, monkeypatch):
    monkeypatch.setattr(observer.subprocess, 'check_output', lambda *a, **kw: '123')
    for n, (pending, age, available, expected) in enumerate([
        (901, 301, True, ['pending_task_older_than_900s', 'translation_heartbeat_older_than_300s']),
        (900, 300, True, []),
        (None, 1000, False, []),
    ]):
        folder = tmp_path / str(n)
        folder.mkdir()
        connection = Connection(folder / 'pgdata', pending_age=pending, heartbeat_age=age, available=available)
        result = observer.snapshot(fake_runtime(folder, connection))
        assert result['warnings'] == expected and result['ok'] is True and result['issues'] == []
