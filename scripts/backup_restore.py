"""本机一致备份及新建 _test 库隔离恢复；没有覆盖、清库或删除入口。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

import psycopg
from psycopg import sql

from local_runtime import ROOT, Runtime, require


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clients():
    directory = Path(os.environ.get('PG_CLIENT_BIN', ROOT / '.tools/pg-client/bin'))
    result = {}
    for name in ('pg_dump', 'pg_restore'):
        program = directory / name
        require(program.is_file() and os.access(program, os.X_OK),
                '缺少PG17客户端；见docs/BACKUP_RESTORE.md，设置PG_CLIENT_BIN')
        version = subprocess.check_output([str(program), '--version'], text=True)
        require(re.search(r'\(PostgreSQL\) 17\.', version), '只使用与本项目PG17匹配的客户端')
        result[name] = str(program)
    return result


def fingerprint(conn):
    """只保存数量/哈希；表内原文、档案及备注不进入公开证据。"""
    conn.execute("SET LOCAL TIME ZONE 'UTC'")
    tables = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    result = {'tables': {}, 'sequences': {}}
    for table in tables:
        rows = [json.dumps(row[0], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                for row in conn.execute(sql.SQL('SELECT row_to_json(t) FROM public.{} t').format(sql.Identifier(table)))]
        result['tables'][table] = {'count': len(rows), 'sha256': hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()}
    for (name,) in conn.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"):
        value, called = conn.execute(sql.SQL('SELECT last_value,is_called FROM public.{}').format(sql.Identifier(name))).fetchone()
        result['sequences'][name] = [value, called]
    constraints = list(conn.execute("SELECT c.relname,p.conname,pg_get_constraintdef(p.oid) FROM pg_constraint p JOIN pg_class c ON c.oid=p.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2"))
    indexes = list(conn.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2"))
    result['schema_sha256'] = hashlib.sha256(json.dumps([constraints, indexes], sort_keys=True).encode()).hexdigest()
    return result


def verify_connection(conn, runtime, database):
    actual, directory, version = conn.execute('SELECT current_database(),current_setting(\'data_directory\'),current_setting(\'server_version_num\')').fetchone()
    require(actual == database and Path(directory).resolve() == runtime.data.resolve() and int(version) // 10000 == 17,
            '数据库名称、目录或PG17身份不符；拒绝操作')


def client_env(runtime):
    # 凭据只放子进程环境，不出现在命令参数、manifest或证据中。
    return {'PATH': os.environ.get('PATH', ''), 'PGPASSWORD': runtime.env['DB_PASSWORD'], 'PGCONNECT_TIMEOUT': '3'}


def backup():
    programs = clients()
    rt = Runtime()
    with rt.lock(), rt.connect() as conn:
        verify_connection(conn, rt, 'signalhub')
        require(not conn.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()').fetchone()[0],
                '先执行signalhub.sh stop并关闭其他正式库连接；停止写入后才能精确核对序列')
        parent = ROOT / '.local/backups'
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent.chmod(0o700)
        folder = parent / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder.mkdir(mode=0o700)
        archive = folder / 'database.dump'
        # pg_dump与行指纹共用同一个导出的MVCC快照。
        conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
        before = fingerprint(conn)
        temporary = folder / 'database.dump.partial'
        temporary.touch(mode=0o600)
        subprocess.run([programs['pg_dump'], '-h', '127.0.0.1', '-p', str(rt.db_port), '-U', rt.env['DB_USER'],
                        '-d', rt.database, '--no-password', '--format=custom', '--compress=0', '--no-owner', '--no-acl',
                        '--snapshot', snapshot, '--file', str(temporary)], env=client_env(rt), check=True, timeout=300)
        conn.execute('COMMIT')
        # 序列不受MVCC保护；有人在备份期间写入则拒绝宣称精确检查点。
        conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        require(fingerprint(conn) == before, '备份期间正式数据有写入；保留partial文件，请停止写入后重试')
        conn.execute('COMMIT')
        temporary.rename(archive)
        manifest = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'database': rt.database,
                    'archive_sha256': digest(archive), 'fingerprint': before, 'scope': 'single database; no cluster roles/configuration'}
        path = folder / 'manifest.json'
        path.touch(mode=0o600)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return {'state': 'backed_up', 'folder': str(folder), 'tables': len(before['tables']), 'bytes': archive.stat().st_size}


def validate_restore_name(name):
    require(bool(re.fullmatch(r'signalhub_restore_[a-z0-9_]{1,32}_test', name or '')),
            '恢复只允许signalhub_restore_<标识>_test；不覆盖任何已有库')


def read_backup(folder):
    folder = folder.resolve()
    require(folder.is_relative_to((ROOT / '.local/backups').resolve()), '只接受本仓库私有.local/backups内的自有备份')
    archive = folder / 'database.dump'
    manifest = json.loads((folder / 'manifest.json').read_text())
    require(manifest.get('format') == 1 and manifest.get('database') == 'signalhub', '备份格式或来源库不符')
    require(digest(archive) == manifest['archive_sha256'], '备份SHA256不符；尚未创建恢复库')
    return archive, manifest


def restore(folder, name):
    validate_restore_name(name)
    archive, manifest = read_backup(folder)
    programs = clients()
    rt = Runtime(test=True)  # 固定独立PG55434；不读取正式.env或启动Worker。
    with rt.lock(), rt.connect('postgres') as admin:
        verify_connection(admin, rt, 'postgres')
        require(not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone(), '恢复目标已存在；拒绝覆盖')
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        subprocess.run([programs['pg_restore'], '-h', '127.0.0.1', '-p', str(rt.db_port), '-U', rt.env['DB_USER'],
                        '-d', name, '--no-password', '--no-owner', '--no-acl', '--exit-on-error', '--single-transaction',
                        str(archive)], env=client_env(rt), check=True, timeout=300)
        # 不启动应用定时器；核对全部表、Flyway、约束、索引和序列后再单独验API。
        with rt.connect(name) as conn:
            verify_connection(conn, rt, name)
            conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            actual = fingerprint(conn)
            require(actual == manifest['fingerprint'], '恢复后完整指纹不符；目标保留供诊断，不修改正式库')
    report = {'state': 'restored_and_verified', 'database': name, 'port': rt.db_port,
              'tables': len(actual['tables']), 'sequences': len(actual['sequences']), 'schema': 'constraints_and_indexes_equal',
              'all_rows': 'equal', 'archive_sha256': manifest['archive_sha256']}
    path = folder / (name + '-verification.json')
    with path.open('x') as output:
        path.chmod(0o600)
        output.write(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('backup')
    target = sub.add_parser('restore')
    target.add_argument('folder', type=Path)
    target.add_argument('--name', required=True)
    args = parser.parse_args()
    result = backup() if args.command == 'backup' else restore(args.folder, args.name)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
