import httpx
import pytest
from signalhub.http import Fetcher,public_address
from signalhub.adapters.github import GithubAdapter
from signalhub.adapters.greenhouse import GreenhouseAdapter
from signalhub.adapters.rss import RssAdapter

@pytest.fixture(autouse=True)
def dns(monkeypatch): monkeypatch.setattr('socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])

def test_rate_limit_retries_bounded():
    calls=[]; delays=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(429,headers={'Retry-After':'1'}) if len(calls)<3 else httpx.Response(200,json=[])
    response=Fetcher(httpx.Client(transport=httpx.MockTransport(handler)),sleep=delays.append).get('https://api.github.com/x')
    assert response.status_code==200 and len(calls)==3 and delays==[1,1]
    with pytest.raises(httpx.HTTPStatusError): Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(429))),sleep=lambda x:None).get('https://api.github.com/x')

def test_timeout_and_server_errors():
    calls=[]
    def timeout(r): calls.append(r);raise httpx.ReadTimeout('test')
    with pytest.raises(httpx.ReadTimeout): Fetcher(httpx.Client(transport=httpx.MockTransport(timeout)),sleep=lambda x:None).get('https://api.github.com/x')
    assert len(calls)==3
    with pytest.raises(httpx.HTTPStatusError): Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(500))),sleep=lambda x:None).get('https://api.github.com/x')

def test_ssrf_and_redirect(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):public_address('https://localhost/x')
    with pytest.raises(ValueError):public_address('http://api.github.com/x')
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    with pytest.raises(httpx.HTTPStatusError):Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'http://localhost'})))).get('https://api.github.com/x')

def test_adapters_and_not_modified():
    f=Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(304))))
    for adapter,config in [(GreenhouseAdapter(),{'board':'test'}),(RssAdapter(),{'url':'https://github.blog/feed/'})]:
        rows,res,same=adapter.fetch(config,f,{})
        assert same and rows==[]
    f=Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'jobs':[{'id':1,'title':'Data Engineer','content':'SQL','absolute_url':'https://example.com/a','updated_at':'2026-01-01','location':{'name':'Shanghai'}}]}))))
    rows,_,_=GreenhouseAdapter().fetch({'board':'test','company_type':'foreign'},f,{})
    assert rows[0]['country'] is None and rows[0].get('published_at') is None

def test_github_reads_every_page_without_reusing_a_page_validator(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN',raising=False)
    calls=[]
    def handler(request):
        calls.append(request)
        assert 'If-None-Match' not in request.headers and 'If-Modified-Since' not in request.headers
        assert request.headers['Accept']=='application/vnd.github+json'
        assert request.headers['User-Agent']=='synthetic-test'
        start=int(request.url.params.get('page','1'))
        rows=[dict(id=start*100+n,tag_name=f'v{start}-{n}',html_url=f'https://example.com/{start}/{n}') for n in range(100)]
        return httpx.Response(200,json=rows,headers={'ETag':'single-page'})
    f=Fetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    headers={'If-None-Match':'stale','if-modified-since':'yesterday','User-Agent':'synthetic-test'}
    rows,response,same=GithubAdapter().fetch({'repo':'synthetic/releases'},f,headers)
    assert len(rows)==500 and len(calls)==5 and response is None and not same
    assert headers['If-None-Match']=='stale'  # 不修改调用方输入。

def test_rss_atom_and_malicious_xml():
    atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><title>test</title><entry><title>Summer program</title><id>1</id><link href="https://example.com/1"/><summary>Unknown fees</summary></entry></feed>'
    f=Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=atom))))
    rows,_,_=RssAdapter().fetch({'url':'https://github.blog/feed/'},f,{})
    assert rows[0]['kind']=='opportunity' and rows[0]['title']=='Summer program'
    with pytest.raises(ValueError):RssAdapter().fetch({'url':'https://not-allowed.example/feed'},f,{})
    f=Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'<!DOCTYPE x [<!ENTITY y "x">]><x>&y;</x>'))))
    with pytest.raises(Exception):RssAdapter().fetch({'url':'https://github.blog/feed/'},f,{})
