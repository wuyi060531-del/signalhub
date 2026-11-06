"""Build a disposable, synthetic SignalHub demo on this computer."""
import argparse
from contextlib import contextmanager
from datetime import date
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import psycopg
from psycopg import sql
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
DATABASE, PG_PORT, WEB_PORT = 'signalhub_demo_test', 55435, 18085


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def tool(name, directory):
    candidate = directory / name
    path = str(candidate.resolve()) if os.access(candidate, os.X_OK) else shutil.which(name)
    require(path, f'缺少 {name}；请先安装 README 指定版本')
    return path


def isolated_env():
    # Do not load .env, PG*, Java options, Spring overrides, proxies, or credentials.
    return {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT') if key in os.environ}


def free_port(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeError(f'端口 {port} 被占用；请先确认归属，演示不会连接已有服务') from None


@contextmanager
def fresh_database(database, port):
    """Create a private cluster; never reuse a directory or an existing server."""
    require(database.endswith('_test') and port not in (5432, 55432), '只允许独立端口及 _test 库')
    free_port(port)
    env = isolated_env()
    directory = Path(os.environ.get('PG_BIN', ROOT / '.tools/postgres/bin'))
    pg_ctl = tool('pg_ctl', directory)
    initdb = tool('initdb', Path(pg_ctl).parent)
    require(' 17.' in subprocess.check_output([pg_ctl, '--version'], env=env, text=True, timeout=10),
            '此入口需要 PostgreSQL 17')
    base = Path(tempfile.mkdtemp(prefix='signalhub-synthetic-'))
    data = base / 'pgdata'
    password = secrets.token_hex(24)
    credentials = dict(host='127.0.0.1', port=port, user='signalhub', password=password,
                       connect_timeout=3, sslmode='disable', options='')
    try:
        pwfile = base / 'init-password'
        try:
            pwfile.touch(mode=0o600)
            pwfile.write_text(password + '\n')
            subprocess.run([initdb, '-D', str(data), '-U', 'signalhub', '--auth=scram-sha-256',
                            '--encoding=UTF8', '--no-locale', '--pwfile=' + str(pwfile)],
                           env=env, check=True, timeout=45, stdout=subprocess.DEVNULL)
        finally:
            pwfile.unlink(missing_ok=True)
        options = f'-h 127.0.0.1 -p {port} -c unix_socket_directories= -c max_connections=20 -c shared_buffers=32MB'
        subprocess.run([pg_ctl, '-D', str(data), '-l', str(base / 'postgres.log'), '-o', options,
                        '-w', '-t', '20', 'start'], env=env, check=True, timeout=25, stdout=subprocess.DEVNULL)
        with psycopg.connect(dbname='postgres', autocommit=True, **credentials) as conn:
            require(Path(conn.execute('SHOW data_directory').fetchone()[0]).resolve() == data.resolve(),
                    '新集群身份不符')
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        url = URL.create('postgresql+psycopg', username='signalhub', password=password,
                         host='127.0.0.1', port=port, database=database)
        yield dict(env, DB_USER='signalhub', DB_PASSWORD=password, DB_URL=f'jdbc:postgresql://127.0.0.1:{port}/{database}',
                   DATABASE_URL=url.render_as_string(hide_password=False), AI_PROVIDER='disabled',
                   AI_PAID_AUTHORIZED='false', LOCAL_TRANSLATION_ENABLED='false'), credentials, base
    finally:
        # Only stop and delete the directory created above. Retain it if the server cannot stop.
        if (data / 'postmaster.pid').exists():
            subprocess.run([pg_ctl, '-D', str(data), '-w', '-t', '20', 'stop', '-m', 'fast'],
                           env=env, check=True, timeout=25, stdout=subprocess.DEVNULL)
        shutil.rmtree(base)


def seed(client, env, credentials):
    with psycopg.connect(dbname=DATABASE, **credentials) as conn:
        migrations = [r[0] for r in conn.execute('SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank')]
        require(migrations == [str(v) for v in range(1, 13)], 'Flyway V1–V12 未全部应用')
        require(conn.execute("SELECT count(*) FROM sources WHERE adapter<>'manual'").fetchone()[0] == 0,
                '演示库不应含网络来源')
        source = conn.execute("SELECT id FROM sources WHERE status='test_data' AND adapter='manual'").fetchone()[0]

    html = client.get('/view/import')
    html.raise_for_status()

    def meta(name):
        return re.search(r'<meta[^>]+name="' + name + r'"[^>]+content="([^"]+)"', html.text).group(1)

    headers = {meta('csrf-header'): meta('csrf')}

    def api(path, method='GET', data=None, params=None):
        response = client.request(method, '/api' + path, json=data, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

    def tick(task_id):
        require(api(f'/tasks/{task_id}')['state'] == 'pending', '任务未进入持久队列')
        subprocess.run([sys.executable, '-m', 'signalhub.cli', 'tick'], env=env, cwd=ROOT,
                       check=True, timeout=20, stdout=subprocess.DEVNULL)
        task = api(f'/tasks/{task_id}')
        require(task['state'] == 'done', 'Worker 未完成任务')
        return task['result']

    record = dict(kind='job', external_id='portfolio-data-intern', title='[合成演示] 数据工程实习',
                  company='示例数据工坊（虚构）', country='CN', city='上海', categories=['data_engineering'],
                  employment_type='internship', url='https://example.com/signalhub/data-intern',
                  is_demo=True, body="Bachelor's degree required. Required: Python and SQL.")
    def import_job(value):
        return tick(api('/imports', 'POST', dict(sourceId=source, records=[value]))['taskId'])

    first, replay = import_job(record), import_job(record)
    require(first['inserted'] == replay['deduplicated'] == 1 and replay['updated'] == 0, '重复导入未去重')
    row = api('/items', params=dict(source=source, includeDemo='true'))['items'][0]
    item_id = row['id']
    detail = f'/items/{item_id}'
    require(api('/items', params=dict(source=source))['total'] == 0, '默认列表泄漏合成岗位')
    api('/profile', 'PUT', dict(education='bachelor', graduationYear=2028, currentlyStudying=True,
        cities=['上海'], roles=['data_engineering'], skills=['Python', 'SQL'], learningSkills=['Spark'],
        companyTypes=[], excludedTerms=[], employmentTypes=['internship'], internshipStartFrom='2027-03-01', internshipStartTo='2027-05-31',
        weights=dict(role=30, skills=40, city=15, company=0, qualifications=15)))
    api('/matches/refresh', 'POST')
    require(api(detail)['matching_status'] == 'current', '初始匹配未计算')
    updated = import_job({**record, 'body': record['body'] + ' Preferred: Spark.'})
    stale = api(detail)
    require(updated['updated'] == 1 and stale['matching_status'] == 'pending' and stale['score'] is None,
            '新 JD 版本没有让旧匹配失效')
    api('/matches/refresh', 'POST')
    current = api(detail)
    require(len(current['versions']) == 2 and current['hard_status'] == 'insufficient_information'
            and current['recruitment']['state'] == 'synthetic', '版本、未知资格或合成标记未正确展示')
    explanation = current['explanation']
    require(any(q['key'] == 'internship_start' and q['status'] == 'unconfirmed' for q in explanation['qualifications'])
            and abs(sum(p['contribution'] for p in explanation['breakdown']) - explanation['baseScore']) < .01
            and abs(explanation['baseScore'] + sum(a['delta'] for a in explanation['adjustments']) - current['score']) < .01,
            '春季到岗未知或分数解释未正确展示')
    for status in ('saved', 'applied'):
        api(f'/applications/{item_id}', 'PUT', dict(status=status, notes='合成演示；没有向雇主发送任何材料。'))
    require(len(api(f'/applications/{item_id}/history')) == 2, '收藏／模拟投递历史缺失')
    translation = api('/translations', 'POST', dict(ids=[item_id], depth=2))
    require(translation['state'] == 'unavailable' and current['payload']['body'].endswith('Preferred: Spark.'),
            '没有模型时应保留原文')
    require(tick(api(detail + '/enrich', 'POST')['taskId'])['state'] == 'disabled', 'AI 未安全降级')
    with psycopg.connect(dbname=DATABASE, **credentials) as conn:
        require(conn.execute('SELECT count(*) FROM raw_records').fetchone()[0] == 2
                and conn.execute('SELECT count(*) FROM ai_usage').fetchone()[0] == 0
                and conn.execute('SELECT count(*) FROM items WHERE NOT is_demo').fetchone()[0] == 0,
                '原文去重、AI 用量或数据隔离不符')
    return dict(database=DATABASE, flyway='V1–V12', item=item_id, score=current['score'],
                hard_status=current['hard_status'], versions=2, translation=translation['state'],
                ai='disabled', applications=['saved', 'applied'], date=date.today().isoformat())


def run(verify_only):
    free_port(WEB_PORT)
    java = tool('java', Path(os.environ.get('JAVA_HOME', ROOT / '.tools/jdk/Contents/Home')) / 'bin')
    jar = ROOT / 'backend-java/target/signalhub-0.1.0.jar'
    require(jar.is_file(), '先按 README 构建 JAR')
    with fresh_database(DATABASE, PG_PORT) as (env, credentials, base):
        env.update(PORT=str(WEB_PORT), SERVER_ADDRESS='127.0.0.1')
        # Keep our own copy so a concurrent Maven package cannot replace a running JAR.
        demo_jar = shutil.copy2(jar, base / 'backend.jar')
        with (base / 'java.log').open('wb') as log:
            backend = subprocess.Popen([java, '-Xms64m', '-Xmx256m', '-jar', demo_jar],
                                       env=env, cwd=base, stdout=log, stderr=subprocess.STDOUT)
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{WEB_PORT}', trust_env=False, timeout=5) as client:
                    for _ in range(120):
                        require(backend.poll() is None, '隔离 Java 提前退出')
                        try:
                            reply = client.get('/api/health')
                            if reply.is_success:
                                health = reply.json()
                                require(health['pid'] == backend.pid and health['database'] == DATABASE, '隔离 Java 身份不符')
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(.25)
                    else:
                        raise RuntimeError('隔离 Java 未就绪')
                    result = seed(client, env, credentials)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    if not verify_only:
                        print(f"详情 http://127.0.0.1:{WEB_PORT}/view/detail?id={result['item']}  |  Ctrl+C 停止并清理演示", flush=True)
                        backend.wait()
                        raise RuntimeError('隔离 Java 意外退出')
            finally:
                if backend.poll() is None:
                    backend.terminate()
                    try:
                        backend.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        backend.kill()
                        backend.wait()


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true', help='跑完真实链路即退出，不保留服务')
    args = parser.parse_args()
    for key in list(os.environ):
        if key.startswith('PG') and key != 'PG_BIN':
            os.environ.pop(key)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        run(args.verify_only)
    except KeyboardInterrupt:
        pass
