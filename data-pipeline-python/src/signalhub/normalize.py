"""保守规则提取：只根据明确原文填写字段，不以当前年份推断届别。"""
import re
import hashlib
import json
import html
from datetime import date
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup
from .models import Item, Skill, SkillGroup, Salary, ExperienceRequirement

def token(pattern):
    # 中文与英文技能相邻时仍需命中；ASCII字母/数字/下划线边界防JavaScript误判Java。
    return r'(?<![A-Za-z0-9_])(?:'+pattern+r')(?![A-Za-z0-9_])'

SKILLS = {
 'C++': token(r'c\+\+'), 'C': r'(?<![A-Za-z0-9_])c(?![A-Za-z0-9_+])', 'Go': token(r'(?-i:Go)|golang'),
 'Python': token(r'python'), 'Java': token(r'java'), 'SQL': token(r'sql'),
 'Spring Boot': token(r'spring[ -]?boot'), 'Spark': token(r'(?:apache )?spark'),
 'Kafka': token(r'kafka'), 'Linux': token(r'linux'), 'Docker': token(r'docker'),
 'Airflow': token(r'airflow'), 'Pandas': token(r'pandas'),
 '数据仓库': r'数据仓库|数仓|data warehouse', '机器学习': r'机器学习|machine learning',
 'LLM': token(r'llms?')+r'|大语言模型', 'RAG': token(r'rag')+r'|检索增强生成',
 'PostgreSQL': token(r'postgres(?:ql)?'), 'MySQL': token(r'mysql')
}

ROLES = {
 'data_engineering': r'数据开发|数据工程|大数据|data engineer|big data',
 'java_backend': token(r'java')+r'|后端|backend', 'python': token(r'python'),
 'data_analysis': r'数据分析|data analyst',
 'ai': token(r'ai|llm|rag')+r'|人工智能|机器学习|machine learning',
 'software': r'software engineer|软件工程|software developer'
}

def clean(text):
    # Greenhouse 的 content 可能是实体编码的 HTML；只有限次解码，不执行内容。
    decoded = str(text)
    for _ in range(3):
        value = html.unescape(decoded)
        if value == decoded: break
        decoded = value
    if '<' not in decoded:
        value = re.sub(r'\s+', ' ', decoded).strip(' ；')
        return re.sub(r'\s*；(?:\s*；)*\s*', '；', value)
    soup = BeautifulSoup(decoded, 'html.parser')
    for el in soup(['script', 'style', 'noscript', 'template']):
        el.decompose()
    for el in soup.find_all(['p', 'li', 'div', 'h1', 'h2', 'h3', 'br']):
        el.append('；')
    value = re.sub(r'\s+', ' ', soup.get_text(' ', strip=True)).strip(' ；')
    return re.sub(r'\s*；(?:\s*；)*\s*', '；', value)

def explicit_date(text, labels):
    """只识别带语义标签及完整年份的日期；不拿发布时间推断截止日。"""
    prefix = r'(?:'+labels+r')\s*(?:日期|时间|on)?\s*[:：]?\s*'
    months = {name.lower(): n for n, names in enumerate([
        ('Jan', 'January'), ('Feb', 'February'), ('Mar', 'March'), ('Apr', 'April'),
        ('May',), ('Jun', 'June'), ('Jul', 'July'), ('Aug', 'August'),
        ('Sep', 'Sept', 'September'), ('Oct', 'October'), ('Nov', 'November'), ('Dec', 'December')], 1) for name in names}
    month = r'('+'|'.join(sorted(months, key=len, reverse=True))+r')\.?'
    candidates = []
    for match in re.finditer(prefix+r'(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})日?', text, re.I):
        candidates.append(tuple(map(int, match.groups())))
    for match in re.finditer(prefix+r'(\d{1,2})(?:st|nd|rd|th)?\s+'+month+r'\s+(20\d{2})\b', text, re.I):
        day, name, year = match.groups(); candidates.append((int(year), months[name.lower()], int(day)))
    for match in re.finditer(prefix+month+r'\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b', text, re.I):
        name, day, year = match.groups(); candidates.append((int(year), months[name.lower()], int(day)))
    try:
        dates = {date(*values) for values in candidates}
    except ValueError:
        return None
    # 多个冲突日期不能任选一个；时间/时区原文仍保留，模型只支持日期。
    return dates.pop() if len(dates) == 1 else None

