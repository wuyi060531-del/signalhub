"""Explicit optional offline model setup. Fixed official index model URL, no accounts/paid API.
Run from the original repository with .venv/bin/python; never part of normal service startup.
"""
import hashlib
from pathlib import Path
import stat
import subprocess
import sys
import zipfile
import httpx

ROOT=Path(__file__).resolve().parents[1]
URL='https://argos-net.com/v1/translate-en_zh-1_9.argosmodel'
ARCHIVE_SHA256='433e7c4f034d87fbe2353161e05f18646d7999452f801a4e1f0378522b9850ab'


def main():
    home=ROOT/'.local/translation-model';home.mkdir(parents=True,exist_ok=True)
    archive=home/'en-zh.argosmodel'
    if not archive.exists():
        temporary=home/'en-zh.download'
        with httpx.stream('GET',URL,trust_env=False,follow_redirects=False,timeout=60) as response:
            response.raise_for_status();size=0
            with temporary.open('wb') as output:
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>100*1024*1024:raise ValueError('model_download_limit')
                    output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=ARCHIVE_SHA256:raise ValueError('archive_checksum_mismatch')
        temporary.rename(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=ARCHIVE_SHA256:raise ValueError('archive_checksum_mismatch')
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>400*1024*1024:raise ValueError('model_unpack_limit')
        for member in z.infolist():
            if not (home/member.filename).resolve().is_relative_to(home.resolve()) or stat.S_ISLNK(member.external_attr>>16):raise ValueError('unsafe_model_archive')
            if '/stanza/' not in member.filename:z.extract(member,home)
    interpreter=ROOT/'.local/translation-env/bin/python'
    if not interpreter.exists():subprocess.run([sys.executable,'-m','venv',str(interpreter.parent.parent)],check=True)
    subprocess.run([str(interpreter),'-m','pip','install','ctranslate2==4.8.0','sentencepiece==0.2.1'],check=True)
    print('本地模型与独立环境已准备；按文档显式启用 LOCAL_TRANSLATION_ENABLED=true 后空闲重启。')
    print('Argos en_zh 1.9 / OPUS-MT (Tiedemann, Thottingal), CC-BY 4.0. 下载后翻译完全离线。')


if __name__=='__main__':main()
