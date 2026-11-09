const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../backend-java/src/main/resources/static/app.js'), 'utf8');
// app.js 不是模块：只截取投递历史的纯函数（不含 DOM 渲染）在沙箱里执行。
const start = source.indexOf('const HISTORY_FIELDS');
const end = source.indexOf('function applicationHistoryView(');
assert.ok(start > 0 && end > start, '投递历史的纯函数应存在');
const sandbox = {};
// historyTime 依赖页面里真实的 fullTime 定义，一并截取，保证测的是同一份格式化配置。
const timeStart = source.indexOf('const fullTime');
const timeEnd = source.indexOf('function formatTime(');
assert.ok(timeStart > 0 && timeEnd > timeStart, 'fullTime 应存在');
vm.runInNewContext(source.slice(timeStart, timeEnd) + source.slice(start, end) +
  ';this.historyChanges = historyChanges; this.historyEntries = historyEntries; this.historyTime = historyTime;', sandbox);
// 沙箱里创建的数组和这里不是同一个领域，直接 deepStrictEqual 会误判，所以先经 JSON 规范化。
const historyEntries = (rows, show) => JSON.parse(JSON.stringify(sandbox.historyEntries(rows, show)));
// 与页面一致的展示函数，换成最简单的可断言形式。
const show = (key, v) => key === 'status' ? '<' + v + '>' : String(v);
const row = (id, snapshot) => ({id, created_at: '2026-11-0' + id + 'T01:00:00Z', snapshot});
const labelsOf = (entry) => entry.changes.map(c => c.label + ':' + c.before + '>' + c.after);

test('最早一条是“创建”，只列出已填写的字段', () => {
  const [entry] = historyEntries([row(1, {status: 'saved', notes: '', nextAction: null, appliedAt: null})], show);
  assert.equal(entry.first, true);
  assert.deepEqual(labelsOf(entry), ['状态:>' + '<saved>']);
});

test('后一条只列出相对上一条真正变化的字段，最新在前', () => {
  const rows = [
    row(1, {status: 'saved', notes: '', nextAction: null}),
    row(3, {status: 'assessment', notes: '', nextAction: '做笔试'}),
    row(2, {status: 'applied', notes: '', nextAction: null}),
  ];
  const entries = historyEntries(rows, show);
  assert.deepEqual(entries.map(e => e.id), [3, 2, 1], '按 id 倒序，与接口返回顺序无关');
  assert.deepEqual(labelsOf(entries[0]), ['状态:<applied>><assessment>', '下一步:>做笔试']);
  assert.deepEqual(labelsOf(entries[1]), ['状态:<saved>><applied>']);
  assert.equal(entries[0].first, false);
  assert.equal(entries[2].first, true);
});

test('内容没有变化的保存得到空的变化列表', () => {
  const same = {status: 'applied', notes: '', nextAction: null, appliedAt: null};
  const entries = historyEntries([row(1, same), row(2, {...same})], show);
  assert.deepEqual(entries[0].changes, []);
});

test('null、空串和缺失字段视为同一种“未填写”，不产生假变化', () => {
  const entries = historyEntries([
    row(1, {status: 'saved', notes: '', nextAction: null}),
    row(2, {status: 'saved', nextAction: ''}),
  ], show);
  assert.deepEqual(entries[0].changes, []);
});

test('同一时刻的不同时区写法不算变化，真正改时间才算', () => {
  const entries = historyEntries([
    row(1, {status: 'applied', appliedAt: '2026-11-02T02:00:00Z'}),
    row(2, {status: 'applied', appliedAt: '2026-11-02T10:00:00+08:00'}),
    row(3, {status: 'applied', appliedAt: '2026-11-03T10:00:00+08:00'}),
  ], show);
  assert.deepEqual(labelsOf(entries[0]), ['投递时间:2026-11-02T10:00:00+08:00>2026-11-03T10:00:00+08:00']);
  assert.deepEqual(entries[1].changes, []);
});

test('清空字段会记为变化，after 为空串由页面显示“已清空”', () => {
  const entries = historyEntries([
    row(1, {status: 'applied', nextAction: '发邮件'}),
    row(2, {status: 'applied', nextAction: ''}),
  ], show);
  assert.deepEqual(labelsOf(entries[0]), ['下一步:发邮件>']);
});

test('缺少 snapshot 的异常行不会抛错', () => {
  const entries = historyEntries([{id: 1, created_at: null, snapshot: null}, {id: 2, created_at: null}], show);
  assert.equal(entries.length, 2);
  assert.deepEqual(entries.map(e => e.changes), [[], []]);
});

test('历史时间带年份和秒数，只差一年或几秒的时间不会显示成同样的文字', () => {
  const {historyTime} = sandbox;
  assert.equal(historyTime('2026-11-02T02:00:00Z'), '2026/11/02 10:00:00', '按北京时间显示完整年月日时分秒');
  const base = historyTime('2026-11-02T02:00:00Z');
  assert.notEqual(historyTime('2027-11-02T02:00:00Z'), base, '不同年份的同月同日');
  assert.notEqual(historyTime('2026-11-02T02:00:30Z'), base, '只差 30 秒');
  assert.equal(historyTime('2026-11-02T10:00:00+08:00'), base, '同一时刻的不同写法显示一致');
});

test('历史时间遇到空值或无法解析的值显示破折号，不抛错', () => {
  const {historyTime} = sandbox;
  for (const bad of [null, undefined, '', 'not-a-date']) assert.equal(historyTime(bad), '—');
});
