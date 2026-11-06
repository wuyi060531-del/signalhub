"""文档化公开 Posting API；固定域名、PUBLIC、有界完整分页和详情。"""
import re
import time
from urllib.parse import urlencode
from .ashby import CITIES

REGIONS = {'shanghai':'上海','beijing':'北京','jiangsu':'江苏','guangdong':'广东',
           'shandong':'山东','hunan':'湖南','zhejiang':'浙江','sichuan':'四川'}


def is_intern(job):
    return (job.get('typeOfEmployment') or {}).get('id') == 'intern' or bool(
        re.search(r'实习|\bintern(?:ship)?s?\b', job.get('name',''), re.I))


class SmartRecruitersAdapter:
    def __init__(self, sleep=time.sleep):
        self.sleep = sleep

    def fetch(self, config, fetcher, headers):
        board=config.get('board','')
        if not isinstance(board,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',board):
            raise ValueError('SmartRecruiters board格式错误')
        country=config.get('country')
        if country is not None and (not isinstance(country,str) or not re.fullmatch(r'[A-Za-z]{2}',country)):
            raise ValueError('country需为两位国家代码')
        intern_only=config.get('intern_only',False)
        if not isinstance(intern_only,bool):raise ValueError('intern_only需为布尔值')
        keyword=config.get('q')
        if keyword is not None and (not isinstance(keyword,str) or len(keyword)>100):raise ValueError('q需为100字符以内文本')
        max_items=config.get('max_items',100)
        if type(max_items) is not int or not 1<=max_items<=200:raise ValueError('max_items范围1–200')
        root=f'https://api.smartrecruiters.com/v1/companies/{board}/postings'
        # 单页ETag无法代表后续页或详情；每轮新鲜读取，不能错误整源304。
        clean_headers={k:v for k,v in headers.items() if k.lower() not in ('if-none-match','if-modified-since')}
        requests=0
        def get(url):
            nonlocal requests
            if requests:self.sleep(1)  # 最多约1请求/秒，远低于官方10请求/秒。
            requests+=1
            return fetcher.get(url,clean_headers)
        listings={}
        offset=0
        for _ in range(20):
            query={'destination':'PUBLIC','limit':100,'offset':offset}
            if country:query['country']=country.lower()
            if keyword:query['q']=keyword
            response=get(root+'?'+urlencode(query))
            data=response.json();page=data['content'];total=data['totalFound']
            if type(total) is not int or total<0 or not isinstance(page,list):raise ValueError('分页响应格式错误')
            if total>2000:raise ValueError('超过2000条分页边界，请缩小来源国家范围')
            if data.get('offset',offset)!=offset:raise ValueError('服务端分页偏移不一致')
            if not page and offset<total:raise ValueError('未完成快照却返回空页')
            for job in page:
                identifier=str(job.get('uuid') or job.get('id') or '')
                if not re.fullmatch(r'[A-Za-z0-9-]{1,100}',identifier):raise ValueError('职位标识格式错误')
                if identifier in listings:raise ValueError('SmartRecruiters分页重复标识，拒绝不完整快照')
                listings[identifier]=job
            offset+=len(page)
            if offset>=total:break
        else:raise ValueError('分页未在上限内完成')
        selected=[(key,job) for key,job in listings.items() if not intern_only or is_intern(job)]
        if len(selected)>max_items:raise ValueError('详情超过max_items边界，请缩小条件；不会静默截断')
        def records():
            for identifier,listing in selected:
                job=get(root+'/'+identifier).json()
                if job.get('active') is not True or job.get('visibility')!='PUBLIC':continue
                if str(job.get('uuid') or job.get('id'))!=identifier:raise ValueError('详情标识与列表不一致')
                # 列表与详情可能在请求之间变化；实习源不能混入已改为正式工的详情。
                if intern_only and not is_intern(job):continue
                place=job.get('location') or {}
                code=place.get('country')
                code=code.upper() if isinstance(code,str) else None
                if country and code!=country.upper():raise ValueError('列表国家过滤与详情不一致')
                city=place.get('city') or None;province=place.get('region') or None
                if code=='CN':
                    city=CITIES.get(str(city).casefold(),city)
                    province=REGIONS.get(str(province).casefold(),province)
                sections=job.get('jobAd',{}).get('sections',{})
                body='\n'.join('\n'.join((sections.get(key,{}).get('title') or label, sections.get(key,{}).get('text') or ''))
                    for key,label in (('jobDescription','Job Description'),('qualifications','Qualifications'),('additionalInformation','Additional Information')))
                campus=bool(re.search(r'校招|校园招聘|(?<![A-Za-z])campus hiring(?![A-Za-z])|\bgraduate (?:program|programme)\b',job['name'],re.I))
                employment='internship' if is_intern(job) else 'campus' if campus else {'permanent':'full_time','part-time':'other','contract':'other'}.get((job.get('typeOfEmployment') or {}).get('id'))
                yield dict(kind='job',external_id=identifier,title=job['name'],body=body,
                    url=job.get('postingUrl'),company=job.get('company',{}).get('name') or config.get('company',board),
                    company_type=config.get('company_type','unknown'),country=code,city=city,province=province,
                    remote=place.get('remote'),employment_type=employment,published_at=job.get('releasedDate'),
                    _raw={'listing':listing,'detail':job})
        # 不返回某个局部页面的缓存验证器供整个来源使用。
        return records(),None,False
