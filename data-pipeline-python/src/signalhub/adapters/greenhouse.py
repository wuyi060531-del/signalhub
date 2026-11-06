import re

class GreenhouseAdapter:
    def fetch(self, config, fetcher, headers):
        board = config.get('board','')
        if not re.fullmatch(r'[\w-]+',board): raise ValueError('board 格式错误')
        response = fetcher.get(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true', headers)
        if response.status_code == 304: return [],response,True
        jobs = response.json()['jobs']
        # 不把 updated_at 当作首次发布时间，不从自由文本 location 推测国家。
        records = [dict(kind='job',external_id=str(x['id']),title=x['title'],body=x.get('content') or '',url=x['absolute_url'],company=config.get('company',board),company_type=config.get('company_type','unknown'),country=config.get('country'),city=x.get('location',{}).get('name'),_raw=x) for x in jobs]
        return records,response,False
