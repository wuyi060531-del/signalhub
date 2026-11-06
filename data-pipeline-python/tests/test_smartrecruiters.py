import copy
from urllib.parse import urlsplit,parse_qs
import httpx
import pytest
from sqlalchemy import text
from signalhub.adapters.smartrecruiters import SmartRecruitersAdapter
from signalhub.pipeline import Pipeline

JOB={'id':'123','uuid':'public-123','name':'数据工程实习生','active':True,'visibility':'PUBLIC',
     'location':{'country':'cn','city':'Shanghai','region':'Shanghai','remote':False},
     'typeOfEmployment':{'id':'permanent'},'company':{'name':'Synthetic Company'},
     'releasedDate':'2026-10-13T08:00:00Z','postingUrl':'https://jobs.smartrecruiters.com/example/123',
     'jobAd':{'sections':{'jobDescription':{'text':'<p>要求 Python SQL</p>'},'qualifications':{'text':'本科2027届'},'additionalInformation':{'text':'每周到岗3天'}}}}

class Fetch:
    def __init__(self,jobs=None):self.jobs=jobs or [copy.deepcopy(JOB)];self.calls=[];self.fail=False
    def get(self,url,headers):
        self.calls.append((url,headers))
        query=parse_qs(urlsplit(url).query)
        if query:
            offset=int(query['offset'][0]);part=self.jobs[offset:offset+1]
            return httpx.Response(200,json={'offset':offset,'totalFound':len(self.jobs),'content':part})
        key=url.rsplit('/',1)[-1]
        if self.fail and key=='public-456':raise httpx.ReadTimeout('synthetic timeout')
        return httpx.Response(200,json=next(x for x in self.jobs if x['uuid']==key))

def fetch_rows(config,fetch=None):
    rows,response,same=SmartRecruitersAdapter(sleep=lambda _:None).fetch({'board':'example',**config},fetch or Fetch(),{'If-None-Match':'local-page-only'})
    return list(rows),response,same

def test_public_pagination_details_structured_fields_and_raw():
    other={**JOB,'id':'456','uuid':'public-456','postingUrl':'https://jobs.smartrecruiters.com/example/456'}
    f=Fetch([JOB,other]);rows,response,same=fetch_rows({'country':'CN','intern_only':True},f)
    assert len(rows)==2 and response is None and not same
    assert rows[0]['country']=='CN' and rows[0]['city']=='上海' and rows[0]['province']=='上海'
    assert rows[0]['employment_type']=='internship'  # 明确实习标题不是仅靠全职工时标签判断。
    assert rows[0]['_raw']['detail']==JOB and '<p>' in rows[0]['body']
    assert all('If-None-Match' not in h for _,h in f.calls)
    assert all(parse_qs(urlsplit(u).query).get('destination')==['PUBLIC'] for u,_ in f.calls if '?' in u)

def test_inactive_internal_and_unknown_country_not_guessed():
    for changed in ({'active':False},{'visibility':'INTERNAL'},{'visibility':None}):
        assert not fetch_rows({},Fetch([{**JOB,**changed}]))[0]
    rows=fetch_rows({},Fetch([{**JOB,'location':{'city':'Shanghai'}}]))[0]
    assert rows[0]['country'] is None and rows[0]['city']=='Shanghai'
    assert not fetch_rows({'intern_only':True},Fetch([{**JOB,'name':'Internal systems engineer'}]))[0]
    campus=fetch_rows({},Fetch([{**JOB,'name':'Campus Hiring_ETAS'}]))[0][0]
    assert campus['employment_type']=='campus'

@pytest.mark.parametrize('config',[{'board':'../private'},{'country':'China'},{'intern_only':'true'},{'max_items':True},{'max_items':201},{'q':[]}])
def test_bad_config_rejected_before_network(config):
    f=Fetch()
    with pytest.raises(ValueError):fetch_rows(config,f)
    assert not f.calls

def test_bounds_empty_early_page_and_identity_rejected():
    class BadList:
        def __init__(self,data):self.data=data
        def get(self,*a):return httpx.Response(200,json=self.data)
    for data in ({'offset':0,'totalFound':2001,'content':[]},{'offset':0,'totalFound':1,'content':[]},{'offset':2,'totalFound':1,'content':[JOB]}):
        with pytest.raises(ValueError):fetch_rows({},BadList(data))
    with pytest.raises(ValueError):fetch_rows({'max_items':1},Fetch([JOB,{**JOB,'uuid':'public-456'}]))
    class WrongDetail(Fetch):
        def get(self,url,headers):
            if '?' in url:return super().get(url,headers)
            return httpx.Response(200,json={**JOB,'uuid':'wrong'})
    with pytest.raises(ValueError):fetch_rows({},WrongDetail())


@pytest.mark.parametrize('same_page',[True,False])
def test_repeated_listing_identity_rejects_incomplete_snapshot(same_page):
    class Repeated(Fetch):
        def get(self,url,headers):
            if '?' not in url:return super().get(url,headers)
            offset=int(parse_qs(urlsplit(url).query)['offset'][0])
            return httpx.Response(200,json={'offset':offset,'totalFound':2,
                                          'content':[JOB,JOB] if same_page else [JOB]})
    with pytest.raises(ValueError,match='重复标识'):
        fetch_rows({},Repeated())