NEGATIVE_PREFIX = re.compile(r'(?:不(?:强制)?要求|无需|不需要|不涉及|not require[ds]?|not necessary to have|no (?:prior |previous )?experience (?:in|with)|no (?:requirement|need)(?: for)?)\s*[:：]?\s*(?:熟悉|掌握|具备|有|any|experience (?:in|with))?\s*',re.I)
SKILL_NAMES = re.compile('|'.join('(?:'+pattern+')' for pattern in SKILLS.values()),re.I)

def skill_list_only(value):
    """否定范围只跨明确技能列表，不跨“掌握/要求”等新的谓词。"""
    rest=SKILL_NAMES.sub('',value)
    rest=re.sub(r'\b(?:and|or|either|one|of|experience|in|with)\b|[\s,，、/&]|和|与|及|或|经验','',rest,flags=re.I)
    return not rest

COUNT = {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
         'one':1,'two':2,'three':3}
ALTERNATIVE = re.compile(r'任意\s*([一二两三四五六七八九十\d]+)\s*(?:种|项|门)|任选\s*([一二两三四五六七八九十\d]+)?|其中\s*([一二两三四五六七八九十\d]+)(?:种|项|门)|至少\s*([一二两三四五六七八九十\d]+)(?:种|项|门)|\b(?:at least\s+(one|two|three|\d+)|one or more|either|one of|or)\b|或',re.I)
PREFERRED = re.compile(r'优先|加分|preferred|nice.to.have|bonus|\badvantage\b|\bplus\b',re.I)
REQUIRED = re.compile(r'要求|必须|熟悉|掌握|required|must|proficien|familiar with',re.I)



def alternative_choice(evidence):
    for choice in ALTERNATIVE.finditer(evidence):
        if choice.group().lower() in ('or','或'):
            before=evidence[:choice.start()].rstrip(' ,，、')
            after=evidence[choice.end():].lstrip(' ,，、')
            # 普通叙述中的 or 不能改变整句技能性质，至少一侧须紧邻技能。
            if not (re.search('(?:'+SKILL_NAMES.pattern+')$',before,re.I) or SKILL_NAMES.match(after)):
                continue
        return choice
    for separator in re.finditer(r'/',evidence):
        before=evidence[:separator.start()].rstrip()
        after=evidence[separator.end():].lstrip()
        if re.search('(?:'+SKILL_NAMES.pattern+')$',before,re.I) or SKILL_NAMES.match(after):
            return separator  # 裸斜杠可能是任选或组合，只标待核验，不猜最低数量。
    return None


def skill_clauses(body):
    """句边界及明显的新要求/加分子句；保留列表逗号。标题只影响后续段落。"""
    context = None
    for sentence in re.split(r'[。；;\n]|(?<=[.!?])\s+', body):
        sentence=sentence.strip()
        heading=sentence.strip('*# ')
        if re.fullmatch(r'(?:requirements|qualifications|required (?:skills(?: and experience)?|qualifications)|minimum qualifications|the must.haves|任职要求|职位要求|必备条件)\s*[:：]?',heading,re.I):
            context='required';continue
        if re.fullmatch(r'(?:preferred qualifications|nice to have|the nice.to.haves|加分条件)\s*[:：]?',heading,re.I):
            context='preferred';continue
        if re.fullmatch(r'(?:job description|additional information|perks.{0,5}benefits|what you.ll do|职位描述|工作职责|其他信息|公司描述)\s*[:：]?',heading,re.I):
            context=None;continue
        boundary=r'[,，]\s*(?=(?:'+SKILL_NAMES.pattern+r')\s*(?:优先|加分|必需|必须|(?:is )?required|preferred))'
        sentence=re.sub(boundary,'；',sentence,flags=re.I)
        for clause in re.split(r'[；]|[,，]\s*(?=(?:必须|要求|掌握|熟悉|prior knowledge|nice.to.have|preferred|有.{0,12}经验优先))',sentence,flags=re.I):
            if clause.strip():yield clause.strip(),context


