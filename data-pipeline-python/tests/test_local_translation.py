"""Queue tests use explicitly synthetic provider output; real model evidence is separate."""
import json
from sqlalchemy import text
from signalhub.pipeline import Pipeline
from signalhub.local_translation import LocalTranslationWorker,LocalProvider,REVISION,build_inputs,pieces
from signalhub.local_nmt_runner import safe_reference

RAW=dict(kind='job',external_id='local-nmt-test',title='Test Engineer',body='Python is required. A bachelor degree is needed. 2028 graduates may apply.',is_demo=True)


def enqueue(db,depth=1):
    with db.begin() as c:
        item=c.execute(text('SELECT id,content_hash FROM items')).mappings().one()
        return c.execute(text("INSERT INTO reading_translation_jobs(item_id,content_hash,provider_revision,depth) VALUES (:id,:content_hash,:revision,:depth) ON CONFLICT(item_id,content_hash,provider_revision,depth) DO UPDATE SET id=reading_translation_jobs.id RETURNING id"),{**dict(item),'revision':REVISION,'depth':depth}).scalar_one()


class SyntheticProvider:
    calls=0
    def available(self):return True
    def translate(self,payload,depth):
        self.calls+=1
        return {'method':'synthetic_test_provider','title_zh':'明确合成测试译文','depth':depth,'reviewed':False}


def test_optional_provider_disabled_without_model_or_explicit_enable(monkeypatch):
    monkeypatch.setenv('LOCAL_TRANSLATION_ENABLED','false')
    assert not LocalProvider().available()


