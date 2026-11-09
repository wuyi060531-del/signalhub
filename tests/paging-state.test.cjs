const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../backend-java/src/main/resources/static/app.js'), 'utf8');
// app.js 不是模块：只截取分页加载器（不含 DOM）在沙箱里执行。
const start = source.indexOf('function createPagedLoader(');
const end = source.indexOf('function outOfView(');
assert.ok(start > 0 && end > start, 'createPagedLoader 应存在');
const sandbox = {};
vm.runInNewContext(source.slice(start, end) + ';this.createPagedLoader = createPagedLoader;', sandbox);
const createPagedLoader = () => sandbox.createPagedLoader();

// 可手动决定何时成功/失败的请求，用来构造请求交错。
function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}
const ok = (page) => () => Promise.resolve('第' + page + '页');
const fail = () => Promise.reject(new Error('服务暂时不可用'));

test('翻页失败后页码不变：再点“下一页”请求的仍是目标页，而不是跳过一页', async () => {
  const loader = createPagedLoader();
  assert.equal(await loader.load(0, ok(0)), '第0页');
  assert.equal(loader.page, 0);
  // 用户点“下一页”：目标页 = 当前页 + 1，请求失败
  await assert.rejects(loader.load(loader.page + 1, fail), /服务暂时不可用/);
  assert.equal(loader.page, 0, '失败后页码必须仍是界面上显示的那一页');
  // 用户再点一次“下一页”：必须还是请求第 1 页
  const requested = [];
  await loader.load(loader.page + 1, (t) => { requested.push(t); return Promise.resolve('第1页'); });
  assert.deepEqual(JSON.parse(JSON.stringify(requested)), [1]);
  assert.equal(loader.page, 1);
});

test('“上一页”失败同样不改变页码', async () => {
  const loader = createPagedLoader();
  await loader.load(2, ok(2));
  await assert.rejects(loader.load(loader.page - 1, fail));
  assert.equal(loader.page, 2);
  await loader.load(loader.page - 1, ok(1));
  assert.equal(loader.page, 1);
});

test('成功后才提交页码，请求进行中页码保持不变', async () => {
  const loader = createPagedLoader();
  const d = deferred();
  const pending = loader.load(3, () => d.promise);
  assert.equal(loader.page, 0, '请求未完成时不能先改页码');
  d.resolve('第3页');
  assert.equal(await pending, '第3页');
  assert.equal(loader.page, 3);
});

test('请求交错：旧请求后返回时不会覆盖新结果，也不会改页码', async () => {
  const loader = createPagedLoader();
  const slow = deferred(), fast = deferred();
  const a = loader.load(1, () => slow.promise);   // 先发出的“下一页”，响应很慢
  const b = loader.load(0, () => fast.promise);   // 随后改了筛选，重置到第 0 页，响应更快
  fast.resolve('筛选后的第0页');
  assert.equal(await b, '筛选后的第0页');
  assert.equal(loader.page, 0);
  slow.resolve('旧的第1页');
  assert.equal(await a, null, '旧请求的结果应被丢弃');
  assert.equal(loader.page, 0, '旧请求不能把页码改回 1');
});

test('旧请求晚于新请求失败：错误被丢弃，不会在新结果旁弹出多余的错误', async () => {
  const loader = createPagedLoader();
  const slow = deferred(), fast = deferred();
  const a = loader.load(1, () => slow.promise);
  const b = loader.load(2, () => fast.promise);
  fast.resolve('第2页');
  await b;
  slow.reject(new Error('旧请求超时'));
  assert.equal(await a, null);
  assert.equal(loader.page, 2);
});

test('新请求失败时，仍在途的旧请求结果也不会被采用（界面保持旧数据，页码不变）', async () => {
  const loader = createPagedLoader();
  await loader.load(0, ok(0));
  const slow = deferred(), bad = deferred();
  const a = loader.load(1, () => slow.promise);
  const b = loader.load(2, () => bad.promise);
  bad.reject(new Error('最新请求失败'));
  await assert.rejects(b, /最新请求失败/);
  slow.resolve('旧的第1页');
  assert.equal(await a, null);
  assert.equal(loader.page, 0, '页码仍与界面上的旧数据一致');
});

test('连续成功的请求：页码总是跟随最后一次成功的请求', async () => {
  const loader = createPagedLoader();
  for (const p of [1, 2, 3, 2, 1, 0]) await loader.load(p, ok(p));
  assert.equal(loader.page, 0);
});
