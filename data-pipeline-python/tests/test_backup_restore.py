"""备份恢复护栏；不写正式库、不启动外部命令。真实恢复另见交付证据。"""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('backup_restore', ROOT / 'scripts/backup_restore.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


@pytest.mark.parametrize('name', ['signalhub', 'postgres', 'signalhub_test', 'signalhub_restore_x',
                                  'signalhub_restore_x_test;DROP DATABASE signalhub'])
def test_formal_or_ambiguous_restore_name_rejected(name):
    with pytest.raises(RuntimeError, match='恢复只允许'):
        backup.validate_restore_name(name)


def test_valid_name_and_tampered_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, 'ROOT', tmp_path)
    folder = tmp_path / '.local/backups/fixture'
    folder.mkdir(parents=True)
    archive = folder / 'database.dump'
    archive.write_bytes(b'synthetic archive')
    (folder / 'manifest.json').write_text(json.dumps({'format': 1, 'database': 'signalhub', 'archive_sha256': backup.digest(archive)}))
    backup.validate_restore_name('signalhub_restore_fixture_test')
    assert backup.read_backup(folder)[0] == archive
    archive.write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='SHA256'):
        backup.read_backup(folder)
    with pytest.raises(RuntimeError, match='私有'):
        backup.read_backup(tmp_path)


def test_restore_rejects_existing_database_without_running_client(monkeypatch):
    from contextlib import nullcontext
    class Admin:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def fetchone(self): return (1,)
    class Runtime:
        def __init__(self, test): assert test is True
        def lock(self): return nullcontext()
        def connect(self, name): assert name == 'postgres'; return Admin()
    monkeypatch.setattr(backup, 'read_backup', lambda path: (path, {}))
    monkeypatch.setattr(backup, 'clients', lambda: {})
    monkeypatch.setattr(backup, 'Runtime', Runtime)
    monkeypatch.setattr(backup, 'verify_connection', lambda *args: None)
    monkeypatch.setattr(backup.subprocess, 'run', lambda *args, **kw: pytest.fail('不应执行恢复'))
    with pytest.raises(RuntimeError, match='已存在'):
        backup.restore(Path('unused'), 'signalhub_restore_existing_test')


def test_real_database_identity_verified_before_operation():
    class Conn:
        def execute(self, *args): return self
        def fetchone(self): return ('signalhub', '/wrong/directory', '170006')
    class Runtime:
        data = Path('/expected')
    with pytest.raises(RuntimeError, match='身份不符'):
        backup.verify_connection(Conn(), Runtime(), 'signalhub')
