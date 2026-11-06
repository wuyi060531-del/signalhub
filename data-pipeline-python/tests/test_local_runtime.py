"""启动/停止护栏：不初始化真实数据库、不发送信号到真实进程。"""
import importlib.util
from pathlib import Path
import socket

import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('local_runtime', ROOT/'scripts/local_runtime.py')
local=importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(local,'ROOT',tmp_path)
    return local.Runtime(test=True)


def test_env_is_literal_and_never_shell_executed(tmp_path):
    marker=tmp_path/'never-create'
    env=tmp_path/'.env'
    env.write_text(f'AI_API_KEY=$(touch {marker})\nDB_PASSWORD="quoted value"\n')
    values=local.read_env(env)
    assert values['DB_PASSWORD']=='quoted value' and values['AI_API_KEY'].startswith('$(')
    assert not marker.exists()


def test_test_environment_ignores_formal_env_and_keys(tmp_path, monkeypatch):
    (tmp_path/'.env').write_text('DATABASE_URL=postgresql://private.example/formal\nAI_PROVIDER=compatible\n')
    monkeypatch.setattr(local,'ROOT',tmp_path)
    monkeypatch.setenv('AI_API_KEY','must-not-inherit')
    monkeypatch.setenv('GITHUB_TOKEN','must-not-inherit')
    runtime=local.Runtime(test=True)
    assert runtime.database.endswith('_test') and runtime.db_port==55434 and runtime.port==18084
    assert runtime.env['AI_PROVIDER']=='disabled' and runtime.env['AI_PAID_AUTHORIZED']=='false'
    assert 'AI_API_KEY' not in runtime.env and 'GITHUB_TOKEN' not in runtime.env


def test_unknown_live_port_rejected_and_released_port_allowed():
    with socket.socket() as server:
        server.bind(('127.0.0.1',0));server.listen()
        port=server.getsockname()[1]
        with pytest.raises(RuntimeError,match='已占用'):
            local.Runtime.free_port(port)
    local.Runtime.free_port(port)


def test_state_permissions_and_environment_identity_guard(runtime):
    with runtime.lock(): runtime.save({})
    assert runtime.state_path.stat().st_mode & 0o777 == 0o600
    runtime.state_path.write_text('{"database":"signalhub","data":"wrong"}')
    with pytest.raises(RuntimeError,match='状态文件'):
        runtime.read_state()


def test_reused_pid_is_never_signalled(runtime, monkeypatch):
    record={'pid':12345,'identity':'previous process'}
    monkeypatch.setattr(runtime,'identity',lambda pid:'unrelated process')
    monkeypatch.setattr(local.os,'kill',lambda *args:pytest.fail('不能向复用PID发信号'))
    runtime.stop_process(record)
    with runtime.lock(): runtime.save({'backend':record})
    monkeypatch.setattr(runtime,'pg_running',lambda:False)
    with pytest.raises(RuntimeError,match='PID身份变化'):
        runtime.stop()


def test_idempotent_start_does_not_duplicate_processes(runtime, monkeypatch):
    state={'backend':{'pid':11,'identity':'backend'},'worker':{'pid':12,'identity':'worker'}}
    with runtime.lock():runtime.save(state)
    monkeypatch.setattr(runtime,'doctor',lambda:{})
    monkeypatch.setattr(runtime,'alive',lambda record:True)
    monkeypatch.setattr(runtime,'pg_running',lambda:True)
    monkeypatch.setattr(runtime,'health',lambda:{'database':runtime.database,'pid':11})
    monkeypatch.setattr(runtime,'status',lambda:{'state':'already_running'})
    monkeypatch.setattr(runtime,'launch',lambda *args:pytest.fail('重复启动'))
    assert runtime.start()=={'state':'already_running'}


def test_stop_refuses_active_task_before_signalling(runtime,monkeypatch):
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query):
            self.query=query;return self
        def fetchone(self):
            if 'data_directory' in self.query:return (str(runtime.data),)
            return ('task_requests',) if 'to_regclass' in self.query else (1,)
    monkeypatch.setattr(runtime,'pg_running',lambda:True)
    monkeypatch.setattr(runtime,'connect',lambda:Connection())
    monkeypatch.setattr(runtime,'stop_process',lambda *args:pytest.fail('任务运行时不能停止'))
    with pytest.raises(RuntimeError,match='任务仍在执行'):runtime.stop()


def test_lock_rejects_simultaneous_mutation(runtime):
    with runtime.lock():
        with pytest.raises(RuntimeError,match='另一个启动'):
            with runtime.lock():pass


def test_foreign_database_config_rejected_without_connecting(tmp_path,monkeypatch):
    monkeypatch.setattr(local,'ROOT',tmp_path)
    monkeypatch.setenv('DATABASE_URL','postgresql+psycopg://signalhub:signalhub-test-fixture@private.example/signalhub')
    with pytest.raises(RuntimeError,match='本地启动仅支持'):local.Runtime()


def test_unowned_database_stop_refused_before_any_process_or_connection(runtime,monkeypatch):
    monkeypatch.setattr(runtime,'pg_running',lambda:True)
    monkeypatch.setattr(runtime,'connect',lambda:pytest.fail('所有权不符时不连接'))
    monkeypatch.setattr(runtime,'stop_process',lambda *args:pytest.fail('所有权不符时不停止应用'))
    with pytest.raises(RuntimeError,match='未接管'):runtime.stop(with_db=True)


def test_test_mode_never_inherits_local_translation_opt_in_or_model_paths(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_ENABLED','true')
    monkeypatch.setenv('LOCAL_TRANSLATION_PYTHON','/private/custom/python')
    monkeypatch.setenv('LOCAL_TRANSLATION_MODEL','/private/custom/model')
    rt=local.Runtime(True)
    assert rt.env['LOCAL_TRANSLATION_ENABLED']=='false'
    assert 'LOCAL_TRANSLATION_PYTHON' not in rt.env and 'LOCAL_TRANSLATION_MODEL' not in rt.env


def test_stop_refuses_active_local_translation_before_signalling(runtime,monkeypatch):
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query):self.query=query;return self
        def fetchone(self):
            if 'data_directory' in self.query:return (str(runtime.data),)
            if 'to_regclass' in self.query:return ('present',)
            return (1 if 'reading_translation_jobs' in self.query else 0,)
    monkeypatch.setattr(runtime,'pg_running',lambda:True)
    monkeypatch.setattr(runtime,'connect',lambda:Connection())
    monkeypatch.setattr(runtime,'stop_process',lambda *args:pytest.fail('本地翻译运行时不能停止'))
    with pytest.raises(RuntimeError,match='本地翻译任务仍在执行'):runtime.stop()


def test_live_backend_copy_survives_packaging_target_change(runtime):
    runtime.home.mkdir(parents=True,exist_ok=True)
    runtime.jar.parent.mkdir(parents=True,exist_ok=True)
    runtime.jar.write_bytes(b'synthetic jar version one')
    deployed=runtime.prepare_backend_artifact()
    assert deployed!=runtime.jar and deployed.read_bytes()==runtime.jar.read_bytes()
    runtime.jar.write_bytes(b'synthetic jar version two')
    assert deployed.read_bytes()==b'synthetic jar version one'
    with deployed.open('rb') as live_handle:
        runtime.prepare_backend_artifact()
        assert live_handle.read()==b'synthetic jar version one'
    assert deployed.read_bytes()==b'synthetic jar version two'
