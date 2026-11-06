const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../backend-java/src/main/resources/static/startup.js'), 'utf8');
const key = 'signalhubStartupPlayed';

// 小型浏览器替身执行真实脚本，覆盖跨页面共享会话和事件生命周期，不等待真实动画时间。
function browser({values = new Map(), reduced = false, dev = true, storageFailure, missing = false} = {}) {
  const timers = new Map(), writes = [], visibility = [];
  const document = {activeElement: null};
  function element() {
    const listeners = new Map();
    return {
      isConnected: true, inert: false,
      addEventListener(name, fn) { listeners.set(name, [...(listeners.get(name) || []), fn]); },
      dispatch(name, extra = {}) { for (const fn of listeners.get(name) || []) fn({target: this, ...extra}); },
      focus() { document.activeElement = this; },
    };
  }
  const body = element(), screen = element(), skip = element(), publication = element(), content = element(), replay = element();
  let hidden = true;
  Object.defineProperty(screen, 'hidden', {get: () => hidden, set(value) { hidden = value; visibility.push(value); }});
  screen.contains = el => el === skip || el === screen;
  document.body = body;
  document.activeElement = body;
  document.querySelector = selector => ({
    '#startup-screen': missing ? null : screen, '#startup-skip': skip, '.publication': publication,
    '#content': content, '#startup-replay': dev ? replay : null,
  })[selector];
  const motion = Object.assign(element(), {matches: reduced});
  const window = Object.assign(element(), {
    matchMedia: () => motion,
    setTimeout(fn, ms) { const id = Symbol(); timers.set(id, {fn, ms}); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  Object.defineProperty(window, 'sessionStorage', {get() {
    if (storageFailure === 'access') throw Error('blocked');
    return {
      getItem(k) { if (storageFailure === 'read') throw Error('blocked'); return values.get(k) ?? null; },
      setItem(k, value) { if (storageFailure === 'write') throw Error('quota'); writes.push([k, value]); values.set(k, value); },
    };
  }});
  Object.defineProperty(window, 'localStorage', {get() { throw Error('must use sessionStorage'); }});
  vm.runInNewContext(source, {document, window});
  return {screen, skip, publication, content, replay, document, window, motion, timers, writes, visibility, values,
    timeout() { const entry = [...timers.values()][0]; assert.ok(entry); entry.fn(); },
    replayNow() { replay.focus(); replay.dispatch('click'); },
  };
}

test('first entry marks the session immediately; refresh/routes skip; a new session plays', () => {
  const values = new Map(), first = browser({values});
  assert.equal(first.screen.hidden, false);
  assert.equal(values.get(key), '1');
  assert.equal(first.publication.inert, true);
  for (let route = 0; route < 3; route++) {
    const next = browser({values});
    assert.equal(next.screen.hidden, true);
    assert.deepEqual(next.visibility, []); // 已播会话从未短暂显示覆盖层。
    assert.equal(next.publication.inert, false);
    assert.equal(next.timers.size, 0);
  }
  assert.equal(browser().screen.hidden, false);
});

test('skip and Escape release focus immediately and keep the played marker', () => {
  for (const action of [b => b.skip.dispatch('click'), b => b.screen.dispatch('keydown', {key: 'Escape'})]) {
    const b = browser();
    action(b);
    assert.equal(b.screen.hidden, true);
    assert.equal(b.publication.inert, false);
    assert.equal(b.document.activeElement, b.content);
    assert.equal(b.values.get(key), '1');
    assert.equal(b.timers.size, 0);
  }
});

test('only overlay exit ends playback; missing/cancelled CSS events have a safe exit', () => {
  const b = browser();
  b.screen.dispatch('animationend', {target: b.skip, animationName: 'signalhub-startup-appear'});
  assert.equal(b.screen.hidden, false);
  b.screen.dispatch('animationend', {animationName: 'signalhub-startup-exit'});
  assert.equal(b.screen.hidden, true);
  assert.equal(b.timers.size, 0);
  const fallback = browser();
  assert.equal([...fallback.timers.values()][0].ms, 2500);
  fallback.timeout();
  assert.equal(fallback.screen.hidden, true);
  const cancelled = browser();
  cancelled.screen.dispatch('animationcancel');
  assert.equal(cancelled.publication.inert, false);
});

test('manual replay preserves the session marker, existing DOM, focus and form state', () => {
  const values = new Map([[key, '1']]), b = browser({values});
  b.content.unsavedNote = '未保存备注';
  for (let repeat = 0; repeat < 2; repeat++) {
    b.replayNow();
    assert.equal(b.screen.hidden, false);
    b.skip.dispatch('click');
    assert.equal(b.document.activeElement, b.replay);
    assert.equal(b.content.unsavedNote, '未保存备注');
  }
  assert.deepEqual(b.writes, []);
  assert.deepEqual([...values], [[key, '1']]);
  assert.equal(browser({values}).screen.hidden, true);
});

test('storage access/read/write failures skip automatically without flashing; dev replay still works', () => {
  for (const storageFailure of ['access', 'read', 'write']) {
    const b = browser({storageFailure});
    assert.equal(b.screen.hidden, true);
    assert.deepEqual(b.visibility, []);
    assert.equal(b.publication.inert, false);
    b.replayNow();
    b.timeout();
    assert.equal(b.screen.hidden, true);
    assert.deepEqual(b.writes, []);
  }
});

test('reduced motion skips auto playback; manual replay is brief and preference changes dismiss it', () => {
  const b = browser({reduced: true});
  assert.deepEqual(b.visibility, []);
  assert.equal(b.values.get(key), '1');
  b.replayNow();
  assert.equal([...b.timers.values()][0].ms, 700);
  b.timeout();
  const changing = browser();
  changing.motion.matches = true;
  changing.motion.dispatch('change');
  assert.equal(changing.screen.hidden, true);
});

test('page lifecycle clears the overlay before back/forward cache restoration', () => {
  const b = browser();
  b.window.dispatch('pagehide');
  assert.equal(b.screen.hidden, true);
  assert.equal(b.publication.inert, false);
  b.window.dispatch('pageshow', {persisted: true});
  assert.equal(b.screen.hidden, true);
  assert.equal(b.timers.size, 0);
  assert.equal(b.values.get(key), '1');
});

test('Tab stays on skip and cleanup restores a pre-existing inert state', () => {
  const b = browser({values: new Map([[key, '1']])});
  b.publication.inert = true;
  b.replayNow();
  let prevented = false;
  b.screen.dispatch('keydown', {key: 'Tab', preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(b.document.activeElement, b.skip);
  b.skip.dispatch('click');
  assert.equal(b.publication.inert, true);
});

test('a page without the overlay is unchanged and does not consume first playback', () => {
  const b = browser({missing: true, dev: false});
  assert.deepEqual(b.writes, []);
  assert.equal(b.timers.size, 0);
});
