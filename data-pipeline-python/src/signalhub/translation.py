"""Offline reviewed reading translations. No network/model provider is enabled by default."""
import argparse
import json
from pathlib import Path
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from .db import engine


class TranslationDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    item_id: int = Field(gt=0)
    content_hash: str = Field(min_length=1, max_length=128)
    method: Literal['human_reviewed', 'source_bilingual']
    attribution: str = Field(min_length=1, max_length=2000)
    reviewed: Literal[True]
    title_zh: str | None = Field(default=None, max_length=500)
    summary_zh: str | None = Field(default=None, max_length=10000)
    body_zh: str | None = Field(default=None, max_length=200000)

    @field_validator('reviewed', mode='before')
    @classmethod
    def explicit_review(cls, value):
        if value is not True:
            raise ValueError('reviewed必须显式为布尔true，不能自动视为已核验')
        return value

    @model_validator(mode='after')
    def meaningful(self):
        if not self.attribution.strip() or not any(v and v.strip() for v in (self.title_zh,self.summary_zh,self.body_zh)):
            raise ValueError('需填写译文及可追溯的译文依据/核验人；不能以空白冒充译文')
        return self


class TranslationProvider(Protocol):
    """Future provider boundary: explicit authorization and review must precede save_reviewed.

    Providers receive a source snapshot and return a draft; no provider is invoked by ETL,
    Worker, page loads or this CLI. An unreviewed model output must never be saved here.
    """
    def translate(self, snapshot: dict) -> TranslationDraft | None: ...


class DisabledTranslationProvider:
    def translate(self, snapshot: dict) -> None:
        return None


def save_reviewed(db, draft: TranslationDraft):
    payload=draft.model_dump(exclude={'item_id','content_hash'})
    with db.begin() as conn:
        current=conn.execute(text('SELECT content_hash FROM items WHERE id=:id FOR SHARE'),{'id':draft.item_id}).scalar_one()
        if current != draft.content_hash:
            raise ValueError('原始内容已更新，拒绝保存过期译文；请重新导出并核验')
        # Same input and reviewed output are idempotent; corrected reviews may replace cache.
        result=conn.execute(text('''INSERT INTO reading_translations(item_id,content_hash,payload)
            VALUES (:id,:hash,CAST(:payload AS jsonb))
            ON CONFLICT(item_id,content_hash,language) DO UPDATE SET payload=excluded.payload,created_at=now()
            WHERE reading_translations.payload IS DISTINCT FROM excluded.payload'''),
            {'id':draft.item_id,'hash':draft.content_hash,'payload':json.dumps(payload,ensure_ascii=False)})
        return 'saved' if result.rowcount else 'cached'


def main():
    parser=argparse.ArgumentParser(description='离线中文参考译文；不调用翻译/AI服务、不抓取来源链接')
    sub=parser.add_subparsers(dest='action',required=True)
    export=sub.add_parser('export',help='从本机API导出当前原文与待填写的译文草稿')
    export.add_argument('item_id',type=int)
    export.add_argument('output',type=Path)
    save=sub.add_parser('import',help='保存已经人工核验的中文译文，不修改原始信息')
    save.add_argument('file',type=Path)
    args=parser.parse_args()
    if args.action=='export':
        import httpx
        if args.item_id<=0:parser.error('item_id需为正整数')
        response=httpx.get(f'http://127.0.0.1:8080/api/items/{args.item_id}',trust_env=False,timeout=10)
        response.raise_for_status(); item=response.json()
        document={'source':item['original'],'translation':{
            'item_id':item['id'],'content_hash':item['content_hash'],'method':'human_reviewed',
            'attribution':'','reviewed':False,'title_zh':None,'summary_zh':None,'body_zh':None}}
        # Never overwrite a user's existing review file.
        with args.output.open('x',encoding='utf-8') as file:json.dump(document,file,ensure_ascii=False,indent=2)
        print('已导出原文；填写并人工核验 translation 后才能导入。')
    else:
        if args.file.stat().st_size>2*1024*1024:parser.error('文件超过2MiB')
        document=json.loads(args.file.read_text(encoding='utf-8'))
        draft=TranslationDraft.model_validate(document['translation'])
        db=engine()
        try:print(save_reviewed(db,draft))
        finally:db.dispose()


if __name__=='__main__':main()
