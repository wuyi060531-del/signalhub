"""隔离库真实 HTTP → Java 队列 → Python ETL → Java 业务验收；不访问外网。"""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from signalhub.pipeline import execute
from signalhub.worker import Worker

ROOT = Path(__file__).resolve().parents[1]


def main():
    url = make_url(os.getenv('TEST_DATABASE_URL', 'postgresql+psycopg://signalhub:signalhub-test-fixture@127.0.0.1:55432/signalhub_test'))
    if (not (url.database or '').endswith('_test') or url.host not in ('127.0.0.1', 'localhost')
            or url.drivername != 'postgresql+psycopg' or url.query):
        raise RuntimeError('只允许本地 _test 数据库')
    db = create_engine(url, pool_pre_ping=True)
    with db.connect() as conn:
        if execute(conn, 'SELECT current_database()').scalar_one() != url.database:
            raise RuntimeError('拒绝正式库')
        if execute(conn,"SELECT count(*) FROM task_requests WHERE state IN ('pending','running')").scalar_one():
            raise RuntimeError('测试库有待执行任务；请先完成或隔离其他测试，不代为执行未知任务')
    port = int(os.getenv('INTEGRATION_PORT', '18080'))
    if not 1024 <= port <= 65535 or port == 8080:
        raise RuntimeError('隔离服务不能使用正式端口8080')
    # 拒绝连接占用该端口的未知服务；只测试本脚本新启动的实例。
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    java_home = Path(os.getenv('JAVA_HOME', ROOT / '.tools/jdk/Contents/Home'))
    java = str(java_home / 'bin/java') if (java_home / 'bin/java').exists() else shutil.which('java')
    if not java:
        raise RuntimeError('需要 JDK21 和已构建 JAR')
    evidence = ROOT / os.getenv('SIGNALHUB_EVIDENCE_DIR', '.local/check')
    evidence.mkdir(parents=True,exist_ok=True)
    env = dict(os.environ, DB_URL=f'jdbc:postgresql://{url.host}:{url.port or 5432}/{url.database}',
               DB_USER=url.username or '', DB_PASSWORD=url.password or '', PORT=str(port),
               SERVER_ADDRESS='127.0.0.1', AI_PROVIDER='disabled', AI_PAID_AUTHORIZED='false')
    # Python Worker 同样明确禁用 Provider；不读取正式 .env。
    os.environ['AI_PROVIDER'] = 'disabled'
    os.environ['AI_PAID_AUTHORIZED'] = 'false'
    os.environ['LOCAL_TRANSLATION_ENABLED'] = 'false'
    marker = 'synthetic-e2e-' + uuid.uuid4().hex
    checks = []
    with (ROOT / '.local').joinpath('integration-java.log').open('wb') as log:
        process = subprocess.Popen([java, '-Xms64m', '-Xmx256m', '-jar', str(ROOT / 'backend-java/target/signalhub-0.1.0.jar')],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30, trust_env=False) as client:
                for _ in range(40):
                    if process.poll() is not None:
                        raise RuntimeError('隔离 Java 启动失败，查看 .local/integration-java.log')
                    try:
                        client.get('/api/health').raise_for_status()
                        break
                    except httpx.HTTPError:
                        time.sleep(0.25)
                else:
                    raise RuntimeError('隔离 Java 健康检查超时')
                page = client.get('/view/import').text
                def meta(name):
                    return re.search(r'<meta[^>]+name="' + name + r'"[^>]+content="([^"]+)"', page).group(1)
                headers = {meta('csrf-header'): meta('csrf')}
                def api(path, method='GET', body=None, params=None):
                    r = client.request(method, '/api' + path, json=body, params=params, headers=headers)
                    r.raise_for_status()
                    return r.json() if r.content else None
                assert client.post('/api/matches/refresh').status_code == 403
                checks.append('真实HTTP拒绝缺少CSRF的写入')
                assert client.get('/api/profile', headers={'Host': 'rebinding.example'}).status_code == 403
                checks.append('真实HTTP拒绝恶意Host读取档案')
                guide = client.get('/job-sources.html')
                guide.raise_for_status()
                assert "script-src 'self'" in guide.headers['Content-Security-Policy']
                assert '当前在列状态以逐岗核验为准' in guide.text and '已有3条' not in guide.text
                checks.append('官方入口指南保留CSP，按逐岗证据判断在列，不显示固定存档数量')
                source = api('/sources', 'POST', dict(name=marker, adapter='manual', config={}, enabled=True))['id']
                record = dict(kind='job', external_id=marker, title='[合成端到端验收] 数据工程实习',
                              body='2027届 本科；要求 Python SQL；Spark加分', company=marker, company_type='foreign',
                              country='SG', city='Singapore', categories=['data_engineering'], employment_type='internship',
                              education='bachelor', graduation_year=2027, remote=False, is_demo=True,
                              deadline=(date.today() + timedelta(days=2)).isoformat(), url=f'https://example.com/synthetic/{marker}',
                              locations=[dict(country='SG', city='Singapore', primary=True), dict(country='CN', city='上海', primary=False)])
                def import_record(value, expect_success=True):
                    task = api('/imports', 'POST', dict(sourceId=source, records=value if isinstance(value,list) else [value]))['taskId']
                    # 不启动自动Worker，不采集test库内已有的公开来源。
                    for _ in range(100):
                        Worker(db).tick()
                        row = api(f'/tasks/{task}')
                        assert 'payload' not in row
                        if row['state'] in ('done', 'failed'):
                            if expect_success:assert row['state'] == 'done', row['result']
                            return row['result']
                    raise RuntimeError('任务未在有界循环内完成')
                first = import_record(record)
                assert first['inserted'] == 1 and first['failed'] == 0
                repeated = import_record(record)
                assert repeated['deduplicated'] == 1 and repeated['updated'] == 0
                checks.append('Java导入契约→真实数据库队列→Python解析/入库/重复去重')
                filters = dict(country='CN', city='上海', source=source, includeDemo='true')
                found = api('/items', params=filters)
                assert found['total'] == 1
                item_id = found['items'][0]['id']
                assert found['items'][0]['matching_status']=='pending' and found['items'][0]['score'] is None
                assert found['items'][0]['recruitment']['state']=='synthetic'
                assert api('/items', params={**filters, 'city': 'Singapore'})['total'] == 0
                assert api('/items', params={**filters, 'includeDemo': 'false'})['total'] == 0
                assert api('/skills', params=filters)['sampleSize'] == 1
                checks.append('同一附加中国地点列表/技能统计、跨地点拒绝、合成排除')
                company_subs={kind:api('/subscriptions','POST',dict(name=marker+'-'+kind,
                    rules=dict(kind='job',q=marker,company_type=kind,includeDemo=True),enabled=True))['id'] for kind in ('unknown','foreign')}
                def company_alerts(kind):
                    return [a for a in api('/alerts') if str(a['dedup_key']).startswith(f'subscription:{company_subs[kind]}:{item_id}:')]
                api('/matches/refresh','POST')
                assert len(company_alerts('unknown'))==1 and not company_alerts('foreign')
                review=dict(name=marker,origin='foreign',headquartersCountries=['US'],ownership='publicly_listed',industry='合成验收',
                            evidenceUrls=['https://example.com/synthetic-employer'],basis='明确合成HTTP核验，非真实公司',verifiedOn=date.today().isoformat(),status='verified')
                api('/employers/review','PUT',review)
                api('/matches/refresh','POST');api('/matches/refresh','POST')
                assert len(company_alerts('foreign'))==1 and len(company_alerts('unknown'))==1
                for kind,sub_id in company_subs.items():
                    api(f'/subscriptions/{sub_id}','PUT',dict(name=marker+'-'+kind,
                        rules=dict(kind='job',q=marker,company_type=kind,includeDemo=True),enabled=False))
                checks.append('未核验企业只匹配unknown订阅，核验后foreign提醒一次，历史提醒保留')
                assert api('/items',params={**filters,'domain':'domestic'})['total']==0
                assert api('/items',params={**filters,'domain':'foreign'})['total']==0
                checks.append('集团核验与主要工作国分开；海外主地点不进入大陆中心，普通多地点查询保留')
                profile = dict(skills=['Python', 'SQL'], learningSkills=['Spark'], cities=['上海'], roles=['data_engineering'],
                               companyTypes=['foreign'], excludedTerms=[], education='bachelor', graduationYear=2027,
                               hardCity=True, weights=dict(role=30, skills=40, city=15, company=15))
                api('/profile', 'PUT', profile)
                saved_profile=api('/profile')
                for key in ('skills','cities','roles','employmentTypes'):
                    bad=client.put('/api/profile',json={**profile,key:[None]},headers=headers)
                    assert bad.status_code==400 and api('/profile')==saved_profile
                for path,body in [('/imports',dict(sourceId=source,records=[None])),
                                  ('/translations',dict(ids=[None],depth=1)),
                                  ('/employers/review',{**review,'name':marker+'-null','headquartersCountries':[None]})]:
                    bad=client.request('PUT' if path=='/employers/review' else 'POST','/api'+path,json=body,headers=headers)
                    assert bad.status_code==400
                assert not any(e['name']==marker+'-null' for e in api('/employers'))
                checks.append('真实HTTP拒绝档案/导入/翻译ID/核验国家空元素，已存档案与企业核验不被污染')
                rules = dict(kind='job', country='CN', city='上海', employment_type='internship', remote=False, includeDemo=True)
                sub = api('/subscriptions', 'POST', dict(name=marker, rules=rules, enabled=True))['id']
                excluded_sub = api('/subscriptions', 'POST', dict(name=marker+'-no-demo', rules={**rules,'includeDemo':False}, enabled=True))['id']
                api('/matches/refresh', 'POST')
                matched = api('/items', params=filters)['items'][0]
                assert matched['matching_status']=='current'
                assert matched['hard_status'] == 'eligible' and matched['score'] >= 70
                explained=api('/items/'+str(item_id))['explanation']
                assert explained['score']==matched['score']
                assert abs(sum(part['contribution'] for part in explained['breakdown'])-explained['baseScore'])<0.01
                assert abs(explained['baseScore']+sum(a['delta'] for a in explained['adjustments'])-explained['score'])<0.01
                checks.append('真实五项评分贡献与调整相加等于最终分数，列表与详情同一计算结果')
                def sub_alerts():
                    return [a for a in api('/alerts') if str(a['dedup_key']).startswith(f'subscription:{sub}:{item_id}:')]
                assert len(sub_alerts()) == 1
                assert not any(str(a['dedup_key']).startswith(f'subscription:{excluded_sub}:{item_id}:') for a in api('/alerts'))
                api('/matches/refresh', 'POST')
                assert len(sub_alerts()) == 1
                checks.append('测试档案→三态匹配/分数→多地点订阅→重复提醒防重/演示订阅排除')
                app = dict(status='applied', notes='[合成验收] 未向任何雇主实际投递')
                api(f'/applications/{item_id}', 'PUT', app)
                api(f'/applications/{item_id}', 'PUT', {**app, 'status': 'interview1'})
                assert len(api(f'/applications/{item_id}/history')) == 2
                api('/matches/refresh', 'POST')
                alerts = [a for a in api('/alerts') if a['item_id'] == item_id]
                deadline_alert = next(a for a in alerts if a['dedup_key'].startswith('deadline:'))
                api(f'/alerts/{deadline_alert["id"]}/read', 'PUT')
                assert next(a for a in api('/alerts') if a['id'] == deadline_alert['id'])['read_at']
                checks.append('本地投递阶段/两份历史/截止提醒/已读持久化，无真实投递')
                changed = import_record({**record, 'body': record['body'] + '；要求 Java'})
                assert changed['updated'] == 1
                stale=api(f'/items/{item_id}')
                assert stale['matching_status']=='pending' and stale['score'] is None and stale['explanation'] is None
                api('/matches/refresh', 'POST')
                assert len(sub_alerts()) == 2
                assert len(api(f'/items/{item_id}')['versions']) == 2
                checks.append('正文变化→版本/变化提醒→订阅按版本追加')
                with db.connect() as conn:
                    usage_before=execute(conn,'SELECT count(*) FROM ai_usage').scalar_one()
                ai_task = api(f'/items/{item_id}/enrich', 'POST')['taskId']
                for _ in range(100):
                    Worker(db).tick()
                    with db.connect() as conn:
                        task = execute(conn,'SELECT state,result FROM task_requests WHERE id=:id',id=ai_task).mappings().one()
                    if task['state'] in ('done','failed'):
                        assert task['result']['state'] == 'disabled'
                        break
                else:raise RuntimeError('无Key降级任务超时')
                with db.connect() as conn:
                    assert execute(conn,'SELECT count(*) FROM ai_usage').scalar_one() == usage_before
                checks.append('AI disabled队列安全降级/无计费用量')
                grouped = {**record, 'external_id':marker+'-groups', 'url':record['url']+'-groups',
                           'body':'2026/2027届；本科在校生；要求Python、Java、SQL任意两种；Spark加分；不要求Docker；每周到岗3天；实习至少6个月',
                           'country':'CN','city':'上海','locations':[]}
                grouped.pop('graduation_year')
                assert import_record(grouped)['inserted']==1
                assert import_record(grouped)['deduplicated']==1
                # external_id不属于规范payload；用当前来源的官方URL定位实体。
                with db.connect() as conn:
                    group_id=execute(conn,'SELECT item_id FROM item_sources WHERE source_id=:s AND external_id=:e',s=source,e=grouped['external_id']).scalar_one()
                full_profile={**profile,'currentlyStudying':True,'availableDays':3,'availableMonths':6}
                def group_result(p):
                    api('/profile','PUT',p)
                    assert api(f'/items/{group_id}')['matching_status']=='pending'
                    api('/matches/refresh','POST')
                    return api(f'/items/{group_id}')
                detail=group_result(full_profile)
                assert detail['payload']['graduation_years']==[2026,2027]
                assert detail['payload']['skill_groups'][0]['minimum']==2
                assert detail['explanation']['hardStatus']=='eligible'
                assert detail['explanation']['skillConditions'][0]['status']=='satisfied'
                assert 'Java' not in detail['explanation']['unconfirmedSkills']
                assert 'Docker' not in [s['skill'] for s in detail['skills']]
                assert 'skillConditions' in client.get('/app.js').text
                assert '逐项技能判断' in client.get('/app.js').text
                assert client.get('/view/detail',params={'id':group_id}).status_code==200
                checks.append('技能任选组/否定/加分/多届别/在读条件经Python→PostgreSQL→Java详情与网页资源')
                partial=group_result({**full_profile,'skills':['Python'],'learningSkills':['Java','SQL']})['explanation']
                assert partial['hardStatus']=='insufficient_information' and partial['skillConditions'][0]['confirmed']==['Python']
                for changes in [dict(currentlyStudying=False),dict(graduationYear=2028),dict(availableDays=2)]:
                    assert group_result({**full_profile,**changes})['explanation']['hardStatus']=='not_eligible'
                empty={**full_profile,'skills':[],'learningSkills':['Python','SQL'],'roles':[],'cities':[],'companyTypes':[],
                       'education':None,'graduationYear':None,'currentlyStudying':None}
                assert group_result(empty)['explanation']['score']==0
                assert group_result(empty)['explanation']['hardStatus']=='insufficient_information'
                detail=group_result(full_profile)
                group_changed=import_record({**grouped,'body':grouped['body'].replace('两种','三种')})
                assert group_changed['updated']==1
                assert import_record({**grouped,'body':grouped['body'].replace('两种','三种')})['deduplicated']==1
                detail=group_result(full_profile)
                assert detail['explanation']['hardStatus']=='insufficient_information'
                assert len(detail['versions'])==2
                assert len([a for a in api('/alerts') if str(a['dedup_key']).startswith(f'subscription:{sub}:{group_id}:')])==2
                api('/matches/refresh','POST')
                assert len([a for a in api('/alerts') if str(a['dedup_key']).startswith(f'subscription:{sub}:{group_id}:')])==2
                checks.append('学习技能/空档案保护、学历届别与在读时间三态、组合变化版本与重复提醒防重')
                experience_record={**record,'external_id':marker+'-experience','url':record['url']+'-experience',
                    'title':'[合成验收] 数据工程师','employment_type':'full_time','country':'CN','city':'上海','locations':[],
                    'body':'2027届 本科；要求Python SQL；工作经验：3年以上'}
                assert import_record(experience_record)['inserted']==1
                with db.connect() as conn:
                    experience_id=execute(conn,'SELECT item_id FROM item_sources WHERE source_id=:s AND external_id=:e',s=source,e=experience_record['external_id']).scalar_one()
                experience_sub=api('/subscriptions','POST',dict(name=marker+'-experience',rules=dict(kind='job',country='CN',employment_type='full_time',includeDemo=True),enabled=True))['id']
                def experience_result(years):
                    api('/profile','PUT',{**profile,'workExperienceYears':years})
                    api('/matches/refresh','POST')
                    return api(f'/items/{experience_id}')
                assert experience_result(None)['explanation']['hardStatus']=='insufficient_information'
                assert experience_result(2)['explanation']['hardStatus']=='not_eligible'
                assert experience_result(3.5)['explanation']['hardStatus']=='eligible'
                assert api('/profile')['workExperienceYears']==3.5
                bad=client.put('/api/profile',json={**profile,'workExperienceYears':-1},headers=headers)
                assert bad.status_code==400 and api('/profile')['workExperienceYears']==3.5
                changed_experience={**experience_record,'body':experience_record['body'].replace('3年以上','4年以上')}
                assert import_record(changed_experience)['updated']==1
                assert import_record(changed_experience)['deduplicated']==1
                detail=experience_result(3.5)
                assert detail['explanation']['hardStatus']=='not_eligible' and len(detail['versions'])==2
                assert detail['payload']['experience_requirements'][0]['minimum_years']==4
                assert len([a for a in api('/alerts') if str(a['dedup_key']).startswith(f'subscription:{experience_sub}:{experience_id}:')])==2
                checks.append('工作经验年数经队列/PG/Java三态判断，档案0/小数/非法值边界，条件版本与订阅防重')
                alternative={**record,'external_id':marker+'-alternative','url':record['url']+'-alternative',
                    'country':'CN','city':'上海','locations':[],
                    'body':'This internship is for at least 6 months duration (at least 3 days per week)；Requirements；Pursuing Bachelor’s degree in Computer Science or equivalent work experience；Familiar with computer language (Python/Java/.Net)'}
                alternative.pop('education')
                assert import_record(alternative)['inserted']==1
                with db.connect() as conn:
                    alternative_id=execute(conn,'SELECT item_id FROM item_sources WHERE source_id=:s AND external_id=:e',s=source,e=alternative['external_id']).scalar_one()
                api('/profile','PUT',{**full_profile,'education':'associate'})
                api('/matches/refresh','POST');detail=api(f'/items/{alternative_id}')
                assert detail['payload']['education'] is None and detail['payload']['student_required'] is None
                assert detail['payload']['days_per_week']==3 and detail['payload']['duration_months']==6
                assert detail['payload']['qualification_review_notes'] and detail['payload']['unparsed_skill_conditions']
                assert detail['explanation']['hardStatus']=='insufficient_information'
                api('/profile','PUT',{**full_profile,'availableMonths':5})
                api('/matches/refresh','POST')
                assert api(f'/items/{alternative_id}')['explanation']['hardStatus']=='not_eligible'
                api('/profile','PUT',{**full_profile,'workExperienceYears':0})
                api('/matches/refresh','POST')
                assert api('/profile')['workExperienceYears']==0
                assert '经验年数与原文证据' in client.get('/app.js').text
                checks.append('英文实习时长、学位或同等经验与裸斜杠条件保留证据/待核验，未知档案时间保护')
                checks.append('岗位版本/档案修订变化立即隐藏旧匹配，刷新后列表与详情一致恢复当前结果')
                prefix={**record,'external_id':marker+'-partial-good','url':record['url']+'-partial-good'}
                rejected={**record,'external_id':marker+'-partial-bad','url':record['url']+'-partial-bad',
                    'skills':[dict(name='Java',requirement='required',evidence='正文中不存在的证据')]}
                partial=import_record([prefix,rejected],expect_success=False)
                assert partial['state']=='partial' and partial['inserted']==1 and partial['failed']==1
                with db.connect() as conn:
                    assert execute(conn,'SELECT count(*) FROM raw_records WHERE source_id=:s AND external_id=:e',s=source,e=rejected['external_id']).scalar_one()==1
                corrected={k:v for k,v in rejected.items() if k!='skills'}
                assert import_record(corrected)['inserted']==1 and import_record(corrected)['deduplicated']==1
                assert api('/items',params={**filters,'q':marker})['total']>=2
                assert '检查任务最新结果' in client.get('/app.js').text
                missing=client.get('/api/tasks/999999999')
                assert missing.status_code==404
                checks.append('按ID真实HTTP任务反馈、部分失败保留原文/成功前缀，修正同标识重提后幂等，无导入正文泄露')
                # 明确Mock：走HTTP→Java持久队列→Python→PG→Java详情，不调用真实模型。
                os.environ['AI_PROVIDER'] = 'mock'
                def mock_enrich():
                    task_id = api(f'/items/{item_id}/enrich', 'POST')['taskId']
                    for _ in range(100):
                        Worker(db).tick()
                        task = api(f'/tasks/{task_id}')
                        if task['state'] in ('done', 'failed'):
                            assert task['state'] == 'done', task
                            return task['result']
                    raise RuntimeError('Mock增强任务超时')
                mock = mock_enrich()
                assert mock['state']=='success' and mock['provider']=='mock' and 'MOCK' in mock['result']['summary']
                assert mock_enrich()['state']=='cached'
                assert len(api(f'/items/{item_id}')['ai'])==1
                api('/profile', 'PUT', {**full_profile,'skills':['Python']})
                assert api(f'/items/{item_id}')['ai']==[]
                assert mock_enrich()['state']=='success' and mock_enrich()['state']=='cached'
                assert import_record({**record,'body':record['body']+'；要求 Java；[合成Mock缓存验证]'})['updated']==1
                assert api(f'/items/{item_id}')['ai']==[]
                assert mock_enrich()['state']=='success' and mock_enrich()['state']=='cached'
                ai_detail = api(f'/items/{item_id}')
                assert len(ai_detail['ai'])==1 and ai_detail['ai'][0]['provider']=='mock:v4'
                assert ai_detail['ai'][0]['result']['summary'].startswith('[MOCK')
                with db.connect() as conn:
                    assert execute(conn,'SELECT count(*) FROM ai_usage').scalar_one()==usage_before
                os.environ['AI_PROVIDER'] = 'disabled'
                checks.append('明确Mock经HTTP/队列/详情完整响应，缓存命中，档案和正文改变隔离旧建议，无真实模型/计费')
                api(f'/subscriptions/{sub}', 'PUT', dict(name=marker, rules=rules, enabled=False))
                # 当前筛选批量已读通过真实HTTP持久化，随后到达的提醒不受旧截止标识影响。
                summary=api('/alerts/summary',params=dict(state='unread',type='subscription',includeDemo=True))
                assert summary['unread']>0
                subscription_total_before=api('/alerts/summary',params=dict(type='subscription',includeDemo=True))['total']
                bulk=api('/alerts/read','PUT',params=dict(state='unread',type='subscription',includeDemo=True,throughId=summary['through_id']))
                assert bulk['updated']==summary['unread']
                assert api('/alerts',params=dict(state='unread',type='subscription',includeDemo=True))==[]
                assert api('/alerts/summary',params=dict(type='subscription',includeDemo=True))['total']==subscription_total_before
                checks.append('提醒分类/未读筛选/批量已读持久化与历史保留，CSRF保护继续生效')
                # New job value flow uses explicit synthetic data; never enters real candidates.
                verified={**record,'external_id':marker+'-verified','title':'[合成端到端] 数据开发日常实习',
                    'body':'合成测试岗位：2027届本科在读，数据开发，要求Python。每周到岗3天；实习6个月。',
                    'country':'CN','city':'成都','locations':[], 'student_required':True,'url':f'https://example.com/synthetic/{marker}-verified',
                    'internship_type':'日常','start_date':'2027-03-01','duration_months':6,'days_per_week':3,
                    'source_verified_at':'2026-01-01T00:00:00+08:00','source_verification_note':'合成核验声明；非真实官方核验',
                    'skills':[dict(name='Python',requirement='required',evidence='要求Python')], 'deadline':None}
                assert import_record(verified)['inserted']==1
                assert import_record(verified)['deduplicated']==1
                vid=api('/items',params={**filters,'city':'成都','q':'[合成端到端] 数据开发日常实习'})['items'][0]['id']
                api('/profile','PUT',{**full_profile,'skills':['Python'],'roles':['data_engineering'],'cities':['成都'],'employmentTypes':['internship'],
                    'internshipTypes':['日常'],'internshipStartFrom':'2027-03-01','internshipStartTo':'2027-05-31'})
                api('/matches/refresh','POST',{})
                v=api(f'/items/{vid}')
                assert v['payload']['source_verification_note']==verified['source_verification_note']
                assert v['bachelor_status']=='confirmed' and v['explanation']['targetDirection'] is True
                assert any(q['key']=='internship_start' and q['status']=='confirmed' for q in v['explanation']['qualifications'])
                assert v['provenance'] and v['provenance'][0]['archived_at']
                assert api('/items',params=dict(domain='mainland',view='attention',q=marker,includeDemo=True))['total']==0
                assert api('/items',params=dict(domain='mainland',view='target',q='[合成端到端] 数据开发日常实习',includeDemo=True))['total']==1
                checks.append('官方JD人工核验元数据/春季窗口/目标类型跨HTTP→ETL幂等保留；本科三态与来源可追溯；合成岗位永不进入真实关注候选')
                # 全部仍为is_demo=true；默认演示隔离和有效性用独立订阅逐项验证。
                shanghai_now=datetime.now(ZoneInfo('Asia/Shanghai'))
                for suffix,deadline,status in [('closed',shanghai_now.date()+timedelta(days=3),' CLOSED '),
                                                ('expired',shanghai_now.date()-timedelta(days=1),None),
                                                ('today',shanghai_now.date(),None),('unknown',None,None)]:
                    value={**record,'external_id':marker+'-notification-'+suffix,'title':marker+'-notification-'+suffix,
                           'url':record['url']+'-notification-'+suffix,'deadline':deadline.isoformat() if deadline else None,'status':status}
                    assert import_record(value)['inserted']==1
                default_sub=api('/subscriptions','POST',dict(name=marker+'-default-demo',rules=dict(q=marker+'-notification'),enabled=True))['id']
                active_sub=api('/subscriptions','POST',dict(name=marker+'-active',rules=dict(q=marker+'-notification',includeDemo=True),enabled=True))['id']
                api('/matches/refresh','POST');api('/matches/refresh','POST')
                def notification_alerts(sub_id):
                    return [a for a in api('/alerts') if a['dedup_key'].startswith(f'subscription:{sub_id}:')]
                assert not notification_alerts(default_sub)
                current_alerts=notification_alerts(active_sub)
                assert len(current_alerts)==2
                assert {api(f'/items/{a["item_id"]}')['title'] for a in current_alerts}=={marker+'-notification-today',marker+'-notification-unknown'}
                # 关闭岗位仍在存档，明确面试不会随招聘截止降噪被取消。
                closed_id=api('/items',params=dict(q=marker+'-notification-closed',includeDemo=True))['items'][0]['id']
                api(f'/applications/{closed_id}','PUT',dict(status='interview1',notes='合成已确认日程，无外部投递',interviewAt=(shanghai_now+timedelta(hours=2)).isoformat()))
                api('/matches/refresh','POST')
                closed_alerts=[a for a in api('/alerts') if a['item_id']==closed_id]
                assert len(closed_alerts)==1 and closed_alerts[0]['dedup_key'].startswith('interview_at:')
                checks.append('默认订阅排除演示；显式包含后仍跳过过期/关闭，上海当天与未知保留；关闭岗位不新增截止提醒且已确认面试继续提醒')
                # 仅在隔离测试库模拟生产分类；这些夹具不是供演示浏览的岗位。
                evidence_record={**record,'external_id':marker+'-evidence','url':record['url']+'-evidence',
                    'title':marker+'-evidence','deadline':None,'status':'open','is_demo':False,
                    'source_verified_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    'source_verification_note':'明确合成：人工核对官方职位编号、JD及在列入口，非真实招聘'}
                states=[]
                for patch,expected in [({},'recently_listed'),
                        ({'source_verified_at':(datetime.now(ZoneInfo('Asia/Shanghai'))-timedelta(days=8)).isoformat()},'archived_unknown'),
                        ({'status':None},'pending_review'),({'status':'closed'},'closed')]:
                    import_record({**evidence_record,**patch})
                    listed=api('/items',params=dict(q=marker+'-evidence',includeDemo=True))['items'][0]
                    detail=api('/items/'+str(listed['id']))
                    assert detail['recruitment']==listed['recruitment']
                    assert detail['recruitment']['state']==expected
                    states.append(expected)
                api('/matches/refresh','POST')
                cached=api('/matches/refresh','POST')
                assert cached['computedJobs']==0 and cached['matchWrites']==0
                import_record({**evidence_record,'body':evidence_record['body']+'；合成岗位JD更新'})
                updated_match=api('/matches/refresh','POST')
                assert updated_match['computedJobs']==1 and updated_match['matchWrites']==1
                checks.append('四类逐岗证据状态经真实导入/ETL后列表详情一致；过期核验恢复未知，JD可见不等于在列')
                checks.append('真实HTTP无变化匹配0计算0写入，单条JD更新仅重算写入1条')
                # 成都2028届AI应用JD的实际语言形态；合成记录不代表招聘或个人已符合。
                application_intern=dict(kind='job',external_id=marker+'-application-intern',
                    title='Application Engineer Intern - 2028 Graduates',company=marker,
                    body="Master or bachelor degree in IT related major; Full-time student who will be graduated in 2028; You'll contribute to AI-enabled application features through coding, testing, and debugging.",
                    country='CN',city='成都',employment_type='internship',is_demo=True,
                    url=record['url']+'-application-intern',status='open',
                    source_verified_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    source_verification_note='合成官方在列核验；不证明2027春可申请或两个月获准')
                import_record(application_intern)
                test_profile={**profile,'graduationYear':2028,'roles':['ai'],'cities':['成都'],
                    'currentlyStudying':True,'availableMonths':2,'availableDays':5,
                    'internshipStartFrom':'2027-03-01','internshipStartTo':'2027-05-31'}
                api('/profile','PUT',test_profile);api('/matches/refresh','POST')
                rows=api('/items',params=dict(q=application_intern['title'],includeDemo=True))['items']
                found=next(r for r in rows if r['payload']['url']==application_intern['url'])
                assert found['payload']['graduation_year']==2028 and found['payload']['student_required'] is True
                assert found['bachelor_status']=='confirmed' and found['explanation']['targetDirection'] is True
                assert found['hard_status']=='insufficient_information' and found['recruitment']['state']=='synthetic'
                assert any(q['key']=='internship_start' and q['status']=='unconfirmed' for q in found['explanation']['qualifications'])
                api('/profile','PUT',{**test_profile,'graduationYear':2027});api('/matches/refresh','POST')
                assert api('/items/'+str(found['id']))['hard_status']=='not_eligible'
                checks.append('2028届全日制本科AI应用实习经Java队列/Python正确解析并进入目标方向；春季日期仍未知，错误届别保持硬冲突')
                result = dict(checked_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'), database=url.database, port=port,
                              synthetic=True, external_requests=False, checks=checks, passed=len(checks),
                              source_id=source, item_id=item_id, group_item_id=group_id, experience_item_id=experience_id, alternative_item_id=alternative_id, first=first, repeat=repeated, changed=changed,
                              limitation='隔离合成HTTP链路，不代表真实招聘/投递或Docker部署；仅更新测试档案，不清理正式库。')
                (evidence / 'integration-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
                print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
            db.dispose()


if __name__ == '__main__':
    (ROOT / '.local').mkdir(exist_ok=True)
    main()
