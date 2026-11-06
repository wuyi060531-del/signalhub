from urllib.parse import urlsplit
from datetime import datetime, timezone
import os
import feedparser
from defusedxml.ElementTree import fromstring

class RssAdapter:
    def fetch(self, config, fetcher, headers):
        url = config.get('url','')
        allowed = set(os.getenv('RSS_ALLOWED_HOSTS','github.blog,www.python.org').split(','))
        if urlsplit(url).hostname not in allowed: raise ValueError('RSS 主机未列入 RSS_ALLOWED_HOSTS 许可清单')
        response = fetcher.get(url,headers)
        if response.status_code == 304: return [],response,True
        fromstring(response.content)  # 禁止 DTD/实体；失败不保存 ETag。
        feed = feedparser.parse(response.content)
        if feed.bozo: raise ValueError('RSS/Atom 解析失败')
        records = []
        for entry in feed.entries:
            date = entry.get('published_parsed')
            body = entry.get('content', [{}])[0].get('value') or entry.get('summary','')
            # 留存完整 entry，而非仅保存已经裁剪过的规范输入。
            records.append(dict(kind=config.get('kind','opportunity'),external_id=entry.get('id') or entry.get('link') or entry['title'],title=entry['title'],url=entry.get('link'),body=body,company=config.get('organizer'),published_at=datetime(*date[:6],tzinfo=timezone.utc).isoformat() if date else None,_raw=dict(entry)))
        return records,response,False
