import copy
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from test_smartrecruiters import JOB, Fetch, fetch_rows

@pytest.mark.parametrize('target,actual,keep', [
 ('Chengdu','Chengdu',True), ('成都',' 成都市 ',True),
 ('chengdu','CHENGDU',True), ('Chongqing','重庆市',True),
 ('重庆','Chongqing',True), ('Chengdu','Beijing',False),
 ('Chengdu',None,False), ('Chengdu','Chengdu / Beijing',False),
 ('Chengdu','Greater Chengdu',False), ('Chengdu',['Chengdu'],False),
])
def test_city_uses_detail_not_body_or_listing(target,actual,keep):
 job=copy.deepcopy(JOB)
 job['location']={'country':'cn','city':actual}
 job['jobAd']['sections']['jobDescription']['text']='Our program includes Chengdu and Chongqing'
 class StaleListing(Fetch):
  def get(self,url,headers):
   response=super().get(url,headers)
   if '?' in url:
    data=response.json()
    for row in data['content']:row['location']={'country':'cn','city':'Chengdu'}
    return httpx.Response(200,json=data)
   return response
 f=StaleListing([job]); rows,_,_=fetch_rows({'country':'CN','city':target},f)
 assert bool(rows)==keep
 query=parse_qs(urlsplit(f.calls[0][0]).query)
 assert query['city']==['Chongqing' if target in ('重庆','Chongqing') else 'Chengdu']
 if rows:
  assert rows[0]['external_id']==JOB['uuid']
  assert rows[0]['url']==JOB['postingUrl']
  assert rows[0]['_raw']['detail']==job
  assert 'status' not in rows[0] and 'source_verified_at' not in rows[0]

@pytest.mark.parametrize('value',['', ' ', [], True, 'x'*101])
def test_invalid_city_before_network(value):
 f=Fetch()
 with pytest.raises(ValueError):fetch_rows({'city':value},f)
 assert not f.calls

def test_omitted_city_keeps_existing_behavior():
 f=Fetch(); rows,_,_=fetch_rows({},f)
 assert len(rows)==1 and 'city' not in parse_qs(urlsplit(f.calls[0][0]).query)

@pytest.mark.parametrize('second',[{'offset':1,'totalFound':1,'content':[]},
 {'offset':1,'totalFound':2,'content':[]},
 {'offset':1,'totalFound':3,'content':[]},
 {'offset':1,'totalFound':2,'content':[JOB]}, None])
def test_incomplete_city_list_never_returns_success(second):
 class Broken:
  def get(self,url,headers):
   offset=int(parse_qs(urlsplit(url).query)['offset'][0])
   if offset==0:return httpx.Response(200,json={'offset':0,'totalFound':2,'content':[JOB]})
   if second is None:raise httpx.ReadTimeout('synthetic')
   return httpx.Response(200,json=second)
 with pytest.raises((ValueError,httpx.ReadTimeout)):
  fetch_rows({'country':'CN','city':'Chengdu'},Broken())

def test_detail_network_failure_propagates():
 class Broken(Fetch):
  def get(self,url,headers):
   if '?' not in url:raise httpx.ReadTimeout('synthetic')
   return super().get(url,headers)
 with pytest.raises(httpx.ReadTimeout):fetch_rows({'city':'Chengdu'},Broken())

@pytest.mark.parametrize('failure',['network','incomplete'])
def test_failed_city_collection_keeps_existing_job_status(db,monkeypatch,failure):
 from sqlalchemy import text
 from signalhub.pipeline import Pipeline
 from signalhub import adapters
 from signalhub.adapters.smartrecruiters import SmartRecruitersAdapter
 monkeypatch.setitem(adapters.ADAPTERS,'smartrecruiters',lambda:SmartRecruitersAdapter(sleep=lambda _:None))
 with db.begin() as c:
  source=c.execute(text("INSERT INTO sources(name,adapter,config,enabled) VALUES ('synthetic city','smartrecruiters',:config,true) RETURNING id"),{'config': '{"board":"example","country":"CN","city":"Chengdu"}'}).scalar_one()
 job=copy.deepcopy(JOB);job['location']['city']='Chengdu'
 assert Pipeline(db,Fetch([job])).run(source)['inserted']==1
 with db.connect() as c:
  before=c.execute(text('SELECT id,payload,content_hash FROM items')).all()
  success=c.execute(text('SELECT last_success FROM sources WHERE id=:id'),{'id':source}).scalar_one()
 class Failed:
  def get(self,url,headers):
   if failure=='network':raise httpx.ReadTimeout('synthetic')
   return httpx.Response(200,json={'offset':0,'totalFound':1,'content':[]})
 assert Pipeline(db,Failed()).run(source)['state']=='failed'
 with db.connect() as c:
  assert c.execute(text('SELECT id,payload,content_hash FROM items')).all()==before
  assert c.execute(text('SELECT last_success FROM sources WHERE id=:id'),{'id':source}).scalar_one()==success
