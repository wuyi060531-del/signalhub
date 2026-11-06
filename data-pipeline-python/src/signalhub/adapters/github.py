import re
import os

class GithubAdapter:
    def fetch(self, config, fetcher, headers):
        repo = config.get('repo', '')
        if not re.fullmatch(r'[\w.-]+/[\w.-]+',repo): raise ValueError('repo 格式 owner/name')
        # 第一页的验证器不能证明其他页 Release 正文未变；沿用有界分页，逐页新鲜读取。
        headers = {k:v for k,v in headers.items() if k.lower() not in ('if-none-match','if-modified-since')}
        headers.update({'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28'})
        if os.getenv('GITHUB_TOKEN'): headers['Authorization'] = 'Bearer '+os.environ['GITHUB_TOKEN']
        first = fetcher.get(f'https://api.github.com/repos/{repo}/releases?per_page=100',headers)
        records = list(first.json())
        # 限制为最多五页；不会根据远程 Link 任意跳转请求。
        for page in range(2,6):
            if len(records) < (page-1)*100: break
            response = fetcher.get(f'https://api.github.com/repos/{repo}/releases?per_page=100&page={page}', headers)
            records.extend(response.json())
        return [dict(kind='release',external_id=str(x['id']),title=f"{repo} · {x['tag_name']}",url=x['html_url'],body=x.get('body') or '',company=repo,version_tag=x['tag_name'],published_at=x.get('published_at'),_raw=x) for x in records if not x.get('draft')], None, False
