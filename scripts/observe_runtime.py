"""手动、只读、有界的本机运行观察；不启动服务、不阻止睡眠、不配置后台。"""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
from zoneinfo import ZoneInfo

from local_runtime import ROOT, Runtime, require

MAX_BYTES = 16 * 1024 * 1024
MAX_HOURS = 72
WATCHED_TABLES = ('items', 'task_requests', 'collection_runs', 'match_results', 'alerts',
                  'reading_translation_jobs', 'translation_runtime')
LOG_NAMES = ('backend.log', 'worker.log', 'postgres.log', 'build.log')
LOG_WARN_BYTES = 50 * 1024 * 1024
DISK_WARN_BYTES = 512 * 1024 * 1024


def validate_options(hours, interval):
    require(math.isfinite(hours) and 0 <= hours <= MAX_HOURS, '观察时长必须为0–72小时；0表示单次')
    require(60 <= interval <= 3600, '采样间隔必须为60–3600秒，建议300秒')


def error_kind(exc):
    # 异常可能包含连接串、原文或本机配置；只保存固定类型名。
    return type(exc).__name__


def snapshot(runtime):
    result = dict(captured_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                  database=runtime.database, services={}, issues=[], warnings=[])
    try:
        state = runtime.read_state()
        for name in ('backend', 'worker'):
            alive = runtime.alive(state.get(name))
            result['services'][name] = {'managed_and_alive': alive}
            if not alive:
                result['issues'].append(name + '_not_managed_or_stopped')
            else:
                pid = state[name]['pid']
                raw = subprocess.check_output(['ps', '-p', str(pid), '-o', 'rss='], text=True, timeout=3)
                result['services'][name].update(pid=pid, rss_kib=int(raw.strip()))
        result['services']['postgres'] = {'running': runtime.pg_running()}
        if not result['services']['postgres']['running']:
            result['issues'].append('postgres_stopped')
        health = runtime.health()
        require(health.get('database') == runtime.database and health.get('pid') == state.get('backend', {}).get('pid')
                and result['services']['backend']['managed_and_alive'] and health.get('status') == 'ok',
                '健康端点与受管实例身份不符')
        result['health_verified'] = True
    except Exception as exc:
        result['health_verified'] = False
        result['issues'].append('runtime_' + error_kind(exc))
    # 每个样本至多一个短连接；先开启READ ONLY，再核对真实DB/目录身份。
    try:
        with runtime.connect() as conn:
            conn.execute('BEGIN READ ONLY')
            conn.execute("SET LOCAL statement_timeout='2000ms'")
            conn.execute("SET LOCAL lock_timeout='500ms'")
            actual, directory, version = conn.execute(
                "SELECT current_database(),current_setting('data_directory'),current_setting('server_version_num')").fetchone()
            require(actual == runtime.database and Path(directory).resolve() == runtime.data.resolve()
                    and int(version) // 10000 == 17, '数据库身份不符')
            result['database_verified'] = True
            result['queue'] = {state: count for state, count in conn.execute(
                'SELECT state,count(*) FROM task_requests GROUP BY state')}
            ages = conn.execute("SELECT max(CASE WHEN state='pending' THEN extract(epoch FROM now()-created_at) END),max(CASE WHEN state='running' THEN extract(epoch FROM now()-started_at) END) FROM task_requests").fetchone()
            result['oldest_task_age_seconds'] = {name: float(value) if value is not None else None
                                                 for name, value in zip(('pending', 'running'), ages)}
            heartbeat = conn.execute("SELECT available,extract(epoch FROM now()-updated_at) FROM translation_runtime WHERE id=1").fetchone()
            result['translation_runtime'] = ({'available': heartbeat[0], 'heartbeat_age_seconds': float(heartbeat[1])}
                                             if heartbeat else None)
            if result['oldest_task_age_seconds']['pending'] is not None and result['oldest_task_age_seconds']['pending'] > 900:
                result['warnings'].append('pending_task_older_than_900s')
            if heartbeat and heartbeat[0] and float(heartbeat[1]) > 300:
                # 长采集也可能暂时挡住翻译tick；只提示排查，不直接判断Worker故障。
                result['warnings'].append('translation_heartbeat_older_than_300s')
            result['translations'] = {state: count for state, count in conn.execute(
                'SELECT state,count(*) FROM reading_translation_jobs GROUP BY state')}
            result['stale_running_tasks'] = conn.execute(
                "SELECT count(*) FROM task_requests WHERE state='running' AND started_at<now()-interval '15 minutes'").fetchone()[0]
            result['connections'] = conn.execute(
                'SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()').fetchone()[0]
            result['table_writes'] = {row[0]: dict(inserted=row[1], updated=row[2], deleted=row[3], live_estimate=row[4], dead_estimate=row[5])
                for row in conn.execute('SELECT relname,n_tup_ins,n_tup_upd,n_tup_del,n_live_tup,n_dead_tup FROM pg_stat_user_tables WHERE relname=ANY(%s)', (list(WATCHED_TABLES),))}
            result['statistics_reset_at'] = str(conn.execute(
                'SELECT stats_reset FROM pg_stat_database WHERE datname=current_database()').fetchone()[0])
            if result['stale_running_tasks']:
                result['issues'].append('task_lease_expired')
            conn.execute('ROLLBACK')
    except Exception as exc:
        result['database_verified'] = False
        result['issues'].append('database_' + error_kind(exc))
    # 只stat四个已知日志文件，不读取内容，不递归PG目录或全磁盘。
    result['log_bytes'] = {}
    for name in LOG_NAMES:
        try:
            path = runtime.home / name
            result['log_bytes'][name] = path.stat().st_size if path.is_file() and not path.is_symlink() else None
        except OSError:
            result['log_bytes'][name] = None
    for name, size in result['log_bytes'].items():
        if size is not None and size > LOG_WARN_BYTES:
            result['warnings'].append(name + '_over_50MiB')
    try:
        result['disk_free_bytes'] = shutil.disk_usage(ROOT).free
        if result['disk_free_bytes'] < DISK_WARN_BYTES:
            result['warnings'].append('disk_free_below_512MiB')
    except OSError as exc:
        result['issues'].append('disk_' + error_kind(exc))
    result['ok'] = result.get('health_verified', False) and result.get('database_verified', False) and not result['issues']
    return result


def summarize(rows):
    require(rows and rows[0].get('type') == 'start', '观察记录缺少起点')
    config = rows[0]
    samples = [row for row in rows if row.get('type') == 'sample']
    span = 0 if len(samples) < 2 else max(0, samples[-1]['elapsed_seconds'] - samples[0]['elapsed_seconds'])
    gaps = [row['gap_seconds'] for row in samples[1:] if row.get('gap_seconds', 0) > config['interval_seconds'] * 1.5]
    active_values = [row.get('active_elapsed_seconds') for row in samples]
    active_known = (len(active_values) >= 2 and all(isinstance(value, (int, float)) and math.isfinite(value)
                                                  for value in active_values))
    active_span = max(0, active_values[-1] - active_values[0]) if active_known else None
    active_ordered = active_known and all(b >= a for a, b in zip(active_values, active_values[1:]))
    failures = sum(not row.get('ok', False) for row in samples)
    # 总跨度不等于连续有效证据；睡眠/停止服务/缺样/时间异常均不得获得通过结论。
    completed = any(row.get('type') == 'end' and row.get('reason') == 'duration_complete' for row in rows)
    continuous_72h = (config['duration_hours'] == 72 and completed and span >= 72 * 3600 - 1
                      and active_ordered and active_span >= 72 * 3600 - 1 and not gaps and failures == 0 and len(samples) >= 2)
    first, last = (samples[0], samples[-1]) if samples else ({}, {})
    reset = first.get('statistics_reset_at') != last.get('statistics_reset_at')
    write_growth = {}
    if not reset:
        for name in WATCHED_TABLES:
            a, b = first.get('table_writes', {}).get(name), last.get('table_writes', {}).get(name)
            if a and b:
                delta = {key: b[key] - a[key] for key in ('inserted', 'updated', 'deleted')}
                if any(value < 0 for value in delta.values()):
                    reset = True
                write_growth[name] = delta
    warned = sum(bool(row.get('warnings')) for row in samples)
    rss_ranges = {}
    for name in ('backend', 'worker'):
        values = [r['services'][name]['rss_kib'] for r in samples
                  if r.get('services', {}).get(name, {}).get('rss_kib') is not None]
        if values:
            rss_ranges[name] = dict(min=min(values), max=max(values))
    log_growth = {name: (last['log_bytes'][name] - first['log_bytes'][name])
                  for name in LOG_NAMES if isinstance(first.get('log_bytes', {}).get(name), int)
                  and isinstance(last.get('log_bytes', {}).get(name), int)}
    return dict(samples=len(samples), span_hours=round(span / 3600, 6),
                active_span_hours=round(active_span / 3600, 6) if active_span is not None else None,
                configured_hours=config['duration_hours'],
                interval_seconds=config['interval_seconds'], unhealthy_samples=failures,
                gap_count=len(gaps), largest_gap_seconds=max(gaps, default=0),
                ended_cleanly=any(row.get('type') == 'end' for row in rows),
                continuous_72h_evidence=continuous_72h and not warned, warning_samples=warned,
                log_growth_bytes=log_growth, rss_range_kib=rss_ranges,
                statistics_reset_or_counter_decrease=reset, table_write_growth=None if reset else write_growth,
                note='仅为有界抽样证据；不等于无故障保证。睡眠或缺样不计连续通过。')


def new_run():
    parent = ROOT / '.local' / 'observations'
    require(not parent.is_symlink(), '观察目录不能为符号链接')
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent.chmod(0o700)
    folder = parent / (datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    return folder


def append_row(path, row):
    encoded = (json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    require(not path.is_symlink() and (path.stat().st_size if path.exists() else 0) + len(encoded) <= MAX_BYTES,
            '观察记录达到16MiB上限或路径不安全；已停止，不影响业务服务')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'ab') as stream:
        stream.write(encoded)


def read_rows(path):
    path = Path(path)
    parent = ROOT / '.local' / 'observations'
    require(not path.is_symlink() and path.resolve().is_relative_to(parent.resolve()) and path.name == 'samples.jsonl',
            '只读取本仓库私有观察目录的samples.jsonl')
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, '记录不存在或超过16MiB上限')
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def observe(runtime, hours, interval):
    validate_options(hours, interval)
    folder = new_run()
    path = folder / 'samples.jsonl'
    rows = []
    def save(row):
        append_row(path, row)
        rows.append(row)
    save(dict(type='start', duration_hours=hours, interval_seconds=interval,
              started_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), read_only=True))
    print('只读观察记录：' + str(path), flush=True)
    print('前台运行；Ctrl-C停止观察，不停止SignalHub，不阻止睡眠。', flush=True)
    started = time.monotonic()
    started_wall = time.time()
    previous_wall = None
    reason = 'single_snapshot' if hours == 0 else 'duration_complete'
    try:
        while True:
            now = time.time()
            row = snapshot(runtime)
            row.update(type='sample', elapsed_seconds=round(now - started_wall, 3),
                       active_elapsed_seconds=round(time.monotonic() - started, 3),
                       gap_seconds=0 if previous_wall is None else round(now - previous_wall, 3))
            if previous_wall is not None and now < previous_wall:
                row['ok'] = False
                row['issues'].append('wall_clock_moved_backwards')
            save(row)
            previous_wall = now
            print(f"{row['captured_at']} {'ok' if row['ok'] else '需检查'}", flush=True)
            # macOS休眠可能不计入monotonic；同时限定墙钟，不补跑睡眠丢失的样本。
            remaining = min(hours * 3600 - (time.monotonic() - started),
                            hours * 3600 - (time.time() - started_wall))
            if hours == 0 or remaining <= 0:
                break
            time.sleep(min(interval, remaining))
    except KeyboardInterrupt:
        reason = 'interrupted_by_user'
    except Exception:
        reason = 'observation_error'
        raise
    finally:
        try:
            save(dict(type='end', reason=reason))
        except RuntimeError:
            # 满额时不覆盖或截断已记录样本；summary会保留未正常结束状态。
            pass
        summary = summarize(rows)
        summary_path = folder / 'summary.json'
        with os.fdopen(os.open(summary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration-hours', type=float, default=0, help='0为单次，显式正数才持续观察，最多72小时；支持小数短检')
    parser.add_argument('--interval-seconds', type=int, default=300, help='60–3600，默认300；不自动配置后台')
    parser.add_argument('--report', type=Path, help='只读汇总已有samples.jsonl，不连接数据库')
    args = parser.parse_args()
    try:
        if args.report:
            print(json.dumps(summarize(read_rows(args.report)), ensure_ascii=False, indent=2))
            return 0
        summary = observe(Runtime(), args.duration_hours, args.interval_seconds)
        return 0 if not summary['unhealthy_samples'] else 1
    except Exception as exc:
        print('SignalHub观察未完成：' + (str(exc) if isinstance(exc, RuntimeError) else error_kind(exc)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
