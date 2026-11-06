"""Ashby 文档化公开 Job Postings API；仅公开列出的职位，无私人接口/账号。"""
import re
from urllib.parse import urlsplit
from ..models import Salary

COUNTRIES = {
    'china':'CN','chn':'CN','cn':'CN','united states':'US','usa':'US','us':'US',
    'singapore':'SG','sgp':'SG','sg':'SG','hong kong':'HK','hkg':'HK','hk':'HK',
    'united kingdom':'GB','gbr':'GB','gb':'GB','australia':'AU','aus':'AU','au':'AU',
    'canada':'CA','can':'CA','netherlands':'NL','nld':'NL','india':'IN','ind':'IN',
    'france':'FR','fra':'FR','japan':'JP','jpn':'JP','new zealand':'NZ','nzl':'NZ',
    'vietnam':'VN','vnm':'VN','mexico':'MX','mex':'MX','south korea':'KR','kor':'KR',
    'germany':'DE','deu':'DE','sweden':'SE','swe':'SE','malaysia':'MY','mys':'MY',
    'indonesia':'ID','idn':'ID','spain':'ES','esp':'ES','israel':'IL','isr':'IL',
    'brazil':'BR','bra':'BR','united arab emirates':'AE','are':'AE','lithuania':'LT','ltu':'LT'
}
CITIES = {'shanghai':'上海','beijing':'北京','shenzhen':'深圳','guangzhou':'广州',
          'hangzhou':'杭州','chengdu':'成都','nanjing':'南京','suzhou':'苏州','wuhan':'武汉','tianjin':'天津'}


def location(entry, primary=False):
    address=entry.get('address') or {}
    postal=address.get('postalAddress',address)
    country=postal.get('addressCountry') or None
    # 只转写官方结构化国家字段，不根据 location 文本推断。
    code=COUNTRIES.get(str(country).casefold(),country)
    city=postal.get('addressLocality') or None
    province=postal.get('addressRegion') or None
    if code=='CN':
        city=CITIES.get(str(city).casefold(),city)
        province=CITIES.get(str(province).casefold(),province)
    return {'name':entry.get('location'),'country':code,'city':city,'province':province,'primary':primary}


class AshbyAdapter:
    def fetch(self, config, fetcher, headers):
        board=config.get('board','')
        if not isinstance(board,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',board):
            raise ValueError('Ashby board格式错误')
        response=fetcher.get(f'https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true',headers)
        if response.status_code==304:return [],response,True
        records=[]
        for job in response.json()['jobs']:
            if job.get('isListed') is not True:continue  # 不展示只应通过直接链接访问的非列表职位。
            url=job.get('jobUrl') or job.get('applyUrl')
            identifier=job.get('id') or (urlsplit(url).path.rstrip('/').split('/')[-1] if url else '')
            locations=[location(job,True),*[location(x) for x in job.get('secondaryLocations',[])]]
            primary=locations[0]
            kind={'FullTime':'full_time','Intern':'internship','PartTime':'other','Contract':'other','Temporary':'other'}.get(job.get('employmentType'))
            compensation=job.get('compensation') or {}
            salary=Salary(raw=compensation.get('scrapeableCompensationSalarySummary') or compensation.get('compensationTierSummary')).model_dump()
            # 多地域待遇信息保持原文，不从混合薪资区间推断统一币种/周期。
            records.append(dict(kind='job',external_id=str(identifier),title=job['title'],url=url,
                body=job.get('descriptionPlain') or job.get('descriptionHtml') or '',
                company=config.get('company',board),company_type=config.get('company_type','unknown'),
                country=primary['country'],city=primary['city'],province=primary['province'],locations=locations,
                remote=job.get('isRemote'),employment_type=kind,published_at=job.get('publishedAt'),
                salary=salary,_raw=job))
        return records,response,False
