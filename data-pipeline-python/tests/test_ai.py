import httpx
import pytest
from pydantic import ValidationError
from signalhub.ai.providers import Analysis,MockProvider
from signalhub.ai.service import AIService
from signalhub.pipeline import Pipeline
from sqlalchemy import text

@pytest.fixture
def item(db):
    Pipeline(db).run(1,[dict(kind='job',external_id='ai-test',title='实习',body='要求 Python；2027届本科')])
    with db.connect() as c:return c.execute(text('SELECT id FROM items')).scalar_one()

def test_disabled_no_key_and_mock(db,item,monkeypatch):
    monkeypatch.setenv('AI_PROVIDER','disabled')
    assert AIService(db).enrich(item)['state']=='disabled'
    monkeypatch.setenv('AI_PROVIDER','compatible');monkeypatch.delenv('AI_API_KEY',raising=False)
    assert AIService(db).enrich(item)['state']=='blocked'
    monkeypatch.setenv('AI_PROVIDER','mock')
    result=AIService(db).enrich(item)
    assert result['state']=='success' and 'MOCK' in result['result']['summary']
    assert AIService(db).enrich(item)['state']=='cached'

def test_schema_json_missing_fields_and_evidence():
    for text in ['not json','{}']:
        with pytest.raises(ValidationError):Analysis.model_validate_json(text)
    result,_,_=MockProvider().analyze('要求 Python',{})
    result.graduation_year.value=2027;result.graduation_year.evidence='2027届'
    with pytest.raises(ValueError):result.verify('要求 Python')

class FailingProvider:
    name='test_paid'
    def analyze(self,*a):raise httpx.ReadTimeout('simulated')

def configure(monkeypatch):
    for k,v in {'AI_PAID_AUTHORIZED':'true','AI_API_KEY':'test-never-sent','AI_MODEL':'test','AI_INPUT_USD_PER_MILLION':'1','AI_OUTPUT_USD_PER_MILLION':'2','AI_MAX_CALLS_PER_MONTH':'1','AI_MONTHLY_BUDGET_USD':'1'}.items():monkeypatch.setenv(k,v)

def test_budget_reservation_limit_and_timeout(db,item,monkeypatch):
    configure(monkeypatch)
    assert AIService(db,FailingProvider()).enrich(item)['state']=='failed'
    assert AIService(db,FailingProvider()).enrich(item)['state']=='blocked'
    with db.connect() as c:
        row=c.execute(text('SELECT state,reserved_usd,actual_usd FROM ai_usage')).one()
        assert row.state=='failed' and row.reserved_usd>0 and row.actual_usd is None

def test_zero_budget_blocks_before_network(db,item,monkeypatch):
    configure(monkeypatch);monkeypatch.setenv('AI_MONTHLY_BUDGET_USD','0')
    assert AIService(db,FailingProvider()).enrich(item)['state']=='blocked'
    with db.connect() as c:assert c.execute(text('SELECT count(*) FROM ai_usage')).scalar_one()==0

def test_wrong_claim_with_real_evidence_rejected():
    result,_,_=MockProvider().analyze('2027届本科，要求 Python',{})
    result.graduation_year.value=2028;result.graduation_year.evidence='2027届'
    with pytest.raises(ValueError):result.verify('2027届本科，要求 Python')

def test_mock_extracts_facts_and_gap_honestly():
    body='数据工程实习；2027届本科；要求 Python SQL；截止：2026-12-31'
    result,inp,out=MockProvider().analyze(body,{'skills':['Python']})
    result.verify(body)
    assert result.education.value=='bachelor' and result.graduation_year.value==2027
    assert result.deadline.value=='2026-12-31' and result.category.value=='job'
    assert result.funding.value is None and result.relevance=='relevant'
    assert 'SQL' in result.skill_gap and '档案尚未确认' in result.skill_gap and inp==out==0

def test_value_evidence_disagreement_rejected():
    body='数据工程实习；截止：2026-12-31；资助：1000元'
    result,_,_=MockProvider().analyze(body,{})
    result.deadline.value='2026-11-30'
    with pytest.raises(ValueError):result.verify(body)
    result.deadline.value=None;result.funding.value='10000元';result.funding.evidence='资助：1000元'
    with pytest.raises(ValueError):result.verify(body)

def test_bad_budget_unknown_mode_and_mock_ignore_price(db,item,monkeypatch):
    configure(monkeypatch);monkeypatch.setenv('AI_MONTHLY_BUDGET_USD','NaN')
    assert AIService(db,FailingProvider()).enrich(item)['state']=='blocked'
    monkeypatch.setenv('AI_PROVIDER','typo')
    assert AIService(db).enrich(item)['state']=='blocked'
    monkeypatch.setenv('AI_PROVIDER','mock');monkeypatch.setenv('AI_INPUT_USD_PER_MILLION','invalid')
    assert AIService(db).enrich(item)['state']=='success'

def test_changed_profile_invalidates_ai_cache(db,item,monkeypatch):
    monkeypatch.setenv('AI_PROVIDER','mock');service=AIService(db)
    assert service.enrich(item)['state']=='success'
    with db.begin() as c:c.execute(text("UPDATE user_profiles SET settings=jsonb_set(settings,'{skills}','[\"Python\"]'),updated_at=now() WHERE id=1"))
    result=service.enrich(item)
    assert result['state']=='success' and result['result']['relevance']=='relevant'
    with db.connect() as c:assert c.execute(text('SELECT count(*) FROM ai_enrichments')).scalar_one()==2

def test_concurrent_ai_lock_prevents_double_call(db,item,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered,release=Event(),Event()
    class SlowMock(MockProvider):
        def analyze(self,*args):
            entered.set();assert release.wait(5)
            return super().analyze(*args)
    monkeypatch.setenv('AI_PROVIDER','mock')
    with ThreadPoolExecutor(max_workers=1) as pool:
        running=pool.submit(AIService(db,SlowMock()).enrich,item)
        assert entered.wait(5)
        try:assert AIService(db).enrich(item)['state']=='blocked'
        finally:release.set()
        assert running.result()['state']=='success'


def test_mock_explicit_english_deadline_obeys_same_evidence_contract():
    from signalhub.ai.providers import MockProvider
    body='Internship position; Applications close: 18 Sep 2026 2359 SGT'
    result, _, _=MockProvider().analyze(body, {})
    assert result.deadline.value=='2026-09-18'
    assert result.deadline.evidence==body
    result.verify(body)
