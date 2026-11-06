"""仅使用本地原始存档重解析一次；无网络调用，不刷新网络验证时间。"""
import argparse
import json
from urllib.parse import urlsplit,parse_qs
import httpx
from signalhub.db import engine
from signalhub.pipeline import Pipeline,execute
from signalhub.adapters.smartrecruiters import SmartRecruitersAdapter
from signalhub.adapters.lever import LeverAdapter


def reparse(source_id):
    db=engine();pipeline=Pipeline(db);source=pipeline.source(source_id)
    if source['adapter'] not in ('smartrecruiters','lever'):raise ValueError('本工具仅支持SmartRecruiters/Lever存档（保留旧命令名）')
    with db.connect() as conn:
        raws=[row['body'] for row in execute(conn,'SELECT r.body FROM item_sources s JOIN raw_records r ON r.id=s.raw_id WHERE s.source_id=:source ORDER BY s.external_id',source=source_id).mappings()]
        before=dict(execute(conn,'SELECT status,last_success,etag,last_modified FROM sources WHERE id=:id',id=source_id).mappings().one())
    if not raws:raise ValueError('来源无原始存档，不会改来源状态')
    if len(raws)>2000:raise ValueError('超过2000条存档边界，不静默截断')
    if source['adapter']=='lever':
        if any(not isinstance(x,dict) or 'id' not in x or 'text' not in x for x in raws):raise ValueError('Lever存档结构不兼容')
        root=f"https://api.lever.co/v0/postings/{source['config']['board']}"
        class LeverArchive:
            def get(self,url,headers):
                if url.split('?',1)[0]!=root:raise ValueError('存档查询不匹配固定来源')
                offset=int(parse_qs(urlsplit(url).query)['skip'][0])
                return httpx.Response(200,json=raws[offset:offset+100])
        records,_,_=LeverAdapter(sleep=lambda _:None).fetch(source['config'],LeverArchive(),{})
        result=pipeline.run(source_id,records,refresh_source=False)
        with db.connect() as conn:
            after=dict(execute(conn,'SELECT status,last_success,etag,last_modified FROM sources WHERE id=:id',id=source_id).mappings().one())
        result['source_network_verification_unchanged']=before==after
        result['external_requests']=0
        db.dispose()
        return result
    if any(not isinstance(x,dict) or 'listing' not in x or 'detail' not in x for x in raws):raise ValueError('存档结构不兼容，停止而不猜原文')
    index={str(x['listing'].get('uuid') or x['listing']['id']):x for x in raws}
    root=f"https://api.smartrecruiters.com/v1/companies/{source['config']['board']}/postings"
    class Archive:
        def get(self,url,headers):
            # 所有请求只在存档内解析；没有HTTP客户端或网络回退。
            if urlsplit(url).query and url.split('?',1)[0]==root:
                offset=int(parse_qs(urlsplit(url).query)['offset'][0])
                data={'offset':offset,'totalFound':len(raws),'content':[x['listing'] for x in raws][offset:offset+100]}
            elif url.startswith(root+'/'):
                data=index[url.rsplit('/',1)[-1]]['detail']
            else:raise ValueError('存档查询不匹配固定来源')
            return httpx.Response(200,json=data)
    records,_,_=SmartRecruitersAdapter(sleep=lambda _:None).fetch(source['config'],Archive(),{})
    result=pipeline.run(source_id,records,refresh_source=False)
    with db.connect() as conn:
        after=dict(execute(conn,'SELECT status,last_success,etag,last_modified FROM sources WHERE id=:id',id=source_id).mappings().one())
    result['source_network_verification_unchanged']=before==after
    result['external_requests']=0
    db.dispose()
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=int)
    args=parser.parse_args()
    print(json.dumps(reparse(args.source),ensure_ascii=False))