def test_idempotent_jobs_cache_deeper_result_without_touching_originals(db):
    Pipeline(db).run(1,[RAW]);enqueue(db,2);provider=SyntheticProvider();worker=LocalTranslationWorker(db,provider)
    assert worker.tick()['state']=='done'
    enqueue(db,1);assert worker.tick()['state']=='done';assert provider.calls==1
    with db.connect() as c:
        assert c.execute(text('SELECT count(*) FROM raw_records')).scalar_one()==1
        assert c.execute(text('SELECT count(*) FROM item_versions')).scalar_one()==1
        assert c.execute(text('SELECT count(*) FROM ai_usage')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM reading_translations')).scalar_one()==0
        assert c.execute(text("SELECT payload->>'body' FROM items")).scalar_one()==RAW['body']


def test_changed_source_never_receives_old_model_output(db):
    Pipeline(db).run(1,[RAW]);job=enqueue(db)
    class Changed(SyntheticProvider):
        def translate(self,payload,depth):
            with db.begin() as c:c.execute(text("UPDATE items SET content_hash='new-source'"))
            return super().translate(payload,depth)
    assert LocalTranslationWorker(db,Changed()).tick()['state']=='superseded'
    with db.connect() as c:
        assert c.execute(text('SELECT result FROM reading_translation_jobs WHERE id=:id'),{'id':job}).scalar_one() is None


def test_generation_failure_is_persistent_and_does_not_retry_on_every_page(db):
    Pipeline(db).run(1,[RAW]);enqueue(db)
    class Broken(SyntheticProvider):
        def translate(self,*a):raise RuntimeError('synthetic error with private input; never exposed')
    worker=LocalTranslationWorker(db,Broken());assert worker.tick()['state']=='failed';assert worker.tick() is None
    with db.connect() as c:
        row=c.execute(text('SELECT error,attempts FROM reading_translation_jobs')).one()
        assert row==('RuntimeError',1)


def test_old_lease_cannot_overwrite_a_new_attempt(db):
    Pipeline(db).run(1,[RAW]);enqueue(db)
    class Superseded(SyntheticProvider):
        def translate(self,payload,depth):
            with db.begin() as c:c.execute(text('UPDATE reading_translation_jobs SET attempts=attempts+1'))
            return super().translate(payload,depth)
    assert LocalTranslationWorker(db,Superseded()).tick()['state']=='superseded'
    with db.connect() as c:assert c.execute(text('SELECT result FROM reading_translation_jobs')).scalar_one() is None


def test_input_selection_preserves_technical_terms_and_labels_preview_as_partial():
    body='Company introduction. Python is required. '+('A long source paragraph for testing. '*200)
    inputs=build_inputs({**RAW,'body':body,'skills':[{'evidence':'Python is required.'}]},1)
    assert len(inputs['excerpt'])<=1600 and inputs['excerpt']!=body
    assert 'Python is required.' in inputs['requirements']
    assert all(len(p)<=520 for p in inputs['texts'])
    assert len(set(inputs['texts']))==len(inputs['texts'])
    assert ''.join(pieces('x'*1100))=='x'*1100


def test_numeric_terminology_negation_and_degree_checks_reject_bad_reference_segments():
    assert safe_reference('Python and SQL are required.','要求 Python 和 SQL。')=='要求 Python 和 SQL。'
    assert safe_reference('Python is not required.','要求 Python。') is None
    assert safe_reference('Graduate in 2028.','2027年毕业。') is None
    assert safe_reference('Use Python and RAG.','使用 Python 和检索增强生成。') is None
    assert safe_reference('A bachelor degree.','需要博士学位。') is None
    assert safe_reference('A bachelor degree.','需要学士学位。') is not None
    assert safe_reference('Test text','No Chinese at all') is None


def test_new_degree_and_lost_specialized_tool_are_not_published_as_reference():
    assert safe_reference('Develop backend systems.','开发后端系统，要求硕士。') is None
    assert safe_reference('Proficiency in Golang would be an advantage.','在戈兰的熟练程度将是一个很强的优势。') is None
    assert safe_reference('Proficiency in Golang would be an advantage.','熟悉 Golang 将是一个优势。') is not None


def test_list_numbers_are_not_sent_to_nmt_as_standalone_sentences():
    inputs=build_inputs({'title':'Test Engineer','body':'1. Python is required.\n2. Familiar with SQL.'},2)
    assert '1.' not in inputs['texts'] and '2.' not in inputs['texts']
    assert 'Python is required.' in inputs['texts']


def test_repository_release_identifier_is_preserved_instead_of_translating_brand():
    inputs=build_inputs({'kind':'release','title':'pallets/flask · 1.0','body':'This release fixes a bug.'},1)
    assert inputs['title']=='pallets/flask · 1.0' and inputs['title'] not in inputs['texts']
    assert safe_reference('GitHub Copilot app','GitHub 副驾驶应用程序') is None


def test_job_conditions_do_not_lose_units_or_become_preferences():
    assert safe_reference('Internship duration: 6 months.', '实习持续6年。') is None
    assert safe_reference('5 years of experience.', '5个月经验。') is None
    assert safe_reference('Work 3 days per week.', '每周工作3次。') is None
    assert safe_reference('Python is required.', 'Python优先。') is None
    assert safe_reference('Undergraduate students.', '在读学生。') is None
    assert safe_reference('Software Engineer Intern', '软件工程师') is None
    assert safe_reference('Internship duration: 6 months.', '实习持续6个月。') is not None


def test_reproduced_routing_and_coder_mistranslations_fall_back_to_source():
    assert safe_reference('Backend Engineering - Routing Efficiency', '后端工程 - 运行效率') is None
    assert safe_reference('You can be a good coder in any programming language.', '你可以成为任何编程语言的优秀编译者。') is None
    assert safe_reference('Backend Engineering - Routing Efficiency', '后端工程 - 路由效率') is not None


def test_current_degree_and_dotnet_are_not_lost_in_reference_translation():
    assert safe_reference('Pursuing Bachelor’s degree.', '获得学士学位。') is None
    assert safe_reference('Pursuing Bachelor’s degree.', '攻读学士学位。') is not None
    assert safe_reference('Familiar with computer language (python/java/.Net…)', '熟悉计算机语言(python/java/.') is None
    assert safe_reference('Familiarity with containerization technologies (Docker, Kubernetes)', '熟悉集装箱化技术(Docker、Kubernetes)') is None
