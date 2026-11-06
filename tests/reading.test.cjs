const {test} = require('node:test');
const assert = require('node:assert/strict');
const reading = require('../backend-java/src/main/resources/static/reading.js');
const item = {title:'Test Engineer',payload:{body:'Python required. Original English.'}, reading:{status:'current',translation:{title_zh:'测试工程师',summary_zh:'要求 Python。',body_zh:'要求 Python。',attribution:'Synthetic test review'}}};
test('default, persisted modes and blocked/invalid storage', () => {
  const values = new Map(), storage = {getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
  assert.equal(reading.readPreference(storage),'zh');
  for(const mode of ['original','bilingual','zh']) {
    reading.writePreference(storage,mode);assert.equal(reading.readPreference(storage),mode);
  }
  assert.equal(reading.readPreference({getItem(){throw Error('blocked')}}),'zh');
  assert.equal(reading.writePreference({setItem(){throw Error('blocked')}},'original'),false);
  assert.equal(reading.normalizeMode('invalid'),'zh');
});
test('all modes preserve source and only current reviews are used', () => {
  const snapshot = JSON.stringify(item);
  for(const mode of ['zh','original','bilingual']) {
    const v = reading.view(item,mode);
    assert.equal(v.primaryTitle, mode==='original'?'Test Engineer':'测试工程师');
    assert.equal(v.originalOpen, mode!=='zh');
    assert.equal(v.body,item.payload.body);
  }
  assert.equal(JSON.stringify(item),snapshot);
  for(const status of ['missing','stale']) {
    const v=reading.view({...item,reading:{...item.reading,status}},'zh');
    assert.equal(v.primaryTitle,item.title);assert.equal(v.zhSummary,null);assert.equal(v.zhBody,null);
    assert.match(v.message,status==='stale'?/过期/:/暂无中文译文/);
  }
});
test('Chinese and mixed Chinese source shown once; a Chinese location does not hide English', () => {
  const chinese={title:'Python 数据实习',payload:{body:'要求掌握 Python 和 SQL，支持学习 Java。'}};
  assert.equal(reading.view(chinese,'bilingual').secondaryTitle,null);
  assert.equal(reading.view(chinese,'zh').chineseSource,true);
  assert.equal(reading.view(chinese,'zh').originalOpen,true);
  assert.equal(reading.view({...item,payload:{body:item.payload.body+' Shanghai 上海'}},'zh').chineseSource,false);
});
test('HTML is data, never evaluated or translated by presentation logic', () => {
  const malicious={title:'<img src=x onerror=alert(1)>',payload:{body:'<script>alert(2)</script>'}};
  assert.equal(reading.view(malicious,'zh').body,malicious.payload.body);
  assert.equal(reading.view(malicious,'zh').primaryTitle,malicious.title);
});
test('a Chinese location in an English title does not suppress a reviewed Chinese title', () => {
  const mixed={...item,title:'Test Engineer（上海）'};
  assert.equal(reading.view(mixed,'zh').primaryTitle,'测试工程师');
  assert.equal(reading.view(mixed,'bilingual').secondaryTitle,mixed.title);
});
