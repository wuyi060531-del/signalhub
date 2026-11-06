"""离线规则/Mock 评估。没有网络请求，不将 Mock 分数当作 LLM 准确率。"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from signalhub.normalize import normalize
from signalhub.ai.providers import MockProvider, Analysis

ROOT = Path(__file__).resolve().parents[1]

def evaluate():
    cases=json.loads((ROOT/'tests/fixtures/ai_eval.json').read_text())
    rows=[]; totals={k:{'correct':0,'total':0} for k in cases[0]['expected']}
    for case in cases:
        assert case['synthetic'] is True
        item=normalize({'kind':'job','external_id':case['id'],'title':'评估样本','body':case['body']})
        result,_,_=MockProvider().analyze(item.body,case['profile'])
        # 即使有语义错误，Schema 和原文证据必须可验证；失败使 check.sh 失败。
        Analysis.model_validate(result.model_dump()).verify(item.body)
        actual={'skills':sorted(s['name'] for s in result.skills),
                **{k:getattr(result,k).value for k in ('education','graduation_year','deadline','category')},
                'relevance':result.relevance}
        expected={**case['expected'],'skills':sorted(case['expected']['skills'])}
        wrong={k:{'expected':expected[k],'actual':actual[k]} for k in expected if expected[k]!=actual[k]}
        for k in totals:
            totals[k]['total']+=1;totals[k]['correct']+=int(expected[k]==actual[k])
        rows.append({'id':case['id'],'synthetic':True,'expected':expected,'actual':actual,'errors':wrong})
    for score in totals.values():score['accuracy']=round(score['correct']/score['total'],4)
    output={'created_at':datetime.now(timezone.utc).isoformat(),'sample_count':len(rows),'provider':'mock/rules; no model or paid API called',
        'real_llm':'not_run: no authorization/key','metrics':totals,'cases':rows,
        'limitations':['12个人工合成样本，不代表真实招聘分布','规则不擅长技能否定、复杂多句作用域和真实语义相关性','证据匹配只能排除部分错误，不证明所有语义事实正确','摘要为带MOCK标记的截取，不评估生成质量']}
    path=ROOT / os.getenv('SIGNALHUB_EVIDENCE_DIR', '.local/check') / 'ai-evaluation.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps({'samples':len(rows),'metrics':totals,'semantic_error_cases':[r['id'] for r in rows if r['errors']],'real_llm':'not_run'},ensure_ascii=False,indent=2))
    return output

if __name__=='__main__':evaluate()
