import argparse
import csv
import json
import logging
import signal
from pathlib import Path
from importlib.resources import files
from apscheduler.schedulers.blocking import BlockingScheduler
from .db import engine
from .pipeline import Pipeline,execute,dump
from .worker import Worker

ROOT = Path(__file__).resolve().parents[3]

def read_file(path):
    if path.stat().st_size>2*1024*1024: raise ValueError('文件超过2MB')
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as f:
            data=[]
            for row in csv.DictReader(f):
                record={k:v for k,v in row.items() if v not in ('',None)}
                for key in ('skills','categories','salary','risk_notes','locations','skill_groups','graduation_years','unparsed_skill_conditions','experience_requirements','qualification_review_notes'):
                    if key in record: record[key]=json.loads(record[key])
                data.append({**record,'_raw':row})
                if len(data)>1000:raise ValueError('最多1000行')
        return data
    if path.suffix.lower()!='.json': raise ValueError('只接受CSV/JSON文件')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,list): raise ValueError('JSON 必须是记录数组')
    if len(data)>1000:raise ValueError('最多1000行')
    return data

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    # HTTP默认INFO会输出完整URL（可能含查询凭据），失败统一由结构化诊断记录。
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)  # 不每3秒为正常空轮询写两行日志。
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command',required=True)
    imp = sub.add_parser('import'); imp.add_argument('path',type=Path); imp.add_argument('--source',type=int,default=1)
    sub.add_parser('demo')
    sub.add_parser('worker')
    sub.add_parser('tick')
    collect = sub.add_parser('collect'); collect.add_argument('source',type=int); collect.add_argument('--force',action='store_true',help='忽略条件缓存，重新获取并用当前规则解析；保留历史版本')
    ai = sub.add_parser('enrich'); ai.add_argument('item',type=int)
    args = parser.parse_args()
    db = engine()
    if args.command=='import': result = Pipeline(db).run(args.source,read_file(args.path))
    elif args.command=='demo': result = Pipeline(db).run(2,json.loads(files('signalhub').joinpath('resources/demo.json').read_text(encoding='utf-8')))
    elif args.command=='collect': result = Pipeline(db).run(args.source,force=args.force)
    elif args.command=='enrich':
        from .ai.service import AIService
        result = AIService(db).enrich(args.item)
    elif args.command=='tick': result = Worker(db).tick()
    else:
        scheduler = BlockingScheduler(timezone='Asia/Shanghai')
        scheduler.add_job(Worker(db).tick,'interval',seconds=3,max_instances=1,coalesce=True)
        # 低频轮询已启用的来源；数据源至少 6 小时采集一次，防止高频访问。
        def schedule_sources():
            with db.begin() as conn:
                execute(conn,'''INSERT INTO task_requests(task_type,source_id,payload)
                    SELECT 'collect',s.id,'{}' FROM sources s WHERE enabled AND adapter<>'manual'
                    AND (last_success IS NULL OR last_success<now()-interval '6 hours')
                    AND NOT EXISTS(SELECT 1 FROM task_requests t WHERE t.source_id=s.id AND
                    (t.state IN ('pending','running') OR t.created_at>now()-interval '6 hours'))''')
        scheduler.add_job(schedule_sources,'interval',minutes=10,max_instances=1)
        # 等待已开始的tick结束，避免普通停止使任务遗留running到租约回收。
        signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=True))
        signal.signal(signal.SIGINT, lambda *_: scheduler.shutdown(wait=True))
        scheduler.start()
        return
    print(dump(result))

if __name__=='__main__': main()
