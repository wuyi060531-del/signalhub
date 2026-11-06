"use strict";
(() => {
  const screen = document.querySelector("#startup-screen");
  const skip = document.querySelector("#startup-skip");
  const publication = document.querySelector(".publication");
  if (!screen || !skip || !publication) return;

  const sessionKey = "signalhubStartupPlayed";
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let active = false, timer, previousFocus, previousInert;

  function finish(restoreFocus = true) {
    if (!active) return;
    active = false;
    window.clearTimeout(timer);
    const hadFocus = screen.contains(document.activeElement);
    screen.hidden = true;
    publication.inert = previousInert;
    if (restoreFocus && hadFocus) {
      const target = previousFocus?.isConnected && previousFocus !== document.body
        ? previousFocus : document.querySelector("#content");
      target?.focus({preventScroll: true});
    }
  }

  function play() {
    if (active) return;
    previousFocus = document.activeElement;
    previousInert = publication.inert;
    active = true;
    screen.hidden = false;
    publication.inert = true;
    skip.focus({preventScroll: true});
    // CSS 在 2.4 秒后淡出；备用计时确保动画事件缺失时仍能进入页面。
    // 减少动态效果下，手动重播只短暂展示静态品牌，不旋转或渐变。
    timer = window.setTimeout(() => finish(), motion.matches ? 700 : 2500);
  }

  skip.addEventListener("click", () => finish());
  screen.addEventListener("keydown", event => {
    if (event.key === "Escape") finish();
    // 对话框只有一个可聚焦控件；保持键盘焦点在可立即跳过的按钮上。
    if (event.key === "Tab") { event.preventDefault(); skip.focus(); }
  });
  screen.addEventListener("animationend", event => {
    if (event.target === screen && event.animationName === "signalhub-startup-exit") finish();
  });
  screen.addEventListener("animationcancel", event => {
    if (event.target === screen) finish();
  });
  motion.addEventListener("change", () => { if (motion.matches) finish(); });
  // 避免浏览器前进/后退缓存恢复到尚未结束的覆盖层。
  window.addEventListener("pagehide", () => finish(false));
  window.addEventListener("pageshow", event => { if (event.persisted) finish(false); });
  document.querySelector("#startup-replay")?.addEventListener("click", play);

  // 在开始播放时写入，刷新/跳过/提前离开也不会在本会话重复播放。
  // 访问或写入存储失败时直接进入业务页面，不影响 app.js 的独立加载。
  try {
    if (window.sessionStorage.getItem(sessionKey) === "1") return;
    window.sessionStorage.setItem(sessionKey, "1");
  } catch (_) { return; }
  if (!motion.matches) play();
})();