def positive_occurrences(sentence, pattern):
    for match in re.finditer(pattern,sentence,re.I):
        before,after=sentence[:match.start()],sentence[match.end():]
        prefixes=list(NEGATIVE_PREFIX.finditer(before))
        negated=bool(prefixes and skill_list_only(before[prefixes[-1].end():]))
        negated=negated or bool(re.search(r'^\s*(?:不属于.{0,15}要求|不是.{0,15}要求|(?:is\s+)?not (?:required|necessary)|is not a requirement)',after,re.I))
        trailing=re.search(r'\b(?:are|is)\s+not (?:required|necessary|mandatory|a prerequisite)\b',after,re.I)
        if trailing and skill_list_only(after[:trailing.start()]):negated=True
        if not negated:yield match


def extract_skill_groups(body):
    result=[]
    for evidence,context in skill_clauses(body):
        choice=alternative_choice(evidence)
        if not choice:continue
        if choice.group()=='/':continue
        if not (REQUIRED.search(evidence) or PREFERRED.search(evidence) or context or re.search(r'任选|任意|其中|至少',evidence)):
            continue
        if re.search(r'\band\b|和|与|及',evidence,re.I) and re.search(r'\bor\b|或',evidence,re.I):continue
        count=next((x for x in choice.groups() if x),None)
        minimum=COUNT.get(str(count).lower(),int(count) if count and count.isdigit() else 1)
        matches=sorted((m.start(),m.end(),name) for name,pattern in SKILLS.items() for m in positive_occurrences(evidence,pattern))
        names=list(dict.fromkeys(x[2] for x in matches))
        if len(names)<2 or minimum>len(names):continue
        # 不把未支持的 Rust 等选项悄悄丢弃，再声称已解析整组。
        prefix=evidence[:matches[0][0]]
        if re.search(r'\b[A-Za-z]+\s*[,/、]\s*$',prefix) and not re.search(r'(?:languages?|such as)\s*,\s*$',prefix,re.I):continue
        listing=evidence[matches[0][0]:matches[-1][1]]
        rest=SKILL_NAMES.sub('',listing)
        rest=re.sub(r'\b(?:and|or)\b|[\s,，、/&()]|和|与|及|或','',rest,flags=re.I)
        if rest:continue
        tail=evidence[matches[-1][1]:]
        if re.match(r'\s*[,/、]\s*(?:(?:or|and)\s+)?[A-Za-z]',tail,re.I):continue
        result.append(SkillGroup(names=names,minimum=minimum,requirement='preferred' if PREFERRED.search(evidence) or context=='preferred' else 'required',evidence=evidence))
    return result


def extract_skills(body):
    result=[]
    clauses=list(skill_clauses(body))
    for name,pattern in SKILLS.items():
        candidates=[]
        for evidence,context in clauses:
            occurrences=list(positive_occurrences(evidence,pattern))
            if not occurrences:continue
            preferred=bool(PREFERRED.search(evidence)) or context=='preferred'
            required=bool(REQUIRED.search(evidence)) or context=='required'
            willingness=all(re.search(r'willing to (?:learn|work (?:on|with))\s+(?:the\s+)?$',evidence[:m.start()],re.I) for m in occurrences)
            if alternative_choice(evidence) or willingness:
                requirement='mentioned'  # 组作为独立条件，避免每个选项再被重复计分。
            else:requirement='preferred' if preferred else 'required' if required else 'mentioned'
            candidates.append(Skill(name=name,requirement=requirement,evidence=evidence))
        if candidates:result.append(min(candidates,key=lambda x:{'required':0,'preferred':1,'mentioned':2}[x.requirement]))
    return result

