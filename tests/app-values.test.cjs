const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../backend-java/src/main/resources/static/app.js'), 'utf8');
// app.js 不是模块：只截取 readableValue 这一个纯函数在沙箱里执行。
const start = source.indexOf('function readableValue(');
const end = source.indexOf('function parseArray(');
assert.ok(start > 0 && end > start, 'readableValue 应存在');
const sandbox = {};
vm.runInNewContext(source.slice(start, end) + ';this.readableValue = readableValue;', sandbox);
const {readableValue} = sandbox;

test('资格表的值显示为可读文字，而不是原始 JSON', () => {
  assert.equal(readableValue('internship'), 'internship');
  assert.equal(readableValue(['internship']), 'internship');
  assert.equal(readableValue(['Python', 'SQL']), 'Python、SQL');
  assert.equal(readableValue(true), '是');
  assert.equal(readableValue(false), '否');
  assert.equal(readableValue(6), '6');
  assert.equal(readableValue({from: '2027-03', to: '2027-06'}), 'from：2027-03；to：2027-06');
});

test('空值返回空串，由调用处决定显示“未明确”或“未填写”', () => {
  assert.equal(readableValue(null), '');
  assert.equal(readableValue(undefined), '');
  assert.equal(readableValue([]), '');
  assert.equal(readableValue([null, '']), '');
});

test('qualification 表不再使用 JSON.stringify 渲染来源值和档案值', () => {
  const row = source.slice(source.indexOf('"逐项招聘资格"'), source.indexOf('"逐项招聘资格"') + 700);
  assert.ok(!/JSON\.stringify\(check\./.test(row));
  assert.match(row, /readableValue\(check\.sourceValue\)/);
  assert.match(row, /readableValue\(check\.profileValue\)/);
});
