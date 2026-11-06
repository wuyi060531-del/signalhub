"""现有工具链的本地生命周期入口；不安装、不删数据、不杀未知进程。"""
import argparse
from contextlib import contextmanager
import fcntl
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def read_env(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            match = re.fullmatch(r'\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)', line)
            require(match, '.env需使用NAME=value格式；不执行shell命令')
            key, value = match.groups()
            if value.startswith(('"', "'")):
                require(len(value)>1 and value[-1]==value[0], '.env引号未闭合')
                value=value[1:-1]
            values[key]=value  # 原样读取，不执行$()/反引号或变量展开。
    return values


class Runtime:
    def __init__(self, test=False):
        self.test = test
        self.home = ROOT / '.local' / ('v1-acceptance' if test else 'runtime')
        self.data = self.home / 'pgdata' if test else ROOT / '.local/pgdata'
        self.state_path = self.home / 'state.json'
        self.env = dict(os.environ) if test else {**read_env(ROOT / '.env'), **os.environ}
        self.port = 18084 if test else int(self.env.get('PORT', '8080'))
        self.db_port = 55434 if test else 55432
        self.database = 'signalhub_v1_test' if test else 'signalhub'
        require(1024<=self.port<=65535 and self.port!=self.db_port, 'HTTP端口配置无效')
        self.env.update(PORT=str(self.port), SERVER_ADDRESS='127.0.0.1', AI_PROVIDER='disabled', AI_PAID_AUTHORIZED='false')
        if test:
            # 验收不继承正式密钥和真实采集配置。
            for key in ('AI_API_KEY', 'GITHUB_TOKEN', 'AI_BASE_URL', 'AI_MODEL'):
                self.env.pop(key, None)
            self.env['RSS_ALLOWED_HOSTS']=''
            self.env['LOCAL_TRANSLATION_ENABLED']='false'
            for key in ('LOCAL_TRANSLATION_PYTHON','LOCAL_TRANSLATION_MODEL'):self.env.pop(key,None)
        self.env.setdefault('DB_USER', 'signalhub')
        from sqlalchemy.engine import URL, make_url
        configured = make_url(self.env['DATABASE_URL']) if not test and self.env.get('DATABASE_URL') else None
        if test:
            self.env.update(DB_USER='signalhub', DB_PASSWORD='')
        self.env.setdefault('DB_PASSWORD', (configured.password or '') if configured else '')
        generated = URL.create('postgresql+psycopg', username=self.env['DB_USER'], password=self.env['DB_PASSWORD'] or None,
                               host='127.0.0.1', port=self.db_port, database=self.database)
        self.url = configured if configured is not None else generated
        require(self.url.drivername=='postgresql+psycopg' and not self.url.query
                and self.url.host in ('127.0.0.1', 'localhost') and (self.url.port or 5432)==self.db_port
                and self.url.database==self.database and self.url.username==self.env['DB_USER']
                and (self.url.password or '')==self.env['DB_PASSWORD'], '本地启动仅支持本机55432/signalhub；DB凭据/地址必须一致，连接参数不能覆盖目标')
        jdbc=f'jdbc:postgresql://127.0.0.1:{self.db_port}/{self.database}'
        require(test or self.env.get('DB_URL', jdbc) in (jdbc, jdbc.replace('127.0.0.1', 'localhost')), 'Java/Python数据库地址不一致')
        self.env.update(DATABASE_URL=self.url.render_as_string(hide_password=False), DB_URL=jdbc)
        self.pg = self.find_bin('pg_ctl', Path(self.env.get('PG_BIN', ROOT / '.tools/postgres/bin')))
        java_home = ROOT / '.tools/jdk/Contents/Home'
        if not (java_home / 'bin/java').exists():
            java_home=Path(self.env.get('JAVA_HOME', '/nonexistent'))
        self.java=self.find_bin('java', java_home / 'bin')
        if self.java:
            self.env['JAVA_HOME']=str(Path(self.java).parent.parent)
        self.jar=ROOT / 'backend-java/target/signalhub-0.1.0.jar'

    @staticmethod
    def find_bin(name, directory):
        candidate=directory / name
        return str(candidate) if os.access(candidate, os.X_OK) else shutil.which(name)

    @contextmanager
    def lock(self):
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.home / 'control.lock').open('a') as file:
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('另一个启动/停止操作正在执行，请稍后检查status')
            yield

    def read_state(self):
        if not self.state_path.exists(): return {}
        state=json.loads(self.state_path.read_text())
        require(state.get('database')==self.database and state.get('data')==str(self.data), '状态文件与当前环境不符，拒绝控制进程')
        return state

    def save(self, state):
        state.update(database=self.database, data=str(self.data))
        temporary=self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, indent=2))
        temporary.chmod(0o600)
        temporary.replace(self.state_path)

    @staticmethod
    def identity(pid):
        if not isinstance(pid, int) or pid<=1: return None
        output=subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='], text=True, capture_output=True)
        return output.stdout.strip() if output.returncode==0 else None

    def alive(self, record):
        return bool(record and self.identity(record.get('pid'))==record.get('identity') and record.get('identity'))

    def pg_running(self):
        return bool(self.pg and self.data.exists() and subprocess.run([self.pg, '-D', str(self.data), 'status'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode==0)

    @staticmethod
    def free_port(port):
        try:
            with socket.socket() as probe:
                # 已停止服务的TIME_WAIT不是未知监听器；允许立即安全重启。
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeError(f'本机端口{port}已占用；拒绝连接/停止未知服务。用lsof -nP -iTCP:{port} -sTCP:LISTEN确认归属')

    def connect(self, database=None):
        import psycopg
        return psycopg.connect(host='127.0.0.1', port=self.db_port, dbname=database or self.database,
                               user=self.env['DB_USER'], password=self.env['DB_PASSWORD'], connect_timeout=3, autocommit=True)

    def health(self):
        import httpx
        with httpx.Client(trust_env=False, timeout=2) as client:
            response=client.get(f'http://127.0.0.1:{self.port}/api/health')
            response.raise_for_status()
            return response.json()

    def doctor(self):
        require(sys.version_info>=(3,11), '需要Python3.11+，推荐3.12')
        for module in ('psycopg','sqlalchemy','httpx','pydantic','apscheduler','signalhub.cli'):
            try: importlib.import_module(module)
            except ImportError: raise RuntimeError(f'缺少Python依赖{module}，请按README准备现有.venv；不会自动安装')
        require(self.java, '缺少JDK21；配置JAVA_HOME或现有.tools/jdk，不会安装')
        version=subprocess.run([self.java, '-version'], capture_output=True, text=True)
        require(re.search(r'version "21\.', version.stderr+version.stdout), '本地运行需JDK21')
        require(self.pg, '缺少PostgreSQL17；设置PG_BIN到已有bin目录，不会安装')
        pg_version=subprocess.check_output([self.pg, '--version'], text=True)
        require(' 17.' in pg_version, '本地运行需PostgreSQL17')
        for name in ('initdb','postgres'):
            require(os.access(Path(self.pg).parent / name, os.X_OK), f'PostgreSQL目录缺少{name}')
        require(self.env['DB_USER']=='signalhub', '管理现有本地cluster要求DB_USER=signalhub')
        return dict(python=sys.version.split()[0], java='21', postgres='17',
                    database=self.database, http=f'http://127.0.0.1:{self.port}',
                    ai='disabled', credentials='not_displayed', dependencies='available')

    def launch(self, command, name, state):
        log_path=self.home / (name+'.log')
        descriptor=os.open(log_path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
        with os.fdopen(descriptor, 'ab') as log:
            process=subprocess.Popen(command, cwd=ROOT, env=self.env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        # 身份以实际exec完成后的ps为准；不用只凭PID杀进程。
        time.sleep(0.15)
        require(process.poll() is None, f'{name}启动失败，日志：{log_path}')
        identity=self.identity(process.pid)
        require(identity, f'{name}进程无法识别')
        record=dict(pid=process.pid, identity=identity)
        state[name]=record
        self.save(state)
        return record

    def build(self):
        sources=list((ROOT / 'backend-java/src/main').rglob('*'))+[ROOT / 'backend-java/pom.xml']
        stale=not self.jar.exists() or any(p.is_file() and p.stat().st_mtime>self.jar.stat().st_mtime for p in sources)
        if stale:
            require(self.find_bin('mvn', ROOT / '.tools/maven/bin'), '缺少Maven3.9，无法构建JAR；不会安装')
            log_path=self.home / 'build.log'
            print(f'正在构建Java（不执行数据库测试），日志：{log_path}', flush=True)
            with log_path.open('ab') as log:
                log_path.chmod(0o600)
                completed=subprocess.run([str(ROOT / 'scripts/mvn.sh'), '-f', 'backend-java/pom.xml', 'package', '-DskipTests'],
                    cwd=ROOT, env=self.env, stdout=log, stderr=subprocess.STDOUT)
            require(completed.returncode==0, f'Java构建失败；查看{log_path}，现有服务未停止')

    def prepare_backend_artifact(self):
        # A running JVM lazily reads resources from its JAR; Maven replaces target/ in place.
        # Keep a private copy so ordinary packaging cannot truncate the live app's archive.
        deployed=self.home/'backend.jar'
        temporary=self.home/'backend.next.jar'
        shutil.copy2(self.jar,temporary)
        os.replace(temporary,deployed)
        return deployed

    def start(self):
        with self.lock():
            self.doctor()
            state=self.read_state()
            backend=self.alive(state.get('backend'))
            worker=self.alive(state.get('worker'))
            if backend and worker and self.pg_running():
                health=self.health()
                require(health.get('database')==self.database and health.get('pid')==state['backend']['pid'], '后端实例/数据库身份不符')
                return self.status()
            # 验证所有需新启动的端口，再做任何进程/数据库操作。
            if not backend: self.free_port(self.port)
            if not self.pg_running(): self.free_port(self.db_port)
            self.build()
            started=[]
            pg_started=False
            try:
                if not self.pg_running():
                    if not self.data.exists():
                        command = [str(Path(self.pg).parent/'initdb'), '-D', str(self.data), '-U', 'signalhub',
                                   '--encoding=UTF8', '--no-locale']
                        if self.test:
                            subprocess.run(command + ['--auth=trust'], check=True, stdout=subprocess.DEVNULL)
                        else:
                            password = self.env['DB_PASSWORD']
                            require(password and '\n' not in password and '\r' not in password,
                                    '新建本机库前请在忽略的.env或环境设置非空DB_PASSWORD；旧库不改认证')
                            with tempfile.NamedTemporaryFile(mode='w', dir=self.home) as pwfile:
                                pwfile.write(password + '\n')
                                pwfile.flush()
                                subprocess.run(command + ['--auth=scram-sha-256', '--pwfile='+pwfile.name],
                                               check=True, stdout=subprocess.DEVNULL)
                    options=shlex.join(['-h','127.0.0.1','-p',str(self.db_port), '-c','unix_socket_directories=',
                                        '-c','shared_buffers=64MB','-c','max_connections=20'])
                    subprocess.run([self.pg, '-D', str(self.data), '-l', str(self.home/'postgres.log'), '-o', options, 'start'], check=True)
                    pg_started=True
                with self.connect('postgres') as conn:
                    require(Path(conn.execute('SHOW data_directory').fetchone()[0]).resolve()==self.data.resolve(), '数据库目录不符，拒绝初始化其他实例')
                    if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (self.database,)).fetchone():
                        from psycopg import sql
                        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.database)))
                if not backend:
                    self.launch([self.java, '-Xms64m', '-Xmx384m', '-jar', str(self.prepare_backend_artifact())], 'backend', state)
                    started.append('backend')
                for _ in range(120):
                    require(self.alive(state.get('backend')), f'Java已退出；查看{self.home}/backend.log')
                    try:
                        health=self.health()
                        require(health.get('database')==self.database and health.get('pid')==state['backend']['pid'], '后端实例身份不符')
                        break
                    except (OSError, ValueError): pass
                    except Exception as exc:
                        import httpx
                        if not isinstance(exc, httpx.HTTPError): raise
                    time.sleep(0.25)
                else: raise RuntimeError('Java/Flyway健康检查30秒超时')
                if not worker:
                    self.launch([str(ROOT/'.venv/bin/python'), '-m', 'signalhub.cli', 'worker'], 'worker', state)
                    started.append('worker')
                state['pg_managed']=pg_started or state.get('pg_managed', False)
                self.save(state)
                return self.status()
            except BaseException:
                for name in reversed(started):
                    self.stop_process(state.get(name))
                    state.pop(name, None)
                if pg_started:
                    subprocess.run([self.pg, '-D', str(self.data), 'stop', '-m', 'fast'], stdout=subprocess.DEVNULL)
                self.save(state)
                raise

    def stop_process(self, record):
        if not self.alive(record): return
        os.kill(record['pid'], signal.SIGTERM)
        for _ in range(300):
            if not self.alive(record): return
            time.sleep(0.1)
        raise RuntimeError('进程未安全退出；未使用SIGKILL，请检查日志/任务')

    def stop(self, with_db=False):
        with self.lock():
            state=self.read_state()
            if with_db and self.pg_running():
                require(state.get('pg_managed'), '数据库由原流程启动；本脚本未接管，不自动停止共享数据库')
            if self.pg_running():
                with self.connect() as conn:
                    require(Path(conn.execute('SHOW data_directory').fetchone()[0]).resolve()==self.data.resolve(), '数据库目录不符，拒绝控制其他实例')
                    exists=conn.execute("SELECT to_regclass('public.task_requests')").fetchone()[0]
                    if exists:
                        require(conn.execute("SELECT count(*) FROM task_requests WHERE state='running'").fetchone()[0]==0,
                                '任务仍在执行；请等待完成后再stop，不中断正在处理的数据')
                    translation_exists=conn.execute("SELECT to_regclass('public.reading_translation_jobs')").fetchone()[0]
                    if translation_exists:
                        require(conn.execute("SELECT count(*) FROM reading_translation_jobs WHERE state='running'").fetchone()[0]==0,
                                '本地翻译任务仍在执行；请等待完成后再stop')
            for name in ('worker','backend'):
                record=state.get(name)
                if record and not self.alive(record) and self.identity(record.get('pid')):
                    raise RuntimeError('PID身份变化，拒绝停止；先确认进程归属')
            for name in ('worker','backend'):
                record=state.get(name)
                self.stop_process(record)
                state.pop(name, None)
                self.save(state)
            if with_db and self.pg_running():
                require(state.get('pg_managed'), '数据库由原流程启动；本脚本未接管，不自动停止共享数据库')
                subprocess.run([self.pg, '-D', str(self.data), 'stop', '-m', 'fast'], check=True)
                state['pg_managed']=False
                self.save(state)
            return dict(state='stopped', database='stopped' if not self.pg_running() else 'kept_running', data='preserved')

    def status(self):
        state=self.read_state()
        result=dict(database=self.database, postgres='running' if self.pg_running() else 'stopped',
                    backend='running' if self.alive(state.get('backend')) else 'not_managed_or_stopped',
                    worker='running' if self.alive(state.get('worker')) else 'not_managed_or_stopped',
                    ai='disabled', logs=str(self.home), data='preserved')
        result['http']=f'http://127.0.0.1:{self.port}'
        try:
            result['health']=self.health()
            require(result['health'].get('database')==self.database, '健康端点数据库身份不符')
        except Exception:
            result['health']='unavailable_or_unverified'
        result['processes']={name: {'pid': state[name]['pid'], 'rss_kib': subprocess.check_output(
            ['ps','-p',str(state[name]['pid']),'-o','rss='], text=True).strip()} for name in ('backend','worker') if self.alive(state.get(name))}
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('doctor','start','status','stop','restart','run-java','run-worker'))
    parser.add_argument('--test', action='store_true', help='独立PG目录/55434/18084/signalhub_v1_test，不读取.env')
    parser.add_argument('--with-db', action='store_true', help='stop时也停止由本脚本启动的数据库，保留数据')
    parser.add_argument('--open', action='store_true', help='启动成功后用macOS默认浏览器打开控制台')
    args=parser.parse_args()
    try:
        runtime=Runtime(args.test)
        if args.command in ('run-java','run-worker'):
            command = ([runtime.java, '-Xms64m', '-Xmx384m', '-jar', str(runtime.jar)] if args.command=='run-java'
                       else [sys.executable, '-m', 'signalhub.cli', 'worker'])
            require(command[0], '缺少 JDK21')
            os.execve(command[0], command, runtime.env)
        if args.command=='restart':
            runtime.stop(args.with_db)
            result=runtime.start()
        elif args.command=='stop': result=runtime.stop(args.with_db)
        else: result=getattr(runtime, args.command)()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.open and args.command in ('start','restart'):
            require(sys.platform=='darwin' and shutil.which('open'), '自动打开仅支持现有macOS open；请使用输出的http地址')
            subprocess.run(['open',f'http://127.0.0.1:{runtime.port}'],check=True)
        return 0
    except Exception as exc:
        # 不输出连接串/密钥/驱动异常；日志仅留在忽略的.local。
        message=str(exc) if isinstance(exc, RuntimeError) else f'{type(exc).__name__}；检查.local日志和docs/LOCAL_RUN.md'
        print('SignalHub: '+message, file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
