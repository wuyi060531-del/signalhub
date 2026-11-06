/* Reading-only bilingual presentation. Original fields never change. */
(function (root) {
  "use strict";
  const modes = ["zh", "original", "bilingual"], key = "signalhubReadingMode";
  function normalizeMode(value) { return modes.includes(value) ? value : "zh"; }
  function readPreference(storage) {
    try { return normalizeMode(storage.getItem(key)); } catch (_) { return "zh"; }
  }
  function writePreference(storage, value) {
    try { storage.setItem(key, normalizeMode(value)); return true; } catch (_) { return false; }
  }
  // Conservative language hint, not a language detector: mixed Chinese remains one source.
  function hasChinese(value) { return /[\u3400-\u9fff]/u.test(value || ""); }
  function chineseText(value) {
    const han = (String(value || "").match(/[\u3400-\u9fff]/gu) || []).length;
    const latin = (String(value || "").match(/[a-z]/gi) || []).length;
    return han > 0 && han >= latin / 2;
  }
  function view(item, mode) {
    mode = normalizeMode(mode);
    const p = item.payload || {}, original = item.original || {};
    const title = original.title || item.title || p.title || "未命名信息";
    const body = original.body ?? p.body ?? "";
    const summary = original.summary || p.summary || p.body || "";
    const translation = item.reading?.status === "current" ? item.reading.translation || {} : {};
    const zhTitle = translation.title_zh?.trim();
    const sameTitle = !zhTitle || zhTitle === title || chineseText(title);
    const chineseSource = chineseText(p.body || body) || (!body && chineseText(title));
    return { mode, title, body, summary, translation, chineseSource,
      primaryTitle: mode !== "original" && !sameTitle ? zhTitle : title,
      secondaryTitle: mode !== "original" && !sameTitle ? title : null,
      zhSummary: translation.summary_zh?.trim() || null,
      zhBody: translation.body_zh?.trim() || null,
      status: item.reading?.status || "missing",
      message: item.reading?.status === "stale" ? "中文译文可能已过期，暂不展示，请重新核验" : Object.keys(translation).length ? "暂无中文摘要译文" : "暂无中文译文",
      originalOpen: mode !== "zh" || chineseSource,
    };
  }
  const api = { normalizeMode, readPreference, writePreference, view, hasChinese };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SignalHubReading = api;
})(typeof window === "undefined" ? globalThis : window);
