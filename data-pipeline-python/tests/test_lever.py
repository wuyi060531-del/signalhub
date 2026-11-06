import copy
import json
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from sqlalchemy import text
from signalhub.adapters.lever import LeverAdapter
from signalhub.normalize import normalize
from signalhub.pipeline import Pipeline

JOB = dict(id='synthetic-123', text='Software Engineer Intern', country='CN',
           categories=dict(location='China - Shanghai', allLocations=['China - Shanghai', 'Singapore'], commitment='Internship'),
           description='<p>This internship is for 6 months.</p>',
           lists=[dict(text='Requirements', content='<li>Required: Python SQL</li>')],
           additional='<p>Apply via the official page.</p>', workplaceType='onsite',
           createdAt=1697205771219, hostedUrl='https://jobs.lever.co/example/synthetic-123')

class Fetch:
    def __init__(self, jobs=None):
        self.jobs = [copy.deepcopy(JOB)] if jobs is None else jobs
        self.calls = []
    def get(self, url, headers):
        self.calls.append((url, headers))
        skip = int(parse_qs(urlsplit(url).query)['skip'][0])
        return httpx.Response(200, json=self.jobs[skip:skip + 100])

def rows(config=None, fetch=None):
    return LeverAdapter(sleep=lambda _: None).fetch({'board':'example', **(config or {})}, fetch or Fetch(), {})[0]

def test_public_complete_body_primary_country_and_unknown_secondary():
    fetch = Fetch()
    raw = rows({'country':'CN', 'intern_only':True, 'commitment':'Internship'}, fetch)[0]
    job = normalize({k:v for k,v in raw.items() if k != '_raw'})
    assert job.country == 'CN' and job.city == '上海' and job.remote is False
    assert job.locations[1].country is None and job.locations[1].city is None
    assert job.employment_type == 'internship' and job.published_at is None and job.graduation_year is None
    assert 'Required: Python SQL' in job.body and 'Apply via the official page.' in job.body
    assert raw['_raw'] == JOB
    assert all(u.startswith('https://api.lever.co/v0/postings/example?') for u,h in fetch.calls)
    assert parse_qs(urlsplit(fetch.calls[0][0]).query)['commitment'] == ['Internship']

def test_label_only_not_imported_as_intern_and_unknown_country_not_guessed():
    label_only = {**JOB, 'text':'Associate Consultant', 'description':'Program for university graduates.'}
    assert rows({'intern_only':True}, Fetch([label_only])) == []
    record = rows({}, Fetch([label_only]))[0]
    assert record['employment_type'] is None and record['risk_notes']
    unknown = {**JOB, 'country':None}
    assert rows({'country':'CN'}, Fetch([unknown])) == []
    raw = rows({}, Fetch([unknown]))[0]
    assert raw['country'] is None and raw['city'] is None
    mentor = {**JOB, 'text':'Develop Mentorship', 'description':'This program is not tied to any hiring process.'}
    assert rows({'intern_only':True}, Fetch([mentor])) == []

@pytest.mark.parametrize('config', [{'board':'../private'}, {'country':'China'}, {'country':True},
                                  {'intern_only':'true'}, {'max_items':True}, {'max_items':201},
                                  {'commitment':[]}, {'commitment':''}])
def test_config_rejected_before_network(config):
    f = Fetch()
    with pytest.raises(ValueError): rows(config, f)
    assert not f.calls

def test_full_pagination_no_partial_cache_and_bounds():
    jobs = [{**JOB, 'id':f'synthetic-{n}'} for n in range(101)]
    f = Fetch(jobs)
    records, response, unchanged = LeverAdapter(sleep=lambda _:None).fetch({'board':'example', 'max_items':101}, f, {'If-None-Match':'partial'})
    assert len(records) == 101 and response is None and not unchanged
    assert len(f.calls) == 2 and all(not h for u,h in f.calls)
    with pytest.raises(ValueError): rows({'max_items':100}, Fetch(jobs))
    class Repeated(Fetch):
        def get(self, url, headers): return httpx.Response(200, json=jobs[:100])
    with pytest.raises(ValueError, match='重复标识'): rows({}, Repeated())
    with pytest.raises(ValueError, match='标识'): rows({}, Fetch([{**JOB, 'id':'../../private'}]))

def test_database_source_repeat_changed_version_and_alert_once(db):
    with db.begin() as conn:
        source = conn.execute(text("INSERT INTO sources(name,adapter,config,enabled) VALUES ('Lever synthetic','lever',CAST(:config AS jsonb),true) RETURNING id"), {'config':json.dumps(dict(board='example',country='CN',intern_only=True))}).scalar_one()
    f = Fetch(); pipeline = Pipeline(db, f)
    assert pipeline.run(source)['inserted'] == 1
    assert pipeline.run(source)['deduplicated'] == 1
    f.jobs[0]['description'] += '<p>Required: Java</p>'
    assert pipeline.run(source)['updated'] == 1
    assert pipeline.run(source)['deduplicated'] == 1
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM items')).scalar_one() == 1
        assert conn.execute(text('SELECT count(*) FROM item_versions')).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM alerts WHERE dedup_key LIKE 'change:%'")).scalar_one() == 1


def test_lever_archive_reparse_has_no_network_and_preserves_freshness(db,monkeypatch):
    import importlib.util
    from pathlib import Path
    with db.begin() as conn:
        source=conn.execute(text("INSERT INTO sources(name,adapter,config,enabled) VALUES ('Lever archive','lever',CAST(:c AS jsonb),true) RETURNING id"),{'c':json.dumps(dict(board='example',country='CN',intern_only=True))}).scalar_one()
    assert Pipeline(db,Fetch()).run(source)['inserted']==1
    def forbidden(*args,**kwargs):raise AssertionError('存档重解析不能访问网络')
    monkeypatch.setattr('signalhub.http.Fetcher.get',forbidden)
    spec=importlib.util.spec_from_file_location('reparse_public',Path(__file__).resolve().parents[2]/'scripts/reparse-smartrecruiters.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'engine',lambda:db)
    result=module.reparse(source)
    assert result['deduplicated']==1 and result['external_requests']==0
    assert result['source_network_verification_unchanged']
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM raw_records')).scalar_one()==1
        assert conn.execute(text('SELECT mode FROM collection_runs ORDER BY id DESC LIMIT 1')).scalar_one()=='archive_reparse'