def parse_salary(text):
    salary = Salary(raw='面议' if text and '面议' in text else None)
    if not text or '面议' in text:
        return salary
    expression = text
    # 中文 N 薪形式明确表示按月发放的年内薪数；不与日薪或年薪做换算。
    if re.search(r'[kK万]\s*[·・]\s*\d+\s*薪', expression):
        expression = re.sub(r'([kK万])\s*[·・]', r'\1/月·', expression)
    pattern = r'(\d+(?:\.\d+)?)\s*([kK万]?)\s*(?:[–—~至-]\s*(\d+(?:\.\d+)?)\s*([kK万]?))?\s*(?:元)?\s*(?:/|每)?\s*(天|日|月|年|小时|hour|month|year|day)'
    match = next((m for m in re.finditer(pattern, expression, re.I) if re.search(r'[kK万元/]|每', m.group())), None)
    if not match:
        return salary
    low, unit, high, high_unit, period = match.groups()
    unit = unit or high_unit or ''
    multiplier = lambda u: 1000 if u.lower() == 'k' else 10000 if u == '万' else 1
    salary.minimum = float(low) * multiplier(unit)
    salary.maximum = float(high or low) * multiplier(high_unit or unit)
    salary.currency = 'CNY' if re.search(r'元|薪|天|月|年', match.group()) else None
    salary.period = {'天':'day','日':'day','月':'month','年':'year','小时':'hour','hour':'hour','month':'month','year':'year','day':'day'}[period.lower()]
    salary.raw = match.group()
    months = re.search(r'(\d+)\s*薪', text)
    salary.months = int(months[1]) if months else None
    return salary


def extract_experience(body):
    """只提取明确经验年数。总工作年数不能替代特定领域/项目经历。"""
    result=[]
    number=r'\d+(?:\.\d+)?'
    patterns=[
        re.compile(r'(?:(?:至少|不少于|最多|不超过)\s*)?'+number+r'\s*(?:[-–至]\s*'+number+r')?\s*(?:年及以上|年以上|年以内|年以下|年)\s*(?:的)?\s*(?:相关)?(?:工作|专业|行业|开发)?经验',re.I),
        re.compile(r'(?:工作经验|工作经历)\s*[:：]?\s*(?:(?:至少|不少于|最多|不超过)\s*)?'+number+r'\s*(?:[-–至]\s*'+number+r')?\s*(?:年以上|年以下|年以内|年)',re.I),
        re.compile(r'(?:(?:at least|minimum(?: of)?|up to|at most|no more than)\s*)?'+number+r'\s*(?:[-–]\s*'+number+r')?\+?\s*years?\s+(?:of\s+)?(?:(?:professional|work|relevant|hands-on|software engineering)\s+)*(?:experience)',re.I),
    ]
    for evidence,context in skill_clauses(body):
        if not (context or REQUIRED.search(evidence) or PREFERRED.search(evidence) or re.search(r'工作(?:经验|经历)\s*[:：]',evidence)):
            continue
        if re.search(r'无需.{0,15}经验|无.{0,10}经验要求|no .{0,20}experience.{0,12}(?:required|necessary)|experience.{0,10}not required',evidence,re.I):
            continue
        for pattern in patterns:
            for match in pattern.finditer(evidence):
                phrase=match.group();values=list(map(float,re.findall(number,phrase)))
                if any(v>60 for v in values):continue
                lower,upper=values[0],values[1] if len(values)>1 else None
                if upper is None and re.search(r'最多|不超过|年以内|年以下|up to|at most|no more than',phrase,re.I):
                    lower,upper=None,lower
                if lower is not None and upper is not None and lower>upper:continue
                explicit_work=bool(re.search(r'工作|professional|\bwork\b',phrase,re.I))
                domain=bool(re.search(r'相关|行业|开发|relevant|software engineering',phrase,re.I)
                            or re.match(r'\s+(?:in|with)\s+',evidence[match.end():],re.I))
                # 明示项目/研究/实习年数不自动等同工作经验。
                scope='related' if domain else 'work' if explicit_work else 'unspecified'
                suffix=re.split(r'[（(；;,，]',evidence[match.end():],maxsplit=1)[0]
                preferred=context=='preferred' or bool(PREFERRED.search(evidence[:match.end()])) or bool(re.match(r'\s*(?:者)?\s*(?:优先|加分|preferred|is preferred)',suffix,re.I))
                condition=ExperienceRequirement(minimum_years=lower,maximum_years=upper,
                    requirement='preferred' if preferred else 'required',
                    scope=scope,evidence=evidence)
                if condition not in result:result.append(condition)
    return result

