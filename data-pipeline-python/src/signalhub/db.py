import os
from sqlalchemy import create_engine

def engine():
    url = os.getenv('DATABASE_URL')
    if not url:
        raise RuntimeError('请显式配置 DATABASE_URL，或使用本地启动／合成演示入口')
    return create_engine(url, pool_size=2, max_overflow=0, pool_pre_ping=True)
