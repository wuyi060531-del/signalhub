import pytest
from pydantic import ValidationError
from sqlalchemy import text
from signalhub.pipeline import Pipeline
from signalhub.translation import TranslationDraft, DisabledTranslationProvider, save_reviewed

RAW=dict(kind='job',external_id='bilingual-test',title='Test Engineer',body='Python required.\nSecond paragraph.',country='CN',is_demo=True)


def snapshot(db):
    with db.connect() as conn:
        return dict(conn.execute(text('SELECT id,content_hash,payload,version FROM items')).mappings().one())


def draft(item,**changes):
    return TranslationDraft(item_id=item['id'],content_hash=item['content_hash'],method='human_reviewed',attribution='合成测试夹具，仅核验测试文本',reviewed=True,title_zh='测试工程师',summary_zh='要求 Python。',**changes)


def test_review_cache_idempotence_preserves_sources_versions_and_expired_history(db):
    pipeline=Pipeline(db);pipeline.run(1,[RAW]);before=snapshot(db)
    review=draft(before)
    assert save_reviewed(db,review)=='saved'
    assert save_reviewed(db,review)=='cached'
    assert snapshot(db)==before
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM raw_records')).scalar_one()==1
        assert conn.execute(text('SELECT count(*) FROM item_versions')).scalar_one()==1
    pipeline.run(1,[{**RAW,'body':'Java required. New source content.'}])
    with pytest.raises(ValueError,match='已更新'):save_reviewed(db,review)
    assert save_reviewed(db,draft(snapshot(db)))=='saved'
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM reading_translations')).scalar_one()==2
        assert conn.execute(text('SELECT count(*) FROM ai_usage')).scalar_one()==0


@pytest.mark.parametrize('changes',[
    {'reviewed':False},{'reviewed':'true'},{'reviewed':1},{'method':'mock'}, {'attribution':'  '},
    {'title_zh':None,'summary_zh':None}, {'title_zh':'  ','summary_zh':'  '}, {'item_id':0},
    {'title_zh':'x'*501}, {'unknown':'reject'},
])
def test_unreviewed_or_invalid_drafts_rejected(changes):
    values=dict(item_id=1,content_hash='hash',method='human_reviewed',attribution='test reviewer',reviewed=True,title_zh='中文',summary_zh=None)
    with pytest.raises(ValidationError):TranslationDraft.model_validate({**values,**changes})


def test_default_provider_never_generates_a_translation():
    assert DisabledTranslationProvider().translate({'body':'Original English'}) is None
