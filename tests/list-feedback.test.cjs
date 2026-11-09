const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../backend-java/src/main/resources/static/app.js'), 'utf8');
// app.js 不是模块：截取 outOfView / pastTop / msg 三个函数，在带假 DOM 的沙箱里执行。
const start = source.indexOf('function outOfView(');
const end = source.indexOf('async function api(');
assert.ok(start > 0 && end > start, 'outOfView、pastTop、msg 应存在');
function makeSandbox(rect, innerHeight = 800) {
  const calls = [];
  const notice = {
    hidden: true, className: '', attrs: {}, children: null,
    setAttribute(k, v) { this.attrs[k] = v; },
    replaceChildren(...c) { this.children = c; },
    getBoundingClientRect: () => rect,
    scrollIntoView: (opts) => calls.push(opts),
  };
  const sandbox = {
    document: {querySelector: (s) => (s === '#notice' ? notice : null)},
    window: {innerHeight},
    node: (tag, text) => ({tag, text}),
  };
  vm.runInNewContext(source.slice(start, end) + ';this.msg = msg; this.outOfView = outOfView; this.pastTop = pastTop;', sandbox);
  return {sandbox, notice, calls};
}

test('outOfView：完全在视口上方或下方才算滚出视口，部分可见不算', () => {
  const {sandbox} = makeSandbox({});
  const out = (top, bottom) => sandbox.outOfView({top, bottom}, 800);
  assert.equal(out(-300, -1), true, '完全在上方');
  assert.equal(out(-300, 0), true, '底边刚好贴着视口上沿');
  assert.equal(out(800, 900), true, '顶边刚好在视口下沿');
  assert.equal(out(1200, 1300), true, '完全在下方');
  assert.equal(out(-100, 50), false, '露出一点');
  assert.equal(out(0, 40), false, '完全可见');
  assert.equal(out(780, 900), false, '下方露出一点');
});

test('pastTop：只有顶边已经滚到视口上方才需要回到结果开头', () => {
  const {sandbox} = makeSandbox({});
  assert.equal(sandbox.pastTop({top: -1}), true);
  assert.equal(sandbox.pastTop({top: -5043}), true);
  assert.equal(sandbox.pastTop({top: 0}), false, '已在顶部不移动页面');
  assert.equal(sandbox.pastTop({top: 73}), false);
});

test('错误提示不在视口内时滚进视野，并保留 role=alert', () => {
  const {sandbox, notice, calls} = makeSandbox({top: -6000, bottom: -5950});
  sandbox.msg('服务暂时不可用', true);
  assert.equal(notice.hidden, false);
  assert.equal(notice.attrs.role, 'alert');
  assert.equal(notice.className, 'notice error');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].block, 'nearest');
});

test('错误提示已在视口内时不滚动，避免页面无谓跳动', () => {
  const {sandbox, calls} = makeSandbox({top: 120, bottom: 170});
  sandbox.msg('请求失败', true);
  assert.equal(calls.length, 0);
});

test('成功提示即使不在视口内也不打断用户当前位置', () => {
  const {sandbox, notice, calls} = makeSandbox({top: -6000, bottom: -5950});
  sandbox.msg('已保存');
  assert.equal(notice.attrs.role, 'status');
  assert.equal(notice.className, 'notice');
  assert.equal(calls.length, 0);
});
