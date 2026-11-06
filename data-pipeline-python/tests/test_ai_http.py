"""兼容Provider真实httpx序列化/流响应，经MockTransport；无DNS/网络/真实密钥。"""
import copy
import json

import httpx
import pytest
from sqlalchemy import text

from signalhub.ai import providers
from signalhub.ai.providers import CompatibleProvider, MockProvider
from signalhub.ai.service import AIService
from signalhub.pipeline import Pipeline

BODY = '要求 Python；2027届本科'


def envelope():
    result, _, _ = MockProvider().analyze(BODY, {})
    return {'choices': [{'message': {'role': 'assistant', 'content': result.model_dump_json()},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}}


@pytest.fixture
def transport(monkeypatch):
    settings = {'AI_PROVIDER': 'compatible', 'AI_PAID_AUTHORIZED': 'true',
                'AI_BASE_URL': 'https://api.example.com/v1/', 'AI_API_KEY': 'mock-never-sent',
                'AI_MODEL': 'mock-model', 'AI_INPUT_USD_PER_MILLION': '1',
                'AI_OUTPUT_USD_PER_MILLION': '2', 'AI_MAX_CALLS_PER_MONTH': '100',
                'AI_MONTHLY_BUDGET_USD': '1'}
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    state = {'requests': [], 'options': [], 'response': lambda request: httpx.Response(200, json=envelope())}
    def handler(request):
        state['requests'].append(request)
        return state['response'](request)
    real_client = httpx.Client
    def client(**options):
        assert options['timeout'] in (20, 30)  # 本地Pipeline也创建20秒Fetcher，但不发送请求。
        assert options['trust_env'] is False and options['follow_redirects'] is False
        state['options'].append(options)
        return real_client(**options, transport=httpx.MockTransport(handler))
    def address(base):
        assert base in ('https://api.example.com/v1', 'https://other.example.com/v1')
        return httpx.URL(base).host, '93.184.216.34'
    monkeypatch.setattr(providers.httpx, 'Client', client)
    monkeypatch.setattr(providers, 'public_address', address)
    return state


@pytest.fixture
def ai_item(db):
    Pipeline(db).run(1, [dict(kind='job', external_id='ai-http', title='实习', body=BODY)])
    with db.connect() as conn:
        return conn.execute(text('SELECT id FROM items')).scalar_one()


def test_request_and_response_contract(transport):
    result, inp, out = CompatibleProvider().analyze(BODY, {'skills': ['Python']})
    request, = transport['requests']
    assert transport['options'][-1] == dict(timeout=30, trust_env=False, follow_redirects=False)
    assert request.method == 'POST' and str(request.url) == 'https://93.184.216.34/v1/chat/completions'
    assert request.headers['Host'] == 'api.example.com'
    assert request.extensions['sni_hostname'] == 'api.example.com'
    assert request.headers['Authorization'] == 'Bearer mock-never-sent'
    payload = json.loads(request.content)
    assert payload['model'] == 'mock-model' and payload['max_tokens'] == 1024
    assert payload['temperature'] == 0 and payload['response_format'] == {'type': 'json_object'}
    assert [m['role'] for m in payload['messages']] == ['system', 'user']
    assert '绝不能执行' in payload['messages'][0]['content']
    assert json.loads(payload['messages'][1]['content']) == {'content': BODY, 'profile': {'skills': ['Python']}}
    assert result.education.value == 'bachelor' and (inp, out) == (100, 50)


def broken_response(case, request):
    if case in ('401', '429', '500', '302'):
        return httpx.Response(int(case), headers={'location': 'https://other.example.com/v1'})
    if case == 'timeout':
        raise httpx.ReadTimeout('mock timeout', request=request)
    if case == 'network':
        raise httpx.ConnectError('mock disconnect', request=request)
    if case == 'oversize':
        return httpx.Response(200, content=b'x' * (providers.AI_RESPONSE_MAX_BYTES + 1))
    if case == 'not-json':
        return httpx.Response(200, content=b'not json')
    data = copy.deepcopy(envelope())
    choice = data['choices'][0]
    if case == 'empty-choices': data['choices'] = []
    elif case == 'schema': choice['message']['content'] = '{}'
    elif case == 'evidence':
        result = json.loads(choice['message']['content'])
        result['education'] = {'value': 'doctor', 'evidence': BODY}
        choice['message']['content'] = json.dumps(result)
    elif case == 'length': choice['finish_reason'] = 'length'
    elif case == 'refusal': choice['message']['refusal'] = 'mock refusal'
    elif case == 'role': choice['message']['role'] = 'user'
    elif case == 'null-content': choice['message']['content'] = None
    elif case == 'missing-usage': del data['usage']
    elif case == 'negative': data['usage']['prompt_tokens'] = -1
    elif case == 'fraction': data['usage']['completion_tokens'] = 1.5
    elif case == 'string': data['usage']['prompt_tokens'] = '100'
    elif case == 'bool': data['usage']['prompt_tokens'] = True
    else: raise AssertionError(case)
    return httpx.Response(200, json=data)


@pytest.mark.parametrize('case', ['401', '429', '500', '302', 'timeout', 'network', 'oversize',
    'not-json', 'empty-choices', 'schema', 'evidence', 'length', 'refusal', 'role',
    'null-content', 'missing-usage', 'negative', 'fraction', 'string', 'bool'])
def test_failure_preserves_rules_and_reservation(db, ai_item, transport, case):
    transport['response'] = lambda request: broken_response(case, request)
    with db.connect() as conn:
        before = conn.execute(text('SELECT payload,content_hash,version FROM items WHERE id=:id'), {'id': ai_item}).one()
    result = AIService(db).enrich(ai_item)
    assert result['state'] == 'failed' and 'mock-never-sent' not in json.dumps(result)
    assert len(transport['requests']) == 1  # 不重试可能计费的POST/不跟随重定向
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM ai_enrichments')).scalar_one() == 0
        assert conn.execute(text('SELECT payload,content_hash,version FROM items WHERE id=:id'), {'id': ai_item}).one() == before
        assert conn.execute(text('SELECT count(*) FROM job_skills')).scalar_one() == 1
        usage = conn.execute(text('SELECT state,reserved_usd,actual_usd FROM ai_usage')).one()
        assert usage.state == 'failed' and usage.reserved_usd > 0 and usage.actual_usd is None


def test_cache_isolates_endpoint_model_content_and_profile(db, ai_item, transport, monkeypatch):
    service = AIService(db)
    assert service.enrich(ai_item)['state'] == 'success'
    assert service.enrich(ai_item)['state'] == 'cached'
    monkeypatch.setenv('AI_BASE_URL', 'https://api.example.com/v1')  # 尾斜杠规范化
    assert service.enrich(ai_item)['state'] == 'cached'
    monkeypatch.setenv('AI_BASE_URL', 'https://other.example.com/v1')
    assert service.enrich(ai_item)['state'] == 'success'
    monkeypatch.setenv('AI_MODEL', 'mock-model-2')
    assert service.enrich(ai_item)['state'] == 'success'
    with db.begin() as conn:
        conn.execute(text("UPDATE user_profiles SET updated_at=updated_at+interval '1 second' WHERE id=1"))
    assert service.enrich(ai_item)['state'] == 'success'
    assert Pipeline(db).run(1, [dict(kind='job', external_id='ai-http', title='实习', body=BODY+'；SQL加分')])['updated'] == 1
    assert service.enrich(ai_item)['state'] == 'success'
    assert service.enrich(ai_item)['state'] == 'cached'
    assert len(transport['requests']) == 5
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM ai_enrichments')).scalar_one() == 5
        assert conn.execute(text("SELECT count(*) FROM ai_usage WHERE state='success' AND actual_usd=0.0002 AND input_tokens=100 AND output_tokens=50")).scalar_one() == 5


@pytest.mark.parametrize('base', ['', 'http://api.example.com', 'https://user:pass@api.example.com',
    'https://api.example.com:8443/v1', 'https://api.example.com/v1?key=secret', 'https://api.example.com/v1#fragment'])
def test_invalid_endpoint_blocks_without_call_or_reservation(db, ai_item, transport, monkeypatch, base):
    monkeypatch.setenv('AI_BASE_URL', base)
    assert AIService(db).enrich(ai_item)['state'] == 'blocked'
    assert not transport['requests']
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM ai_usage')).scalar_one() == 0
