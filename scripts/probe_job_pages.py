"""一次性只读核实：少量官方招聘详情页（每页 1 次 GET，先读并遵守 robots.txt）。

只抽取页面自带的 JobPosting 结构化数据（标题、发布日期、有效期、地点、雇佣类型、描述节选），
并记录 HTTP 状态、重定向后的最终地址。各类失败分别记录，不据此判断岗位或平台失效。
用法：python scripts/probe_job_pages.py URL [URL ...]
"""
import datetime
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

UA = 'SignalHub/0.1 public-read-only (one-off job page verification)'
robots = {}


def fetch(url, limit=2 * 1024 * 1024):
    request = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, response.geturl(), response.read(limit).decode('utf-8', 'replace')
    except urllib.error.HTTPError as error:
        return error.code, url, ''
    except TimeoutError:
        return 'timeout', url, ''
    except (urllib.error.URLError, OSError) as error:
        return 'network_error:' + type(error).__name__, url, ''


def allowed(url):
    host = urllib.parse.urlsplit(url)
    base = f'{host.scheme}://{host.netloc}'
    if base not in robots:
        parser = urllib.robotparser.RobotFileParser()
        status, _, body = fetch(base + '/robots.txt', 256 * 1024)
        time.sleep(1)
        if status == 200:
            parser.parse(body.splitlines())
            robots[base] = parser
        elif isinstance(status, int) and 400 <= status < 500:
            robots[base] = None  # 无 robots 规则
        else:
            robots[base] = False  # 无法确认访问策略，不请求该站
    parser = robots[base]
    return parser is None or (parser is not False and parser.can_fetch(UA, url))


def job_postings(page):
    found = []
    for raw in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if item.get('@type') == 'JobPosting':
                    found.append(item)
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return found


def text(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', value or ''))).strip()


for url in sys.argv[1:]:
    row = {'url': url, 'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
    if not allowed(url):
        row['skipped'] = 'robots.txt 不允许或无法确认'
    else:
        status, final, page = fetch(url)
        time.sleep(1)
        row.update(status=status, final_url=final, redirected=(final != url))
        row['page_title'] = text((re.search(r'<title[^>]*>(.*?)</title>', page, re.S | re.I) or [None, ''])[1])[:160]
        postings = job_postings(page)
        row['jobposting_count'] = len(postings)
        if postings:
            p = postings[0]
            locs = p.get('jobLocation') or []
            locs = locs if isinstance(locs, list) else [locs]
            row['jobposting'] = {
                'title': p.get('title'), 'datePosted': p.get('datePosted'), 'validThrough': p.get('validThrough'),
                'employmentType': p.get('employmentType'), 'organization': (p.get('hiringOrganization') or {}).get('name'),
                'locations': [(l.get('address') or {}).get('addressLocality') or (l.get('address') or {}).get('addressRegion') for l in locs if isinstance(l, dict)],
                'countries': [(l.get('address') or {}).get('addressCountry') for l in locs if isinstance(l, dict)],
                'identifier': (p.get('identifier') or {}).get('value') if isinstance(p.get('identifier'), dict) else p.get('identifier'),
                'description_excerpt': text(p.get('description'))[:2200]}
    print('RESULT ' + json.dumps(row, ensure_ascii=False))
