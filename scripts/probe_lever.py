"""一次性只读验证：Lever 文档化公开 Postings API（GET /v0/postings/SITE?mode=json）。

仅一次 GET、无认证；不保存正文，只打印计数、公开标题和字段是否存在。
用法：python scripts/probe_lever.py <site>
"""
import collections
import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

site = sys.argv[1]
url = f'https://api.lever.co/v0/postings/{site}?mode=json'
result = {'site': site, 'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
request = urllib.request.Request(url, headers={'User-Agent': 'SignalHub/0.1 public-read-only (one-off verification)', 'Accept': 'application/json'})
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        result['status'] = response.status
        data = json.loads(response.read(8 * 1024 * 1024))
except urllib.error.HTTPError as error:
    result['status'] = error.code
    data = None
except TimeoutError:
    result['status'] = 'timeout'
    data = None
except (urllib.error.URLError, OSError) as error:
    result['status'] = 'network_error:' + type(error).__name__
    data = None
if isinstance(data, list):
    result['total'] = len(data)
    result['field_names'] = sorted({key for item in data for key in item})
    result['countries'] = dict(collections.Counter(item.get('country') for item in data))
    result['commitments'] = dict(collections.Counter((item.get('categories') or {}).get('commitment') for item in data))
    result['locations'] = collections.Counter((item.get('categories') or {}).get('location') for item in data).most_common(15)
    result['has_hostedUrl'] = sum(1 for item in data if item.get('hostedUrl'))
    result['has_createdAt'] = sum(1 for item in data if item.get('createdAt'))
    result['postings_cn_or_intern'] = [
        {'title': item.get('text'), 'location': (item.get('categories') or {}).get('location'),
         'all_locations': (item.get('categories') or {}).get('allLocations'), 'commitment': (item.get('categories') or {}).get('commitment'),
         'team': (item.get('categories') or {}).get('team'), 'country': item.get('country'),
         'workplaceType': item.get('workplaceType'), 'hostedUrl': item.get('hostedUrl'), 'createdAt': item.get('createdAt')}
        for item in data
        if item.get('country') == 'CN' or 'intern' in str((item.get('categories') or {}).get('commitment') or '').lower()
        or 'intern' in (item.get('text') or '').lower()]
print('RESULT ' + json.dumps(result, ensure_ascii=False))
