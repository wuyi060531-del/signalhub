"""一次性只读验证：SmartRecruiters 文档化公开 Posting API。

仅 GET、无认证、约 1 请求/秒（官方上限 10 请求/秒）。不保存响应正文，只打印计数与公开岗位标题。
各类失败（HTTP 状态、超时、连接失败）分别记录，不据此判断平台失效。
用法：python scripts/probe_smartrecruiters.py <companyIdentifier> <国家代码> [详情抽样数]
"""
import collections
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = 'https://api.smartrecruiters.com/v1/companies/'
UA = 'SignalHub/0.1 public-read-only (one-off verification)'
log = []


def get(url):
    started = time.time()
    request = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(8 * 1024 * 1024)
            outcome = (response.status, body)
    except urllib.error.HTTPError as error:
        outcome = (error.code, b'')
    except TimeoutError:
        outcome = ('timeout', b'')
    except (urllib.error.URLError, OSError) as error:
        outcome = ('network_error:' + type(error).__name__, b'')
    log.append({'url': url.split('?')[0].replace(ROOT, ''), 'status': outcome[0], 'seconds': round(time.time() - started, 2)})
    time.sleep(1)
    return outcome


def main():
    board, country = sys.argv[1], sys.argv[2].lower()
    sample = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    result = {'board': board, 'country_filter': country, 'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
    postings, offset, total = [], 0, None
    for _ in range(20):
        query = urllib.parse.urlencode({'destination': 'PUBLIC', 'limit': 100, 'offset': offset, 'country': country})
        status, body = get(f'{ROOT}{board}/postings?{query}')
        if status != 200:
            result['list_error'] = status
            break
        data = json.loads(body)
        total = data.get('totalFound')
        page = data.get('content') or []
        postings.extend(page)
        offset += len(page)
        if not page or offset >= (total or 0):
            break
    result['totalFound'] = total
    result['collected'] = len(postings)
    cities = collections.Counter((p.get('location') or {}).get('city') for p in postings)
    result['countries_in_listing'] = dict(collections.Counter((p.get('location') or {}).get('country') for p in postings))
    result['chengdu'] = sum(n for c, n in cities.items() if c and c.strip().lower() in ('chengdu', '成都', '成都市'))
    result['chongqing'] = sum(n for c, n in cities.items() if c and c.strip().lower() in ('chongqing', '重庆', '重庆市'))
    result['top_cities'] = cities.most_common(12)
    result['employment_types'] = dict(collections.Counter((p.get('typeOfEmployment') or {}).get('id') for p in postings))
    dates = sorted(p['releasedDate'] for p in postings if p.get('releasedDate'))
    result['releasedDate_present'] = len(dates)
    result['releasedDate_range'] = [dates[0], dates[-1]] if dates else None
    intern = [p for p in postings if (p.get('typeOfEmployment') or {}).get('id') == 'intern'
              or re.search(r'实习|\bintern(?:ship)?s?\b', p.get('name', ''), re.I)]
    result['intern_count'] = len(intern)
    # 标题关键词只是候选线索，不是匹配度。
    keywords = {'data': r'数据|\bdata\b|大数据|ETL|BI\b', 'java_backend': r'\bjava\b|后端|backend|back-end', 'ai': r'\bAI\b|人工智能|机器学习|大模型|LLM|算法|machine learning'}
    result['title_keyword_candidates'] = {k: sum(1 for p in postings if re.search(v, p.get('name', ''), re.I)) for k, v in keywords.items()}
    result['intern_postings'] = [{'title': p.get('name'), 'city': (p.get('location') or {}).get('city'),
                                  'releasedDate': p.get('releasedDate'), 'id': p.get('id')} for p in intern[:40]]
    # 接口自带的全文检索（q）直接查实习，不依赖本地分页是否完整。
    result['q_search'] = {}
    for keyword in ('intern', '实习'):
        status, body = get(f"{ROOT}{board}/postings?{urllib.parse.urlencode({'destination': 'PUBLIC', 'limit': 100, 'country': country, 'q': keyword})}")
        if status != 200:
            result['q_search'][keyword] = {'error': status}
            continue
        data = json.loads(body)
        result['q_search'][keyword] = {'totalFound': data.get('totalFound'), 'postings': [
            {'title': p.get('name'), 'city': (p.get('location') or {}).get('city'), 'type': (p.get('typeOfEmployment') or {}).get('id'),
             'releasedDate': p.get('releasedDate')} for p in (data.get('content') or [])[:40]]}
    # 详情字段抽样：优先实习岗位，只记录字段是否存在，不保存正文。
    checks = []
    for p in (intern or postings)[:sample]:
        status, body = get(f"{ROOT}{board}/postings/{p['id']}")
        if status != 200:
            checks.append({'id': p['id'], 'status': status})
            continue
        d = json.loads(body)
        sections = (d.get('jobAd') or {}).get('sections') or {}
        checks.append({'id': p['id'], 'status': 200, 'active': d.get('active'), 'visibility': d.get('visibility'),
                       'has_postingUrl': bool(d.get('postingUrl')), 'postingUrl_host': urllib.parse.urlsplit(d.get('postingUrl') or '').hostname,
                       'releasedDate': d.get('releasedDate'), 'location_country': (d.get('location') or {}).get('country'),
                       'section_keys': sorted(sections), 'body_chars': sum(len((s or {}).get('text') or '') for s in sections.values())})
    result['detail_checks'] = checks
    result['requests'] = log
    print('RESULT ' + json.dumps(result, ensure_ascii=False))


main()