def normalize(raw):
    data = dict(raw)
    # 保留句子边界，便于区分 required 与 preferred。
    original = str(data.get('body') or '')
    body = clean(original.replace('\n', '；'))
    data['body'] = body
    data['title'] = clean(data.get('title', ''))
    combined = data['title'] + ' ' + body
    if data.get('kind') == 'job':
        if 'skills' not in data:
            data['skills'] = [s.model_dump() for s in extract_skills(body)]
        else:
            # 授权导入的结构技能也走同一别名规范，避免 Python/python 重复分组。
            skill_map = {}
            for skill in data['skills']:
                fields = dict(skill)
                name = str(fields.get('name','')).strip()
                fields['name'] = next((canonical for canonical,pattern in SKILLS.items() if re.fullmatch(pattern,name,re.I)),name)
                if 'evidence' in fields: fields['evidence'] = clean(fields['evidence'])
                value = Skill.model_validate(fields)
                old = skill_map.get(value.name)
                rank = {'required':0,'preferred':1,'mentioned':2}
                if old is None or rank[value.requirement]<rank[old.requirement]: skill_map[value.name]=value
            data['skills'] = [s.model_dump() for s in skill_map.values()]
        if 'skill_groups' not in data:
            data['skill_groups']=[g.model_dump() for g in extract_skill_groups(body)]
        else:
            data['skill_groups']=[dict(group) for group in data['skill_groups']]
            for group in data['skill_groups']:
                group['names']=[next((n for n,p in SKILLS.items() if re.fullmatch(p,name.strip(),re.I)),name.strip()) for name in group['names']]
                group['evidence']=clean(group['evidence'])
        if 'unparsed_skill_conditions' not in data:
            resolved={g['evidence'] for g in data['skill_groups']}
            data['unparsed_skill_conditions']=[e for e,context in skill_clauses(body)
                if alternative_choice(e) and e not in resolved
                and (REQUIRED.search(e) or PREFERRED.search(e) or context or re.search(r'任选|任意|其中|至少',e))
                and any(list(positive_occurrences(e,p)) for p in SKILLS.values())]
        data.setdefault('categories', [name for name, pattern in ROLES.items() if re.search(pattern, combined, re.I)])
        clauses=list(skill_clauses(body))
        if 'experience_requirements' not in data:
            data['experience_requirements']=[r.model_dump() for r in extract_experience(body)]
        else:
            data['experience_requirements']=[dict(c) for c in data['experience_requirements']]
            for condition in data['experience_requirements']:
                condition['evidence']=clean(condition['evidence'])
        review_notes=list(data.get('qualification_review_notes') or [])
        degree_alternatives=[e for e,c in clauses if re.search(r'degree|本科|硕士|博士|大专',e,re.I)
            and re.search(r'or equivalent (?:work )?experience|或.{0,10}同等.{0,6}经验',e,re.I)]
        review_notes.extend(degree_alternatives)
        if data.get('employment_type')=='internship' or re.search(r'实习|\bintern(?:ship)?s?\b',data['title'],re.I):
            review_notes.extend(r['evidence'] for r in data['experience_requirements']
                if r['requirement']=='required' and (r.get('minimum_years') or 0)>=1)
        data['qualification_review_notes']=list(dict.fromkeys(clean(e) for e in review_notes))
        cohorts = set()
        # A preferred graduating class is not a hard eligibility restriction.
        # Keep the complete evidence in body; only infer mandatory cohorts here.
        cohort_evidence='；'.join(part for e,c in skill_clauses(data['title']+'\n'+body)
            for part in re.split(r'[，]|,(?!\s*20\d{2})',e)
            if c!='preferred' and not PREFERRED.search(part)
            and not re.search(r'\bnot (?:for|accept(?:ing)?|(?:a )?graduat\w*|eligible)|\bexclud(?:e|es|ing)\b|graduates?.{0,20}\bnot eligible\b',part,re.I))
        cohort_text=re.sub(r'(?:不招|不接受|不面向)\s*20\d{2}届','',cohort_evidence)
        for m in re.finditer(r'((?:20\d{2}\s*[/、和与\-–]?\s*)+)届|(?:class of|graduat(?:ing|ed) in|will graduate in)\s*((?:20\d{2}(?:\s*(?:or|and|[/,])\s*)?)+)', cohort_text, re.I):
            cohorts.update(map(int, re.findall(r'20\d{2}', m.group())))
        # 官方英文“2028 Graduates”是届别，不是申请/到岗日期；优先/否定子句已在上方排除。
        for m in re.finditer(r'\b(20\d{2})\s+graduates?\b',cohort_text,re.I):
            cohorts.add(int(m.group(1)))
        # 明确连续届别范围展开；多届别不再丢失为单个 null。
        for m in re.finditer(r'(20\d{2})\s*[-–至]\s*(20\d{2})届',cohort_text):
            start,end=map(int,m.groups())
            if 2000<=start<=end<=2100:cohorts.update(range(start,end+1))
        if cohorts and 'graduation_years' not in data and not data.get('graduation_year'):
            data['graduation_years']=sorted(cohorts)
        if len(cohorts)==1 and not data.get('graduation_year'):
            data['graduation_year'] = cohorts.pop()
        if not data.get('education'):
            for name, pattern in [('associate',r'大专|associate.?s? degree'),('bachelor',r'本科|bachelor(?:[’\x27]s)?(?: degree)?'),('master',r'硕士|master(?:[’\x27]s)? degree'),('doctor',r'博士|Ph\.?D')]:
                degree_text='；'.join(e for e,c in clauses if c!='preferred' and not PREFERRED.search(e) and e not in degree_alternatives)
                degree_text=re.sub(r'(?:不接受|不招|不要求|无需)\s*(?:本科|硕士|博士|大专)(?:生)?','',degree_text,flags=re.I)
                if re.search(pattern, degree_text, re.I):
                    data['education'] = name
                    break
        if data.get('student_required') is None:
            if re.search(r'非在校生也可|不要求在校|无需在读|not required to be (?:a )?(?:full[ -]time )?students?',body,re.I):data['student_required']=False
            elif re.search(r'在校生|在读|currently (?:pursuing|enrolled)|must be (?:a )?student|full[ -]time students?\b|students? who will (?:be )?graduat|pursuing.{0,30}degree',
                           '；'.join(e for e,c in clauses if e not in degree_alternatives and c!='preferred' and not PREFERRED.search(e)
                                     and not re.search(r'\b(?:not (?:a |an )?|no )(?:full[ -]time )?students?\b',e,re.I)),re.I):data['student_required']=True
        if not data.get('bachelor_student_evidence'):
            # Acceptance of a current-bachelor pathway is independent of minimum
            # degree / mandatory student status when equivalent experience is an alternative.
            evidence=next((e for e,c in clauses if c!='preferred' and not PREFERRED.search(e)
                and re.search(r"(?:currently\s+)?pursuing\s+(?:a\s+)?bachelor|(?:本科|学士).{0,8}(?:在读|在校)|(?:在读|在校).{0,8}本科",e,re.I)
                and not re.search(r"不接受|不招|无需|不要求|\bnot\b|\bno\b",e,re.I)),None)
            if evidence and data.get('accepts_bachelor') is not False:
                data['bachelor_student_evidence']=evidence
        if not data.get('employment_type'):
            data['employment_type'] = 'internship' if re.search(r'实习|\bintern(?:ship)?s?\b',data['title'],re.I) and not re.search(r'非实习|不招.{0,8}实习|not an? internship', combined,re.I) else 'campus' if re.search(r'校招|校园招聘|graduate program',data['title'],re.I) else None
            if data['employment_type'] is None and re.search(r'(?:招聘|招募)(?:.{0,8})实习生|internship (?:position|role)',body,re.I) and not re.search(r'不招.{0,8}实习|非实习|not an? internship',body,re.I):
                data['employment_type']='internship'
        if not data.get('internship_type'):
            data['internship_type'] = next((x for x in ['暑期','寒假','日常','长期','可转正'] if x+'实习' in combined), None)
        data.setdefault('salary', parse_salary(body).model_dump())
        days = re.search(r'每周(?:到岗)?\s*(\d)\s*天', body)
        duration = re.search(r'实习(?:持续|至少)?\s*(\d+)\s*个?月', body)
        if not days:
            days=re.search(r'(?<![\d–-])(\d)\s*(?:working )?days\s+(?:per|a)\s+week',body,re.I)
            if days and re.search(r'\d\s*[-–]\s*$',body[:days.start()]):days=None
        if not duration:
            duration=re.search(r'(?:internship\s+(?:is for|duration\s*[:=]|length\s*[:=])|continuous internship of)\s*(?:at least\s*)?(\d+)\s*months?',body,re.I)
        if days: data.setdefault('days_per_week', int(days[1]))
        if duration: data.setdefault('duration_months', int(duration[1]))
        if re.search(r'接受本科|本科及以上', body): data.setdefault('accepts_bachelor', True)
        if '不接受本科' in body: data['accepts_bachelor'] = False
        if '可转正' in body: data.setdefault('conversion', True)
        if re.search(r'接受非相关专业|专业不限|不限专业', body): data.setdefault('accepts_other_major', True)
        if re.search(r'(?:要求|必须)(?:有|具备)?(?:相关)?实习经历', body): data.setdefault('experience_required', True)
        if re.search(r'无需(?:实习)?经验|无(?:实习)?经验要求', body): data.setdefault('experience_required', False)
        if not data.get('recruitment_batch'):
            data['recruitment_batch'] = next((x for x in ['提前批','补录','春招','秋招','管培生'] if x in combined), None)
        if not data.get('language'):
            lang = re.search(r'(?:语言要求|英语要求)\s*[:：]\s*([^；。]+)', body)
            if lang: data['language'] = lang[1].strip()
        if not data.get('major'):
            major = re.search(r'专业要求\s*[:：]\s*([^；。]+)', body)
            if major: data['major'] = major[1].strip()
            else:
                # 保留整句要求，不将专业任选/相关领域映射成武断硬限制。
                major=next((e for e,c in clauses if c!='preferred' and not PREFERRED.search(e)
                    and re.search(r'degree\s+in\s+|(?:本科|硕士|博士).{0,10}专业',e,re.I)),None)
                if major:data['major']=major
    if not data.get('deadline'):
        data['deadline'] = explicit_date(body, r'申请截止|报名截止|截止|apply by|application deadline|deadline|applications? close(?:s)?')
    if not data.get('application_start'):
        data['application_start'] = explicit_date(body, r'申请开始|报名开始|applications open')
    if data.get('kind') == 'opportunity':
        data.setdefault('risk_notes', ['费用、资助、资格和截止日以官方原文为准；未知字段需人工确认'])
    return Item.model_validate(data)

def canonical_url(url):
    p = urlsplit(url)
    query = urlencode(sorted((k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k not in ('ref','source')))
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/') or '/',query,''))

def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def content(item):
    data = item.model_dump(mode='json')
    data.pop('external_id')
    # 来源的链接保留在 item_sources，canonical URL 避免 UTM 触发版本变化。
    if data.get('url'): data['url'] = canonical_url(data['url'])
    return data
