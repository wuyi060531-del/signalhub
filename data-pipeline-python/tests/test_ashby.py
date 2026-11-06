import httpx
import pytest
from sqlalchemy import text
from signalhub.adapters.ashby import AshbyAdapter
from signalhub.pipeline import Pipeline

JOB={'id':'official-id','title':'Software Engineer Intern','location':'China - Shanghai',
     'descriptionPlain':'Required: Python SQL; Docker preferred.', 'descriptionHtml':'<p>Required: Python SQL</p>',
     'jobUrl':'https://jobs.ashbyhq.com/example/official-id','isListed':True,'isRemote':False,
     'employmentType':'Intern','publishedAt':'2026-10-13T08:00:00Z',
     'address':{'postalAddress':{'addressCountry':'China','addressLocality':'Shanghai','addressRegion':'Shanghai'}},
     'secondaryLocations':[{'location':'Singapore','address':{'addressCountry':'Singapore','addressLocality':'Singapore'}}]}

class Fetch:
    def __init__(self,data):self.data=data;self.calls=[]
    def get(self,url,headers):self.calls.append((url,headers));return httpx.Response(200,json=self.data)

def test_public_listed_structured_locations_and_raw():
    fetch=Fetch({'jobs':[JOB,{**JOB,'isListed':False},{**JOB,'isListed':None}]})
    rows,_,same=AshbyAdapter().fetch({'board':'example','company_type':'foreign'},fetch,{})
    assert len(rows)==1 and not same
    row=rows[0]
    assert row['country']=='CN' and row['city']=='上海' and row['employment_type']=='internship'
    assert row['locations'][1]['country']=='SG' and row['remote'] is False and row['_raw']==JOB
    assert fetch.calls[0][0].startswith('https://api.ashbyhq.com/posting-api/job-board/example?')

def test_missing_country_not_inferred_and_bad_board_no_fetch():
    fetch=Fetch({'jobs':[{**JOB,'address':{},'secondaryLocations':[]}]})
    row=AshbyAdapter().fetch({'board':'example'},fetch,{})[0][0]
    assert row['country'] is None and row['city'] is None
    with pytest.raises(ValueError):AshbyAdapter().fetch({'board':'../localhost'},fetch,{})
    assert len(fetch.calls)==1

def test_304_and_source_id_fallback():
    class Unchanged:
        def get(self,*args):return httpx.Response(304)
    assert AshbyAdapter().fetch({'board':'example'},Unchanged(),{})[2]
    raw={k:v for k,v in JOB.items() if k!='id'}
    assert AshbyAdapter().fetch({'board':'example'},Fetch({'jobs':[raw]}),{})[0][0]['external_id']=='official-id'

def test_pipeline_real_adapter_repeat_and_content_change(db):
    with db.begin() as c:source=c.execute(text("INSERT INTO sources(name,adapter,enabled,config) VALUES ('Ashby test','ashby',true,'{\"board\":\"example\",\"company_type\":\"foreign\"}') RETURNING id")).scalar_one()
    fetch=Fetch({'jobs':[JOB]});p=Pipeline(db,fetch)
    assert p.run(source)['inserted']==1 and p.run(source)['deduplicated']==1
    fetch.data={'jobs':[{**JOB,'descriptionPlain':JOB['descriptionPlain']+' Required: Kafka.'}]}
    assert p.run(source)['updated']==1
    with db.connect() as c:
        assert c.execute(text('SELECT count(*) FROM items')).scalar_one()==1
        assert c.execute(text('SELECT count(*) FROM item_versions')).scalar_one()==2
        assert c.execute(text("SELECT payload->'locations'->1->>'country' FROM items")).scalar_one()=='SG'