def test_repeated_listing_does_not_claim_fresh_source_or_write_partial_snapshot(db,monkeypatch):
    from signalhub import adapters
    monkeypatch.setitem(adapters.ADAPTERS,'smartrecruiters',lambda:SmartRecruitersAdapter(sleep=lambda _:None))
    with db.begin() as c:
        source=c.execute(text("INSERT INTO sources(name,adapter,enabled,status,last_success,etag,config) VALUES ('SR repeated synthetic','smartrecruiters',true,'verified',now()-interval '2 days','historical','{\"board\":\"example\"}') RETURNING id")).scalar_one()
        before=c.execute(text('SELECT last_success FROM sources WHERE id=:id'),{'id':source}).scalar_one()
    class Repeated:
        def get(self,url,headers):
            if '?' not in url:return httpx.Response(200,json=JOB)
            offset=int(parse_qs(urlsplit(url).query)['offset'][0])
            return httpx.Response(200,json={'offset':offset,'totalFound':2,'content':[JOB]})
    result=Pipeline(db,Repeated()).run(source)
    assert result['state']=='failed' and result['inserted']==0
    with db.connect() as c:
        source_row=c.execute(text('SELECT last_success,status,etag FROM sources WHERE id=:id'),{'id':source}).one()
        assert source_row.last_success==before and source_row.status=='unavailable' and source_row.etag=='historical'
        assert c.execute(text('SELECT count(*) FROM items')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM raw_records')).scalar_one()==0

def test_details_stream_preserves_prefix_and_retry_deduplicates(db,monkeypatch):
    # 使用无等待构造器，网络行为仍由明确响应fixture模拟。
    from signalhub import adapters
    monkeypatch.setitem(adapters.ADAPTERS,'smartrecruiters',lambda:SmartRecruitersAdapter(sleep=lambda _:None))
    with db.begin() as c:source=c.execute(text("INSERT INTO sources(name,adapter,enabled,config) VALUES ('SR synthetic','smartrecruiters',true,'{\"board\":\"example\",\"country\":\"CN\"}') RETURNING id")).scalar_one()
    second={**JOB,'id':'456','uuid':'public-456','postingUrl':'https://jobs.smartrecruiters.com/example/456'}
    f=Fetch([JOB,second]);f.fail=True;p=Pipeline(db,f)
    first=p.run(source)
    assert first['state']=='failed' and first['inserted']==1
    with db.connect() as c:assert c.execute(text('SELECT count(*) FROM raw_records')).scalar_one()==1
    f.fail=False;again=p.run(source)
    assert again['inserted']==1 and again['deduplicated']==1
    with db.connect() as c:assert c.execute(text('SELECT count(*) FROM item_versions')).scalar_one()==2


def load_reparse_script(monkeypatch,db):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('reparse_smartrecruiters',Path(__file__).resolve().parents[2]/'scripts/reparse-smartrecruiters.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'engine',lambda:db)
    return module


def test_reparse_tool_rejects_manual_source_before_writing(db,monkeypatch):
    module=load_reparse_script(monkeypatch,db)
    with pytest.raises(ValueError):module.reparse(1)
    with db.connect() as c:assert c.execute(text('SELECT count(*) FROM collection_runs')).scalar_one()==0


def test_reparse_tool_uses_actual_raw_without_network_or_source_freshness(db,monkeypatch):
    from signalhub import adapters
    monkeypatch.setitem(adapters.ADAPTERS,'smartrecruiters',lambda:SmartRecruitersAdapter(sleep=lambda _:None))
    with db.begin() as c:source=c.execute(text("INSERT INTO sources(name,adapter,enabled,config) VALUES ('SR archive synthetic','smartrecruiters',true,'{\"board\":\"example\"}') RETURNING id")).scalar_one()
    Pipeline(db,Fetch()).run(source)
    with db.begin() as c:c.execute(text("UPDATE sources SET status='unavailable',last_success=now()-interval '2 days' WHERE id=:id"),{'id':source})
    def forbidden(*a,**k):raise AssertionError('离线重解析不允许网络')
    monkeypatch.setattr('signalhub.http.Fetcher.get',forbidden)
    module=load_reparse_script(monkeypatch,db);result=module.reparse(source)
    assert result['deduplicated']==1 and result['external_requests']==0 and result['source_network_verification_unchanged']
    with db.connect() as c:
        assert c.execute(text('SELECT mode FROM collection_runs ORDER BY id DESC LIMIT 1')).scalar_one()=='archive_reparse'
        assert c.execute(text('SELECT status FROM sources WHERE id=:id'),{'id':source}).scalar_one()=='unavailable'


def test_intern_filter_rechecks_detail_and_accepts_plural_title():
    plural={**JOB,'name':'Software Engineering Internships','typeOfEmployment':None}
    assert fetch_rows({'intern_only':True},Fetch([plural]))[0][0]['employment_type']=='internship'
    class Changed(Fetch):
        def get(self,url,headers):
            if '?' in url:return super().get(url,headers)
            return httpx.Response(200,json={**JOB,'name':'Software Engineer','typeOfEmployment':{'id':'permanent'}})
    assert fetch_rows({'intern_only':True},Changed())[0]==[]


def test_official_section_titles_reset_preference_and_nullable_contract():
    from signalhub.normalize import normalize
    job={**JOB,'jobAd':{'sections':{
        'jobDescription':{'title':'职位描述','text':'The Nice-to-Haves:；Docker'},
        'qualifications':{'title':'职位要求','text':'Currently pursuing a Bachelor’s degree in Computer Science；Familiar with SQL'},
        'additionalInformation':{'title':'其他信息','text':'Java community events'}}}}
    raw=fetch_rows({},Fetch([job]))[0][0]
    parsed=normalize({k:v for k,v in raw.items() if k!='_raw'})
    assert parsed.education=='bachelor' and parsed.student_required is True
    assert {s.name:s.requirement for s in parsed.skills}=={'SQL':'required','Docker':'preferred','Java':'mentioned'}
    regular={**JOB,'name':'Software Engineer','typeOfEmployment':None}
    assert fetch_rows({},Fetch([regular]))[0][0]['employment_type'] is None
