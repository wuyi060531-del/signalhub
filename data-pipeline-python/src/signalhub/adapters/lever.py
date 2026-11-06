"""Lever 文档化公开 Postings GET：完整有界分页，不访问候选人/投递接口。"""
import re
import time
from urllib.parse import urlencode
from .ashby import CITIES
from ..normalize import clean


def body_of(job):
    # 列表接口已经包含完整正文；保留要求/加分段落标题供规则识别。
    sections = [job.get('description') or job.get('descriptionPlain') or '']
    for section in job.get('lists') or []:
        sections.extend([section.get('text') or '', section.get('content') or ''])
    sections.append(job.get('additional') or job.get('additionalPlain') or '')
    if job.get('salaryDescriptionPlain'):
        sections.append(job['salaryDescriptionPlain'])
    return '\n'.join(sections)


def internship_evidence(job):
    # 某些正式/校招岗位被平台误标 Internship，严格实习源要求额外文字证据。
    body = clean(body_of(job))
    if re.search(r'非实习|不招.{0,8}实习|not (?:an? )?internship|not (?:tied to|part of) any hiring process', body, re.I):
        return False
    return bool(re.search(r'实习|\bintern(?:ship)?s?\b', job.get('text', ''), re.I)
                or re.search(r'(?:this|the) internship (?:is|role)|internship (?:position|role)|(?:招聘|招募).{0,8}实习生', body, re.I))


class LeverAdapter:
    def __init__(self, sleep=time.sleep):
        self.sleep = sleep

    def fetch(self, config, fetcher, headers):
        board = config.get('board', '')
        if not isinstance(board, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', board):
            raise ValueError('Lever board格式错误')
        country = config.get('country')
        if country is not None and (not isinstance(country, str) or not re.fullmatch(r'[A-Za-z]{2}', country)):
            raise ValueError('country需为两位国家代码')
        commitment = config.get('commitment')
        if commitment is not None and (not isinstance(commitment, str) or not commitment.strip() or len(commitment) > 100):
            raise ValueError('commitment需为1–100字符文本')
        intern_only = config.get('intern_only', False)
        if not isinstance(intern_only, bool):
            raise ValueError('intern_only需为布尔值')
        maximum = config.get('max_items', 100)
        if type(maximum) is not int or not 1 <= maximum <= 200:
            raise ValueError('max_items范围1–200')
        # 单页缓存无法证明整个来源未变化。country不是Lever可用的服务端过滤参数。
        request_headers = {k: v for k, v in headers.items() if k.lower() not in ('if-none-match', 'if-modified-since')}
        root = f'https://api.lever.co/v0/postings/{board}'
        listings = {}
        offset = 0
        for page_number in range(20):
            if page_number:
                self.sleep(1)
            query = dict(mode='json', limit=100, skip=offset)
            if commitment:
                query['commitment'] = commitment
            page = fetcher.get(root + '?' + urlencode(query), request_headers).json()
            if not isinstance(page, list) or len(page) > 100:
                raise ValueError('Lever分页格式错误')
            for job in page:
                identifier = job.get('id') if isinstance(job, dict) else None
                if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}', identifier):
                    raise ValueError('Lever职位标识格式错误')
                if identifier in listings:
                    raise ValueError('Lever分页重复标识，拒绝不完整快照')
                listings[identifier] = job
            offset += len(page)
            if len(page) < 100:
                break
        else:
            raise ValueError('Lever分页未在2000条边界内完成，请缩小commitment条件')
        records = []
        for identifier, job in listings.items():
            code = job.get('country')
            code = code.upper() if isinstance(code, str) and re.fullmatch(r'[A-Za-z]{2}', code) else None
            if country and code != country.upper():
                continue
            intern = internship_evidence(job)
            if intern_only and not intern:
                continue
            categories = job.get('categories') or {}
            label = categories.get('location')
            # 只转写明确的结构地点标签，国家始终来自country；不由雇主或标题猜。
            city = None
            if code == 'CN' and isinstance(label, str):
                match = re.fullmatch(r'China\s*-\s*([A-Za-z ]+)', label, re.I)
                city = CITIES.get(match[1].strip().casefold()) if match else CITIES.get(label.casefold())
            locations = [dict(name=label, country=code, city=city, primary=True)]
            for other in dict.fromkeys(categories.get('allLocations') or []):
                if other != label:
                    locations.append(dict(name=other, country=None, city=None, primary=False))
            work = job.get('workplaceType')
            remote = True if work == 'remote' else False if work in ('on-site', 'onsite', 'hybrid') else None
            notes = []
            if categories.get('commitment') == 'Internship' and not intern:
                notes.append('平台标记Internship，但标题/正文未确认实习性质；需人工核验')
            employment = 'internship' if intern else {'Full-time': 'full_time', 'Part-time': 'other', 'Contract': 'other'}.get(categories.get('commitment'))
            records.append(dict(kind='job', external_id=identifier, title=job['text'], body=body_of(job),
                                url=job.get('hostedUrl'), company=config.get('company', board),
                                company_type=config.get('company_type', 'unknown'), country=code, city=city,
                                locations=locations, remote=remote, employment_type=employment,
                                risk_notes=notes, _raw=job))
        if len(records) > maximum:
            raise ValueError('Lever职位超过max_items；不会静默截断')
        # createdAt不是文档化的发布日期；不填published_at，也不推断招聘届别。
        return records, None, False
