"""可复现静态验收；--docker显式启动独立_test栈，不删除卷或发布镜像。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import uuid
from zoneinfo import ZoneInfo

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(path):
    # BaseLoader保留Actions的on键，不受YAML1.1布尔键转换影响。
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def static_checks():
    production = load(ROOT / 'docker-compose.yml')
    acceptance = load(ROOT / 'docker-compose.test.yml')
    workflow = load(ROOT / '.github/workflows/ci.yml')
    for config in (production, acceptance):
        services = config['services']
        require(set(services) == {'db', 'backend', 'worker'}, '服务集合无效')
        for service in services.values():
            for port in service.get('ports', []):
                require(port.startswith('127.0.0.1:'), '只能绑定本机端口')
            require('mem_limit' in service, '缺少内存上限')
        require(services['backend']['depends_on']['db']['condition']=='service_healthy', 'Java必须等待DB健康')
        require(services['worker']['depends_on']['backend']['condition']=='service_healthy', 'Worker必须等待Flyway/Java健康')
        for name in ('db', 'backend'):
            require('healthcheck' in services[name], '缺少健康检查')
        require(services['worker']['environment']['AI_PAID_AUTHORIZED']=='false', 'Worker禁止付费调用')
        for name in ('backend', 'worker'):
            require(services[name]['environment']['AI_PROVIDER'] in ('disabled', '${AI_PROVIDER:-disabled}'), 'AI必须默认关闭')
            build = services[name]['build']
            require(build['context']=='.', '构建必须使用仓库上下文')
            dockerfile = (ROOT / build['dockerfile']).read_text()
            require(re.search(r'^USER 10001$', dockerfile, re.M), '业务容器必须非root')
    services = acceptance['services']
    prod = production['services']
    require(all(s['logging']['options']=={'max-size':'10m','max-file':'3'} for s in prod.values()), 'Compose缺少日志轮换')
    require(all(prod[service]['environment'][key].startswith('${SIGNALHUB_COMPOSE_DB_PASSWORD:?')
                for service, key in [('db','POSTGRES_PASSWORD'),('backend','DB_PASSWORD'),('worker','PGPASSWORD')]),
            'Compose必须显式配置独立密码')
    require(services['db']['environment']['POSTGRES_DB']=='signalhub_test', '验收库必须_test')
    require(services['backend']['environment']['DB_URL'].endswith('/signalhub_test'), 'Java验收库错误')
    require(services['worker']['environment']['DATABASE_URL'].endswith('/signalhub_test'), 'Worker验收库错误')
    require(services['backend']['ports']==['127.0.0.1:18082:8080'], '验收HTTP端口必须独立')
    require(services['db']['ports']==['127.0.0.1:55433:5432'], '验收DB端口必须独立')
    require(set(acceptance['volumes']).isdisjoint(production['volumes']), '验收卷不能复用正式卷名')
    require('${' not in (ROOT / 'docker-compose.test.yml').read_text(), '验收配置不能读正式环境变量')
    ignored = (ROOT / '.dockerignore').read_text().splitlines()
    for name in ('.env', '.env.*', '.local', '.venv', '.tools', '.git'):
        require(name in ignored, '构建上下文未排除本地敏感目录')
    require(set(workflow['on']) == {'push', 'pull_request'}, 'CI触发配置错误')
    require(workflow['permissions']=={'contents':'read'} and workflow['env']['SIGNALHUB_EVIDENCE_DIR']=='ci-evidence',
            'CI需只读仓库权限和独立产物目录')
    uploads = [s['with']['path'] for job in workflow['jobs'].values() for s in job['steps']
               if s.get('uses','').startswith('actions/upload-artifact@')]
    require(uploads and all(path.startswith('ci-evidence/') for path in uploads), '禁止上传本机历史证据目录')
    steps = workflow['jobs']['test']['steps']
    commands = [step['run'] for step in steps if 'run' in step]
    expected = ['mvn -B -f backend-java/pom.xml verify',
                'cd data-pipeline-python && pytest --junitxml=../ci-evidence/python-junit.xml',
                'python scripts/evaluate.py', 'python scripts/integration_smoke.py',
                'python scripts/deployment_check.py']
    positions = [commands.index(command) for command in expected]
    require(positions==sorted(positions), 'CI必须顺序执行Java/Python/HTTP/配置验收')
    require(workflow['jobs']['test']['services']['postgres']['env']['POSTGRES_DB']=='signalhub_test', 'CI数据库必须_test')
    env = workflow['jobs']['test']['env']
    require(env['AI_PROVIDER']=='disabled' and env['AI_PAID_AUTHORIZED']=='false', 'CI必须显式禁用真实AI')
    container_steps = workflow['jobs']['container-test']['steps']
    require(any(s.get('run')=='python scripts/deployment_check.py --docker' for s in container_steps), '缺少独立容器验收作业')
    return ['Compose/CI YAML解析', '健康依赖/Flyway顺序/内存/loopback端口',
            '独立_test库/端口/卷且不读取正式环境', '非root业务镜像/敏感构建目录排除',
            'AI默认关闭/付费禁止', 'Java→Python→HTTP顺序与独立容器CI入口']


def container_smoke(compose):
    def sql(query):
        return subprocess.check_output(compose + ['exec', '-T', 'db', 'psql', '-U', 'signalhub',
            '-d', 'signalhub_test', '-Atc', query], cwd=ROOT, text=True, timeout=30).strip()
    require(sql('SELECT current_database()')=='signalhub_test', '运行库不是_test')
    expected = [str(v) for v in range(1, 13)]
    actual = sql('SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank').splitlines()
    require(actual == expected, 'Flyway V1–V12未完成')
    require(sql("SELECT count(*) FROM sources WHERE enabled AND adapter<>'manual'")=='0', '验收库存在真实采集源，拒绝继续')
    usage_before = sql('SELECT count(*) FROM ai_usage')
    marker = 'synthetic-container-' + uuid.uuid4().hex
    with httpx.Client(base_url='http://127.0.0.1:18082', timeout=30, trust_env=False) as client:
        client.get('/api/health').raise_for_status()
        page = client.get('/view/import')
        page.raise_for_status()
        def meta(name):
            return re.search(r'<meta[^>]+name="' + name + r'"[^>]+content="([^"]+)"', page.text).group(1)
        headers = {meta('csrf-header'): meta('csrf')}
        def api(path, body=None):
            response = client.request('POST' if body is not None else 'GET', '/api'+path, json=body, headers=headers)
            response.raise_for_status()
            return response.json()
        require(client.post('/api/matches/refresh').status_code==403, 'CSRF未启用')
        source = api('/sources', dict(name=marker, adapter='manual', config={}, enabled=True))['id']
        record = dict(kind='job', external_id=marker, title='[合成容器验收] Python实习', body='要求Python', is_demo=True)
        def wait(task_id):
            for _ in range(40):
                task = api(f'/tasks/{task_id}')
                if task['state'] in ('done', 'failed'):
                    require(task['state']=='done', '容器Worker任务失败')
                    return task['result']
                time.sleep(1)
            raise RuntimeError('容器Worker任务超时')
        first = wait(api('/imports', dict(sourceId=source, records=[record]))['taskId'])
        require(first['inserted']==1 and first['failed']==0, '容器导入未成功')
        repeated = wait(api('/imports', dict(sourceId=source, records=[record]))['taskId'])
        require(repeated['deduplicated']==1, '容器重复导入未去重')
        item_id = api(f'/items?source={source}&includeDemo=true')['items'][0]['id']
        require(wait(api(f'/items/{item_id}/enrich', {} )['taskId'])['state']=='disabled', '容器AI未安全降级')
    require(sql('SELECT count(*) FROM ai_usage')==usage_before, '容器AI出现计费记录')
    return ['PG健康/Flyway V1–V12', '真实CSRF', 'HTTP→Java队列→常驻容器Worker→PG',
            '重复导入去重', 'AI disabled/无计费']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', action='store_true', help='构建并运行独立容器验收，结束只down，保留卷')
    args = parser.parse_args()
    result = {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
              'remote_ci': 'not_run', 'docker_runtime': 'not_run',
              'limitation': '静态通过不等于镜像构建/容器运行/远程CI成功；无真实模型调用'}
    status = 0
    try:
        result['checks'] = static_checks()
        if not shutil.which('docker'):
            result['docker_runtime'] = 'not_installed_not_run'
            if args.docker:
                raise RuntimeError('Docker CLI不可用；不安装系统组件')
        elif args.docker:
            context_host = subprocess.check_output(['docker', 'context', 'inspect', '--format',
                '{{.Endpoints.docker.Host}}'], text=True, timeout=20).strip()
            # 不向配置中的远程daemon发送构建上下文。
            daemon_host = os.getenv('DOCKER_HOST') or context_host
            require(daemon_host.startswith(('unix://', 'npipe://')), '只允许本机Docker daemon')
            compose = ['docker', 'compose', '--project-name', 'signalhub-acceptance',
                       '--env-file', '/dev/null', '-f', str(ROOT / 'docker-compose.test.yml')]
            subprocess.run(['docker', 'info'], check=True, stdout=subprocess.DEVNULL, timeout=20)
            subprocess.run(compose + ['config', '--quiet'], cwd=ROOT, check=True, timeout=30)
            for port in (18082, 55433):
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', port))
            # 仅启动/关闭专属验收项目；不连接正式Compose，不删除任何卷。
            try:
                result['docker_runtime'] = 'failed'
                subprocess.run(compose + ['up', '--build', '--wait', '--wait-timeout', '180'], cwd=ROOT, check=True, timeout=900)
                result['runtime_checks'] = container_smoke(compose)
                result['docker_runtime'] = 'passed'
            finally:
                subprocess.run(compose + ['down'], cwd=ROOT, check=True, timeout=60)
        result['state'] = 'passed'
    except Exception as exc:
        result.update(state='failed', error=str(exc))
        status = 1
    output = ROOT / os.getenv('SIGNALHUB_EVIDENCE_DIR', '.local/check') / 'deployment-check.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return status


if __name__=='__main__':
    raise SystemExit(main())
