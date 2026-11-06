import csv
import json
import pytest
from signalhub.cli import read_file
from signalhub.normalize import normalize

def test_csv_nested_fields_and_raw_preserved(tmp_path):
    path=tmp_path/'jobs.csv'
    row={'kind':'job','external_id':'csv','title':'数据工程实习','body':'要求 Python SQL','categories':'["data_engineering"]','salary':'{"minimum":200,"period":"day","currency":"CNY"}','deadline':'2026-12-31'}
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    record=read_file(path)[0]
    assert record['_raw']['salary']==row['salary']
    item=normalize({k:v for k,v in record.items() if k!='_raw'})
    assert item.salary.minimum==200 and item.categories==['data_engineering']

def test_import_file_size_and_shape_guard(tmp_path):
    path=tmp_path/'bad.json';path.write_text('{}')
    with pytest.raises(ValueError):read_file(path)
    path.write_text(json.dumps([{}]*1001))
    with pytest.raises(ValueError):read_file(path)
    path.write_text(' '* (2*1024*1024+1))
    with pytest.raises(ValueError):read_file(path)

def test_packaged_demo_matches_java_and_fixture_and_is_explicit(tmp_path):
    from importlib.resources import files
    from pathlib import Path
    demo=json.loads(files('signalhub').joinpath('resources/demo.json').read_text())
    root=Path(__file__).resolve().parents[2]
    assert demo==json.loads((root/'tests/fixtures/demo.json').read_text())==json.loads((root/'backend-java/src/main/resources/demo.json').read_text())
    assert len(demo)==5 and all(normalize(row).is_demo for row in demo)


def test_csv_skill_groups_and_cohort_arrays(tmp_path):
    path=tmp_path/'groups.csv'
    body='要求Python或Java任选一项'
    row={'kind':'job','external_id':'csv-group','title':'实习','body':body,'graduation_years':'[2026,2027]',
         'skill_groups':json.dumps([dict(names=['Python','Java'],minimum=1,requirement='required',evidence=body)])}
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    item=normalize({k:v for k,v in read_file(path)[0].items() if k!='_raw'})
    assert item.graduation_years==[2026,2027] and item.skill_groups[0].minimum==1


def test_csv_experience_and_qualification_evidence_arrays(tmp_path):
    path=tmp_path/'experience.csv';body='工作经验：0-2年'
    row=dict(kind='job',external_id='csv-experience',title='Engineer',body=body,
        experience_requirements=json.dumps([dict(minimum_years=0,maximum_years=2,scope='work',requirement='required',evidence=body)]),
        qualification_review_notes=json.dumps([body]))
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    item=normalize({k:v for k,v in read_file(path)[0].items() if k!='_raw'})
    assert item.experience_requirements[0].minimum_years==0 and item.qualification_review_notes==[body]


def test_worker_shutdown_waits_for_current_tick(monkeypatch):
    import signal
    import sys
    import signalhub.cli as cli
    handlers={}
    stopped=[]
    class Scheduler:
        def __init__(self,**kwargs):pass
        def add_job(self,*args,**kwargs):pass
        def shutdown(self,wait):stopped.append(wait)
        def start(self):handlers[signal.SIGTERM](signal.SIGTERM,None)
    monkeypatch.setattr(cli,'BlockingScheduler',Scheduler)
    monkeypatch.setattr(cli,'engine',lambda:object())
    monkeypatch.setattr(cli.signal,'signal',lambda kind,handler:handlers.update({kind:handler}))
    monkeypatch.setattr(sys,'argv',['signalhub','worker'])
    cli.main()
    assert stopped==[True] and signal.SIGINT in handlers
