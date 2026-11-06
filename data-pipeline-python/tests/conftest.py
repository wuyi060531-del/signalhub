import os
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url

@pytest.fixture
def db():
    url=make_url(os.getenv('TEST_DATABASE_URL','postgresql+psycopg://signalhub:signalhub-test-fixture@127.0.0.1:55432/signalhub_test'))
    if (not (url.database or '').endswith('_test') or url.host not in ('127.0.0.1', 'localhost')
            or url.drivername != 'postgresql+psycopg' or url.query):
        raise RuntimeError('只允许本机测试库')
    engine=create_engine(url)
    with engine.begin() as c:
        if c.execute(text('SELECT current_database()')).scalar_one() != url.database:
            raise RuntimeError('测试库身份不符，拒绝清理')
        # 必须先由 Flyway 完成迁移；测试禁止替代迁移。
        c.execute(text('TRUNCATE reading_translation_jobs,translation_runtime,employer_reviews,ai_usage,ai_enrichments,alerts,application_history,job_applications,match_results,subscriptions,duplicate_candidates,job_skills,item_versions,item_sources,raw_records,items,companies,collection_runs,task_requests RESTART IDENTITY CASCADE'))
        c.execute(text("DELETE FROM sources WHERE id>2"))
    yield engine
    engine.dispose()
