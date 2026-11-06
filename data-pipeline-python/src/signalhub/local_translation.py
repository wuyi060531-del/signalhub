"""On-demand local NMT queue and reference cache; independent of paid AI and reviewed translations."""
import json
import os
from pathlib import Path
import re
import subprocess
import time
from sqlalchemy import text

REVISION='argos-en_zh-1.9-ct2-int8-guards-r7'
ATTRIBUTION='本机 Argos en_zh 1.9 / OPUS-MT，Tiedemann 与 Thottingal，模型 CC-BY 4.0；机器参考译文，未经人工核验'


def chinese(value):
    han=len(re.findall(r'[\u3400-\u9fff]',value or ''));latin=len(re.findall(r'[a-z]',value or '',re.I))
    return han>0 and han>=latin/2


def needs_translation(value):
    return bool(re.search(r"[A-Za-z]{2}",value or "")) and not chinese(value)


def pieces(value, limit=520):
    result=[]
    for part in re.split(r'[；\n]+|(?<=[.!?])\s+',value):
        part=part.strip()
        while len(part)>limit:
            cut=part.rfind(' ',0,limit)
            if cut<limit//2:cut=limit
            result.append(part[:cut]);part=part[cut:].strip()
        if part:result.append(part)
    return result


def build_inputs(payload,depth):
    title=str(payload.get('title') or '')
    body=str(payload.get('body') or '')
    limit=1600 if depth==1 else 12000
    excerpt=body[:limit]
    if len(body)>limit and ' ' in excerpt:excerpt=excerpt[:excerpt.rfind(' ')]
    body_parts=pieces(excerpt)
    candidates=pieces(body)
    summary_parts=[p for p in candidates if re.search(r'requirements?|qualifications?|you will|responsibilit|must|required|degree|experience|要求|负责',p,re.I)][:3] or candidates[:2]
    summary=' '.join(summary_parts)[:900]
    requirements=[]
    for key in ('skills','skill_groups','experience_requirements'):
        for condition in payload.get(key) or []:
            evidence=condition.get('evidence')
            if evidence and evidence in body and evidence not in requirements:requirements.append(evidence)
    for key in ('major','eligibility'):
        if payload.get(key) and payload[key] in body and payload[key] not in requirements:requirements.append(payload[key])
    requirements=requirements[:10]
    # Deduplicate repeated source sentences before model inference.
    texts=list(dict.fromkeys([title,*pieces(summary),*body_parts,*[p for r in requirements for p in pieces(r)]]))
    identifier_title=bool(re.fullmatch(r'[\w.-]+/[\w.-]+\s*·\s*\S+',title))
    texts=[v for v in texts if needs_translation(v) and not (identifier_title and v==title)]
    if len(texts)>160:raise ValueError('translation_input_limit')
    return {'title':title,'body':body,'excerpt':excerpt,'summary':summary,'body_parts':body_parts,'requirements':requirements,'texts':texts}


