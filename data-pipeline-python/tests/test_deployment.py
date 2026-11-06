"""静态验收入口的安全护栏；不调用Docker、不启动服务或接触数据库。"""
import importlib.util
from pathlib import Path
import shutil
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('deployment_check', ROOT / 'scripts/deployment_check.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv('SIGNALHUB_EVIDENCE_DIR', raising=False)
    for path in ('docker-compose.yml', 'docker-compose.test.yml', '.github/workflows/ci.yml',
                 'backend-java/Dockerfile', 'data-pipeline-python/Dockerfile', '.dockerignore'):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    monkeypatch.setattr(deployment, 'ROOT', tmp_path)
    return tmp_path


def test_current_configuration_passes(config):
    assert len(deployment.static_checks()) == 6


@pytest.mark.parametrize('path,old,new,error', [
    ('docker-compose.test.yml', 'POSTGRES_DB: signalhub_test', 'POSTGRES_DB: signalhub', '验收库'),
    ('docker-compose.test.yml', '127.0.0.1:18082:8080', '0.0.0.0:18082:8080', '本机'),
    ('docker-compose.test.yml', 'acceptance_pgdata', 'pgdata', '复用正式卷'),
    ('docker-compose.test.yml', 'AI_PAID_AUTHORIZED: "false"', 'AI_PAID_AUTHORIZED: "true"', '付费'),
    ('docker-compose.test.yml', 'AI_PROVIDER: disabled', 'AI_PROVIDER: compatible', '默认关闭'),
    ('backend-java/Dockerfile', 'USER 10001', 'USER root', '非root'),
    ('.github/workflows/ci.yml', 'python scripts/deployment_check.py --docker', 'echo skipped', '容器验收'),
    ('.github/workflows/ci.yml', 'POSTGRES_DB: signalhub_test', 'POSTGRES_DB: signalhub', 'CI数据库'),
    ('.dockerignore', '.env.*', 'env-files-allowed', '敏感'),
])
def test_unsafe_configuration_rejected(config, path, old, new, error):
    file = config / path
    original = file.read_text()
    assert old in original
    file.write_text(original.replace(old, new))
    with pytest.raises(RuntimeError, match=error):
        deployment.static_checks()


def test_no_docker_records_limitation_without_execution(config, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['deployment_check.py'])
    monkeypatch.setattr(deployment.shutil, 'which', lambda name: None)
    monkeypatch.setattr(deployment.subprocess, 'run', lambda *a, **k: pytest.fail('不应执行Docker'))
    assert deployment.main()==0
    result=json.loads((config / '.local/check/deployment-check.json').read_text())
    assert result['state']=='passed' and result['docker_runtime']=='not_installed_not_run'


def test_remote_daemon_rejected_before_build_or_upload(config, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['deployment_check.py', '--docker'])
    monkeypatch.setattr(deployment.shutil, 'which', lambda name: '/mock/docker')
    monkeypatch.setattr(deployment.subprocess, 'check_output', lambda *a, **k: 'tcp://remote.example.com:2376')
    monkeypatch.setattr(deployment.subprocess, 'run', lambda *a, **k: pytest.fail('禁止向远程daemon发送上下文'))
    monkeypatch.delenv('DOCKER_HOST', raising=False)
    assert deployment.main()==1
    result=json.loads((config / '.local/check/deployment-check.json').read_text())
    assert '本机Docker daemon' in result['error'] and result['docker_runtime']=='not_run'