class LocalProvider:
    def __init__(self):
        root=Path.cwd()
        self.enabled=os.getenv('LOCAL_TRANSLATION_ENABLED','false').lower()=='true'
        self.python=Path(os.getenv('LOCAL_TRANSLATION_PYTHON',str(root/'.local/translation-env/bin/python')))
        self.model=Path(os.getenv('LOCAL_TRANSLATION_MODEL',str(root/'.local/translation-model/translate-en_zh-1_9')))
    def available(self):
        return self.enabled and self.python.is_file() and all((self.model/p).is_file() for p in ('model/model.bin','model/config.json','sentencepiece.model'))
    def translate(self,payload,depth):
        inputs=build_inputs(payload,depth)
        if chinese(inputs['body']) and chinese(inputs['title']):return {'method':'source_chinese','depth':depth,'body_complete':True}
        response=subprocess.run([str(self.python),str(Path(__file__).with_name('local_nmt_runner.py')),str(self.model)],
            input=json.dumps({'texts':inputs['texts']},ensure_ascii=False),text=True,capture_output=True,timeout=120,check=True,
            env={**{k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT')},'OMP_NUM_THREADS':'2','VECLIB_MAXIMUM_THREADS':'2'})
        if len(response.stdout)>1024*1024:raise ValueError('translation_output_limit')
        translations=json.loads(response.stdout)['translations']
        if len(translations)!=len(inputs['texts']):raise ValueError('translation_output_shape')
        mapping=dict(zip(inputs['texts'],translations));fallback=[]
        def translated(value):
            if not needs_translation(value):return value
            result=mapping.get(value)
            if result is None:fallback.append(value);return value
            return result
        def paragraph(value):return '\n'.join(translated(p) for p in pieces(value))
        # Common JD section labels have fixed meanings; do not publish the model's
        # reproduced proper-noun rendering of Nice-to-Haves (e.g. 尼斯对哈斯人).
        headings={'nice-to-haves':'加分条件','nice to have':'加分条件','the nice-to-haves':'加分条件',
                  'must-haves':'必备条件','the must-haves':'必备条件','requirements':'岗位要求'}
        for value in inputs['texts']:
            label=value.strip().rstrip(':：').lower()
            if label in headings:mapping[value]=headings[label]
        title=mapping.get(inputs['title'])
        title_markers=[]
        if title:
            for marker in re.findall(r'\b(?:Intern(?:ship)?|Senior|Staff|Principal|Lead|Junior)\b',inputs['title'],re.I):
                # Retain literal source markers when the NMT drops/ambiguously translates rank or internship.
                if marker.lower() not in title.lower() and not (marker.lower().startswith('intern') and '实习' in title):title_markers.append(marker)
            if title_markers:title+='（原文标记：'+' / '.join(dict.fromkeys(title_markers))+'）'
        summary=paragraph(inputs['summary'])
        body='\n\n'.join(translated(p) for p in inputs['body_parts'])
        if not title and not re.search(r'[\u3400-\u9fff]',summary+body):raise ValueError('no_usable_chinese_reference')
        return {'method':'local_nmt','reviewed':False,'attribution':ATTRIBUTION,'provider_revision':REVISION,'depth':depth,
            'title_zh':title,'title_source_markers':title_markers,'summary_zh':summary,'body_zh':body,
            'requirements_zh':[{'original':r,'translation':paragraph(r)} for r in inputs['requirements']],
            'body_complete':len(inputs['excerpt'])==len(inputs['body']) and all(not needs_translation(p) or mapping.get(p) is not None for p in inputs['body_parts']),
            'processed_source_chars':len(inputs['excerpt']),'translated_source_chars':sum(len(p) for p in inputs['body_parts'] if not needs_translation(p) or mapping.get(p) is not None),'total_source_chars':len(inputs['body']),
            'summary_kind':'extractive_translation','fallback_segments':len(set(fallback)),
            'body_original_chinese':chinese(inputs['body']),'warning':'机器可能误译职级、条件和专有名词；学历/届别/薪资/技能/截止日期与匹配仅取原始规则数据。未通过数字、术语或否定检查的片段保留原文。'}


class LocalTranslationWorker:
    def __init__(self,db,provider=None):self.db=db;self.provider=provider or LocalProvider();self.last_heartbeat=0
    def tick(self):
        available=self.provider.available()
        if time.monotonic()-self.last_heartbeat>30:
            with self.db.begin() as c:
                c.execute(text('''INSERT INTO translation_runtime(id,available,provider_revision,message) VALUES (1,:ready,:revision,:message)
                    ON CONFLICT(id) DO UPDATE SET available=excluded.available,provider_revision=excluded.provider_revision,message=excluded.message,updated_at=now()'''),
                    {'ready':available,'revision':REVISION,'message':'本地免费英中机器参考翻译已就绪' if available else '本地翻译关闭或模型/专用环境缺失；原文照常可用'})
            self.last_heartbeat=time.monotonic()
        if not available:return None
        with self.db.begin() as c:
            c.execute(text("UPDATE reading_translation_jobs SET state=CASE WHEN attempts<2 THEN 'pending' ELSE 'failed' END,error='local_translation_lease_expired' WHERE state='running' AND started_at<now()-interval '3 minutes'"))
            job=c.execute(text("SELECT * FROM reading_translation_jobs WHERE state='pending' AND provider_revision=:revision ORDER BY depth DESC,id FOR UPDATE SKIP LOCKED LIMIT 1"),{'revision':REVISION}).mappings().first()
            if not job:return None
            job=dict(job)
            job['attempt']=c.execute(text("UPDATE reading_translation_jobs SET state='running',attempts=attempts+1,started_at=now(),error=NULL WHERE id=:id RETURNING attempts"),{'id':job['id']}).scalar_one()
            item=c.execute(text('SELECT payload,content_hash FROM items WHERE id=:id'),{'id':job['item_id']}).mappings().one()
            cached=c.execute(text("SELECT result FROM reading_translation_jobs WHERE item_id=:item AND content_hash=:hash AND provider_revision=:revision AND depth>=:depth AND state='done' ORDER BY depth DESC LIMIT 1"),
                {'item':job['item_id'],'hash':job['content_hash'],'revision':REVISION,'depth':job['depth']}).scalar_one_or_none()
        result=None;error=None
        if item['content_hash']!=job['content_hash']:state='superseded'
        else:
            try:
                result=cached or self.provider.translate(item['payload'],job['depth']);state='done'
            except Exception as exc:
                state='failed';error=type(exc).__name__ # no raw input, paths, credentials or provider stderr in user-visible errors
        with self.db.begin() as c:
            current=c.execute(text('SELECT content_hash FROM items WHERE id=:id FOR SHARE'),{'id':job['item_id']}).scalar_one()
            if current!=job['content_hash']:state='superseded';result=None
            updated=c.execute(text('''UPDATE reading_translation_jobs SET state=:state,result=CAST(:result AS jsonb),error=:error,finished_at=now()
                WHERE id=:id AND state='running' AND attempts=:attempt'''),{'state':state,'result':json.dumps(result,ensure_ascii=False) if result is not None else None,'error':error,'id':job['id'],'attempt':job['attempt']}).rowcount
        return {'state':state if updated else 'superseded','translation_job':job['id']}
