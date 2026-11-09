"use strict";
const section = document.body.dataset.section,
  content = document.querySelector("#content"),
  demo = document.querySelector("#include-demo");
function stored(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
function store(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* browser storage may be unavailable */ } }
demo.checked = stored("signalhubDemo") === "true";
const readingControl = document.querySelector("#reading-mode");
let readingMode = SignalHubReading.readPreference({getItem: stored});
readingControl.value = readingMode;
const readingBindings = new WeakMap();
function bindReading(host, update) {
  host.dataset.reading = "";
  readingBindings.set(host, update);
  update();
  return host;
}
function updateReadingMode(mode, persist = true) {
  readingMode = SignalHubReading.normalizeMode(mode);
  readingControl.value = readingMode;
  if (persist) SignalHubReading.writePreference({setItem: store}, readingMode);
  document.querySelectorAll("[data-reading]").forEach(host => readingBindings.get(host)?.());
  scheduleTranslation();
}
readingControl.onchange = () => updateReadingMode(readingControl.value);
window.addEventListener("storage", event => {
  if (event.key === "signalhubReadingMode" || event.key === null)
    updateReadingMode(event.newValue, false);
});
const activeLink = document.querySelector(`[data-nav="${section}"]`);
activeLink?.classList.add("active");
activeLink?.setAttribute("aria-current", "page");
function revealCurrentNavigation() {
  const nav = document.querySelector(".publication-nav");
  if (!nav || !activeLink || nav.scrollWidth <= nav.clientWidth) return;
  const bounds = nav.getBoundingClientRect();
  const current = activeLink.getBoundingClientRect();
  const rightPadding = 24;
  if (current.right > bounds.right-rightPadding) nav.scrollLeft += Math.ceil(current.right-bounds.right+rightPadding);
  else if (current.left < bounds.left) nav.scrollLeft += Math.floor(current.left-bounds.left);
}
requestAnimationFrame(revealCurrentNavigation);
window.addEventListener("resize", () => requestAnimationFrame(revealCurrentNavigation));
const labels = {
  eligible: "符合已知条件",
  insufficient_information: "可能符合，信息不足",
  not_eligible: "明确不符合",
  unknown: "未知",
  required: "必备",
  preferred: "加分",
  mentioned: "原文提及",
  not_required: "明确非必需",
  interested: "感兴趣",
  saved: "已收藏",
  preparing: "准备投递",
  applied: "已投递",
  assessment: "笔试",
  interview1: "一面",
  interview_next: "后续面试",
  offer: "Offer",
  rejected: "已拒绝",
  closed: "已结束",
  foreign: "外资企业",
  private: "民营企业",
  joint_venture: "合资企业",
  central_state: "中央企业",
  local_state: "地方国企",
  finance: "金融机构",
  public_institution: "事业单位",
  research: "科研机构",
  other: "其他",
  internship: "实习",
  campus: "校招",
  full_time: "全职",
};

const STATUS_LABELS = {
  eligible: ["符合已知条件", "success"],
  insufficient_information: ["可能符合，信息不足", "warning"],
  not_eligible: ["明确不符合", "danger"],
  verified: ["已验证", "success"],
  test_data: ["演示数据", "warning"],
  manual_only: ["仅手动", "neutral"],
  unverified: ["待验证", "neutral"],
  unavailable: ["暂不可用", "danger"],
  success: ["成功", "success"],
  not_modified: ["无变化", "neutral"],
  failed: ["失败", "danger"],
  partial: ["部分成功", "warning"],
  interrupted: ["已中断", "warning"],
  pending: ["待处理", "neutral"],
  running: ["执行中", "accent"],
  done: ["已完成", "success"],
  disabled: ["已关闭", "neutral"],
  blocked: ["已阻止", "warning"],
  cached: ["使用缓存", "neutral"],
};
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#icon-" + name);
  svg.append(use);
  return svg;
}
function statusText(value) {
  return STATUS_LABELS[value]?.[0] || value || "—";
}
function badge(value) {
  const [text, tone] = STATUS_LABELS[value] || [value || "—", "neutral"];
  return node("span", text, "badge badge-" + tone);
}
const shortTime = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const fullTime = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = Object.fromEntries(
    shortTime.formatToParts(date).map((p) => [p.type, p.value]),
  );
  return (
    parts.month + "月" + parts.day + "日 " + parts.hour + ":" + parts.minute
  );
}
function formatDate(value) {
  if (!value) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-");
    return y + "年" + Number(m) + "月" + Number(d) + "日";
  }
  return formatTime(value);
}
function timeNode(value) {
  if (!value || formatTime(value) === "—") return node("span", "—", "weak");
  const n = node("time", formatTime(value));
  n.dateTime = value;
  n.title = fullTime.format(new Date(value)) + "（Asia/Shanghai）";
  return n;
}
function displayValues(value) {
  if (value == null) return "—";
  if (Array.isArray(value)) return value.map(displayValues);
  if (typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, displayValues(v)]),
    );
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value))
    return fullTime.format(new Date(value)) + "（Asia/Shanghai）";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value))
    return formatDate(value);
  return value;
}
// 资格表里的值可能是字符串、数组或对象：显示成可读文字，而不是原始 JSON。
function readableValue(value) {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map(readableValue).filter((v) => v !== "").join("、");
  if (typeof value === "object")
    return Object.entries(value).map(([k, v]) => k + "：" + readableValue(v)).join("；");
  return String(value);
}
function parseArray(value) {
  try {
    const result = typeof value === "string" ? JSON.parse(value) : value;
    return Array.isArray(result) ? result : [];
  } catch {
    return [];
  }
}
function emptyState(title, description, compact = false) {
  const e = node("div", "", "empty" + (compact ? " inline-empty" : ""));
  append(e, node("strong", title), node("p", description, "muted"));
  return e;
}
const editionDate = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "long",
});
const dateParts = editionDate.formatToParts(new Date());
const dateText = dateParts
  .map((p) => (p.type === "weekday" ? " " + p.value : p.value))
  .join("");
document.querySelector("#edition-date").textContent = dateText;
document.querySelector("#edition-date").dateTime = new Intl.DateTimeFormat(
  "sv-SE",
  {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  },
).format(new Date());
const publicationGroup = {
  overview: "工作台",
  domestic: "求职",
  foreign: "求职",
  opportunities: "求职",
  technology: "情报",
  skills: "情报",
  subscriptions: "管理",
  applications: "管理",
  monitor: "管理",
  settings: "管理",
  import: "导入",
  detail: "档案",
};
document.querySelector("#section-label").textContent =
  publicationGroup[section] || "工作台";
function plainText(value, limit = 160) {
  let text = String(value ?? "");
  const parser = new DOMParser();
  for (let pass = 0; pass < 2; pass++) {
    // 解析到独立文档，仅取文本；不插入 HTML，不加载嵌入资源。
    text = text.replace(
      /<(?:img|iframe|link|source|video|audio)\b[^>]*>/gi,
      "",
    );
    const document = parser.parseFromString(text, "text/html");
    document
      .querySelectorAll("script,style,noscript,template")
      .forEach((n) => n.remove());
    document
      .querySelectorAll("p,div,li,h1,h2,h3,h4,br")
      .forEach((n) => n.append(" "));
    text = document.body.textContent || "";
    if (!/<\/?[a-z][^>]*>/i.test(text)) break;
  }
  text = text.replace(/\s+/g, " ").trim();
  return limit && text.length > limit ? text.slice(0, limit) + "…" : text;
}
function tag(text, tone = "neutral") {
  return node("span", text, "tag tag-" + tone);
}
function scoreIndicator(value) {
  const score =
    value == null ? null : Math.max(0, Math.min(100, Number(value)));
  const tone =
    score == null || score < 40
      ? "neutral"
      : score < 70
        ? "warning"
        : "success";
  const box = node("div", "", "score-indicator score-" + tone);
  append(
    box,
    node("strong", score == null ? "—" : Math.round(score)),
    node("span", score == null ? "尚未计算" : "匹配分", "score-label"),
  );
  const track = node("div", "", "score-track"),
    bar = node("div", "", "score-fill");
  bar.style.width = (score ?? 0) + "%";
  track.setAttribute("aria-hidden", "true");
  track.append(bar);
  box.append(track);
  return box;
}
function actionGroup(...buttons) {
  return append(node("div", "", "actions button-group"), ...buttons);
}
function filterTabs(form, opportunity = false) {
  const bar = node("div", "", "filter-tabs");
  bar.setAttribute("aria-label", opportunity ? "国家筛选" : "招聘类型筛选");
  const options = opportunity
    ? [
        ["", "全部国家"],
        ["CN", "中国"],
        ["US", "美国"],
        ["DE", "德国"],
        ["JP", "日本"],
        ["SG", "新加坡"],
      ]
    : [
        ["", "全部岗位"],
        ["internship", "实习"],
        ["campus", "校招"],
        ["full_time", "全职"],
      ];
  const key = opportunity ? "country" : "employment_type";
  for (const [value, label] of options) {
    const b = node("button", label, "filter-tab" + (!value ? " selected" : ""));
    b.type = "button";
    b.dataset.filterValue = value;
    b.setAttribute("aria-pressed", String(!value));
    b.onclick = () => {
      form.elements[key].value = value;
      sync();
      form.requestSubmit();
    };
    bar.append(b);
  }
  const sync = () => bar.querySelectorAll("button").forEach(b => {
    const selected = b.dataset.filterValue === form.elements[key].value;
    b.classList.toggle("selected", selected);
    b.setAttribute("aria-pressed", String(selected));
  });
  form.addEventListener("change", sync);
  form.addEventListener("reset", () => queueMicrotask(sync));
  return bar;
}
function decorateProfileForm(form, profile) {
  const original = form.querySelector(".grid");
  if (!original) return;
  const groups = [
    [
      "能力与背景",
      "已确认技能与学习中的技能分开记录。",
      ["skills", "learningSkills", "education", "graduationYear", "major", "currentlyStudying", "hasInternshipExperience", "workExperienceYears"],
    ],
    [
      "职业偏好",
      "目标方向、地点和企业偏好用于可解释匹配。",
      ["cities", "roles", "companyTypes", "excludedTerms", "internshipTypes", "employmentTypes"],
    ],
    [
      "实习与薪资",
      "只在相同周期和币种下比较明确薪资。",
      [
        "availableDays",
        "availableMonths",
        "internshipStartFrom",
        "internshipStartTo",
        "hardCity",
        "minimumSalary",
        "salaryPeriod",
        "salaryCurrency",
      ],
    ],
    [
      "匹配权重",
      "按你的侧重点分配评分，所有字段仍可编辑。",
      ["weight_role", "weight_skills", "weight_city", "weight_company", "weight_qualifications"],
    ],
  ];
  const container = node("div", "", "settings-sections");
  groups.forEach(([name, description, names], n) => {
    const row = node("section", "", "settings-row"),
      left = node("div", "", "settings-label"),
      right = node("div", "", "form-fields");
    append(
      left,
      node("span", String(n + 1).padStart(2, "0"), "entry-ordinal"),
      node("h3", name),
      node("p", description, "muted"),
    );
    if (n === 0)
      left.append(
        tag((profile.skills || []).length + " 项已确认技能", "success"),
      );
    for (const key of names) {
      const input = original.querySelector('[name="' + key + '"]');
      if (input) right.append(input.closest(".field"));
    }
    append(row, left, right);
    container.append(row);
  });
  original.replaceWith(container);
}

function node(tag, text = "", cls = "") {
  const n = document.createElement(tag);
  n.textContent =
    typeof text === "string" && /<\/?[a-z][^>]*>/i.test(text)
      ? plainText(text, 0)
      : text;
  if (cls) n.className = cls;
  return n;
}
function append(parent, ...children) {
  children
    .flat()
    .filter(Boolean)
    .forEach((c) => parent.append(c));
  return parent;
}
function card(title, description, action) {
  const c = node("section", "", "card");
  const descriptions = {
    个人求职档案: "记录能力与偏好，所有个人字段仅保存到本地。",
    "可选 AI 增强": "默认关闭，规则功能可以独立运行。",
    "粘贴信息 · 保留来源": "只保存官方链接，正文由本地任务解析。",
    "批量导入 CSV / JSON": "导入有权使用的数据，保留原始来源。",
    技能与原文证据: "区分必备与加分，保留明确的原文依据。",
    可解释岗位匹配: "已知条件、未知条件与明确不符合分别展示。",
    来源与版本历史: "追踪每一次变化和原始来源。",
    "AI 增强 · 建议需核实": "分析建议不能替代官方条件。",
  };
  if (title)
    c.append(
      sectionHeader(
        title,
        description || descriptions[title] || "查看字段、条件与来源依据",
        action,
      ),
    );
  return c;
}
// 列表的页码只在“最新一次请求成功”时才提交：失败时页码不动（界面仍是旧数据，页码必须与之一致），
// 过期请求（被更新的请求取代）的结果和错误都丢弃，旧请求不会覆盖新结果，也不会弹出多余的错误。
function createPagedLoader() {
  let page = 0, latest = 0;
  return {
    get page() { return page; },
    async load(target, fetchPage) {
      const token = ++latest;
      let result;
      try { result = await fetchPage(target); }
      catch (e) { if (token !== latest) return null; throw e; }
      if (token !== latest) return null;
      page = target;
      return result;
    },
  };
}
// 操作发生在长列表下方时，页面顶部的提示和结果都在视口之外，用户会以为“点了没反应”。
function outOfView(rect, viewportHeight) {
  return rect.bottom <= 0 || rect.top >= viewportHeight;
}
function pastTop(rect) {
  return rect.top < 0;
}
function msg(text, error = false) {
  const n = document.querySelector("#notice");
  n.hidden = false;
  n.className = "notice" + (error ? " error" : "");
  n.setAttribute("role", error ? "alert" : "status");
  n.replaceChildren(node("span", text));
  // 错误必须被看见；成功提示不打断用户当前位置。
  if (error && outOfView(n.getBoundingClientRect(), window.innerHeight))
    n.scrollIntoView({block: "nearest"});
}
async function api(path, method = "GET", data) {
  const headers = {};
  if (method !== "GET")
    headers[document.querySelector("meta[name=csrf-header]").content] =
      document.querySelector("meta[name=csrf]").content;
  if (data && !(data instanceof FormData))
    headers["Content-Type"] = "application/json";
  const r = await fetch("/api" + path, {
    method,
    headers,
    body: data
      ? data instanceof FormData
        ? data
        : JSON.stringify(data)
      : undefined,
  });
  const value = await r
    .json()
    .catch(() => ({ error: "请求失败，请刷新页面后重试" }));
  if (!r.ok) throw Error(value.error || "请求失败");
  return value;
}
function button(text, action, primary = false) {
  const b = node(
    "button",
    text,
    "btn " +
      (primary === true
        ? "btn-primary"
        : typeof primary === "string"
          ? primary
          : ""),
  );
  b.type = "button";
  b.onclick = async () => {
    const original = [...b.childNodes];
    b.disabled = true;
    b.setAttribute("aria-busy", "true");
    b.replaceChildren(node("span", "加载中…"));
    try {
      await action();
    } catch (e) {
      msg(e.message, true);
    } finally {
      b.disabled = false;
      b.removeAttribute("aria-busy");
      b.replaceChildren(...original);
    }
  };
  return b;
}
async function taskFeedback(taskId) {
  const panel = card("任务 #" + taskId, "等待 Python worker 执行，排队不表示处理成功"),
    state = node("div"), actions = node("div", "", "actions");
  let refreshed = false;
  const check = async () => {
    const task = await api("/tasks/" + taskId), result = task.result || {};
    state.replaceChildren(badge(task.state));
    state.append(node("p", "尝试次数：" + task.attempts));
    if (task.state === "pending" || task.state === "running") {
      state.append(node("p", "任务仍在处理。离开页面不会取消任务，可在数据源与任务页继续查看。", "muted"));
      return false;
    }
    if (task.task_type === "enrich") {
      state.append(node("p", result.message || ({disabled:"AI 已关闭，未调用模型",blocked:"AI 请求被阻止",cached:"使用已有分析缓存",success:"分析完成，请核验原文",failed:"增强失败，原文与规则结果保留"}[result.state] || "查看任务结果")));
    } else {
      state.append(node("p", "新增 " + (result.inserted || 0) + " · 更新 " + (result.updated || 0) + " · 去重 " + (result.deduplicated || 0) + " · 失败 " + (result.failed || 0)));
      if (task.state === "failed") state.append(node("p", "任务存在失败；已成功入库的记录保留。核对错误后沿用稳定来源标识重新提交。", "notice error"));
      if (!refreshed && ((result.inserted || 0) + (result.updated || 0) > 0 || task.state === "done")) {
        try {
          await api("/matches/refresh", "POST", {});
          refreshed = true;
          state.append(node("p", "岗位匹配与本地订阅提醒已刷新。"));
        } catch (e) {
          state.append(node("p", "数据处理结果已保存，匹配刷新暂时失败；可稍后检查任务或在总览重试。", "notice error"));
        }
      }
    }
    if (task.error) state.append(node("p", "任务错误：" + task.error));
    if (Array.isArray(result.item_ids) && result.item_ids.length) {
      const links = node("div", "", "actions");
      result.item_ids.forEach(id => {
        if (Number.isSafeInteger(id) && id > 0)
          links.append(Object.assign(node("a", "查看已保存信息 #" + id), {href: "/view/detail?id=" + id}));
      });
      state.append(links);
      if (result.item_count > result.item_ids.length)
        state.append(node("p", "此处展示前 " + result.item_ids.length + " 条；其余请在列表按手动来源筛选。", "muted"));
    }
    if (task.result) state.append(disclosure("处理结果与错误详情", pre(task.result)));
    return true;
  };
  actions.append(button("检查任务最新结果", check));
  for (const [url,label] of [["/view/monitor","数据源与任务"],["/view/domestic","国内岗位"],["/view/foreign","外企岗位"],["/view/technology","技术情报"],["/view/opportunities","海外机会"]]) {
    const link = node("a", label); link.href = url; actions.append(link);
  }
  append(panel, state, actions); content.append(panel);
  for (let n = 0; n < 30 && panel.isConnected; n++) {
    try { if (await check()) return; }
    catch (e) { state.replaceChildren(node("p", "暂时无法读取任务状态；任务不会因此取消，可点击检查重试。", "notice error")); return; }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
}
function field(name, label, type = "text", value = "") {
  const l = node("label", label, "field"),
    n = node(type === "textarea" ? "textarea" : "input");
  n.name = name;
  if (type !== "textarea") n.type = type;
  n.value = value ?? "";
  l.append(n);
  return l;
}
function select(name, label, options, value = "") {
  const l = node("label", label, "field"),
    s = node("select");
  s.name = name;
  for (const [v, t] of options) {
    const o = node("option", t);
    o.value = v;
    s.append(o);
  }
  const requested = String(value ?? "");
  s.value = options.some(([v]) => String(v) === requested) ? requested : String(options[0]?.[0] ?? "");
  l.append(s);
  return l;
}
function pre(value) {
  return node(
    "pre",
    typeof value === "string"
      ? value
      : JSON.stringify(displayValues(value), null, 2),
  );
}
function table(headers, rows, options = {}) {
  const wrapper = node("div", "", "table-wrap"),
    t = node("table", "", "data-table " + (options.className || "")),
    head = node("thead"),
    tr = node("tr");
  headers.forEach((h) => {
    const th = node("th", h);
    th.scope = "col";
    tr.append(th);
  });
  head.append(tr);
  t.append(head);
  const body = node("tbody");
  rows.forEach((row) => {
    const r = node("tr");
    row.forEach((v) => {
      const td = node("td");
      td.append(v instanceof Node ? v : node("span", v ?? "—"));
      r.append(td);
    });
    body.append(r);
  });
  if (!rows.length) {
    const tr = node("tr", "", "table-empty"),
      td = node("td");
    td.colSpan = headers.length;
    td.append(
      emptyState(
        options.emptyTitle || "暂无记录",
        options.emptyText || "有新的数据时，会显示在这里。",
        true,
      ),
    );
    tr.append(td);
    body.append(tr);
  }
  t.append(body);
  wrapper.append(t);
  return wrapper;
}
function query(extra = {}) {
  return new URLSearchParams({
    includeDemo: String(demo.checked),
    ...extra,
  }).toString();
}

// textContent is the only insertion path for source and translated text.
function readingText(tag, text, cls = "") {
  const el = document.createElement(tag);
  el.textContent = text || "";
  el.className = cls;
  return el;
}
function readingTitle(item, detail = false) {
  const host = node("div", "", "reading-title" + (detail ? " reading-detail-title" : ""));
  host.readingItem=item;
  scheduleTranslation();
  return bindReading(host, () => {
    const v = SignalHubReading.view(item, readingMode);
    const title = readingText(detail ? "h2" : "a", plainText(v.primaryTitle, 0), detail ? "reading-heading" : "entry-title");
    if (!detail) title.href = "/view/detail?id=" + item.id;
    host.replaceChildren(title);
    if (v.secondaryTitle) host.append(readingText("p", "原标题：" + plainText(v.secondaryTitle, 0), "reading-original-title muted"));
    if(v.translation.method?.startsWith("local_nmt"))host.append(node("small","机器参考译文","reading-machine-label"));
  });
}
function readingSummary(item, detail = false) {
  const host = node("div", "", "reading-summary");
  return bindReading(host, () => {
    const v = SignalHubReading.view(item, readingMode);
    host.replaceChildren();
    const add = (label, text, cls = "") => {
      if (detail && label) host.append(node("h3", label));
      host.append(readingText("p", plainText(text, detail ? 0 : 160), cls || (detail ? "body-text" : "entry-summary")));
    };
    if (v.chineseSource) {
      if (!detail) add("", v.summary);
      return;
    }
    if (v.mode === "original") { if (!detail) add("", v.summary); return; }
    if (v.zhSummary) add(v.translation.method?.startsWith("local_nmt") ? "中文摘要 · 原文重点节选的机器译文" : "中文摘要 · 参考", v.zhSummary);
    else host.append(readingText("p", v.message + (detail ? "；可展开下方已保存原文。" : " · 下方为原文节选"), "reading-unavailable muted"));
    if (!detail && (!v.zhSummary || v.mode === "bilingual")) add("", v.summary);
    if (detail && Object.keys(v.translation).length)
      host.append(readingText("p", "译文依据：" + v.translation.attribution + " · 中文仅供参考，条件以原文为准。", "muted reading-attribution"));
  });
}
function readableOriginal(value) {
  // Preserve paragraph boundaries while removing executable markup in a detached document.
  const doc = new DOMParser().parseFromString(String(value || "").replace(/<(?:img|iframe|link|source|video|audio)\b[^>]*>/gi, ""), "text/html");
  doc.querySelectorAll("script,style,noscript,template").forEach(n => n.remove());
  doc.querySelectorAll("p,div,li,h1,h2,h3,h4,br,section").forEach(n => n.append("\n"));
  return (doc.body.textContent || "").replace(/\n[ \t]+/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}
function readingBody(item) {
  const host = node("section", "", "reading-body");
  return bindReading(host, () => {
    const v = SignalHubReading.view(item, readingMode), original = item.original || {};
    const sameMode=host.dataset.mode===v.mode;
    const originalOpen=sameMode?host.querySelector(".reading-original")?.open:undefined;
    const exactOpen=sameMode?host.querySelector(".reading-exact")?.open:undefined;
    const chineseOpen=sameMode?host.querySelector("details.reading-chinese")?.open:undefined;
    host.dataset.mode=v.mode;
    host.replaceChildren();
    if (v.mode === "bilingual" && v.zhBody && !v.chineseSource) host.classList.add("reading-columns");
    else host.classList.remove("reading-columns");
    if (!v.chineseSource) {
      const chinese = node(v.mode === "original" ? "details" : "div", "", "reading-chinese");
      if (v.mode === "original") {chinese.open=chineseOpen??false;chinese.append(node("summary", "查看中文参考译文"));}
      else chinese.append(node("h3", v.translation.method?.startsWith("local_nmt") ? (v.translation.body_complete ? "中文正文 · 机器参考" : "中文正文节选 · 机器参考") : "中文参考译文"));
      if (v.zhBody) chinese.append(readingText("p", v.zhBody, "body-text"));
      else chinese.append(readingText("p", v.status === "stale" ? v.message : "暂无中文正文译文", "muted"));
      // In original-first mode a title/summary-only review can still be expanded.
      if (v.mode === "original" && !v.zhBody && (v.translation.title_zh || v.zhSummary)) {
        if (v.translation.title_zh) chinese.append(readingText("p", v.translation.title_zh));
        if (v.zhSummary) chinese.append(readingText("p", v.zhSummary, "body-text"));
      }
      if(v.translation.method?.startsWith("local_nmt")) {
        chinese.append(node("p",v.translation.warning,"muted"));
        if(!v.translation.body_complete)chinese.append(node("p","已处理保存正文 " + (v.translation.processed_source_chars ?? v.translation.translated_source_chars) + " / " + v.translation.total_source_chars + " 字，其中可读中文/成功译出 " + v.translation.translated_source_chars + " 字；回退片段或未覆盖内容请查看原文。","muted"));
        if(v.translation.fallback_segments)chinese.append(node("p",v.translation.fallback_segments + " 个片段未通过翻译校验，保留原文。","muted"));
        if(v.translation.requirements_zh?.length) {
          chinese.append(node("h4","关键要求 · 机器参考，性质以原始技能/资格表为准"));
          v.translation.requirements_zh.forEach(x=>chinese.append(readingText("p",x.translation,"body-text"),evidenceDisclosure(x.original)));
        }
      }
      if (v.translation.attribution) chinese.append(readingText("p", "译文依据：" + v.translation.attribution, "muted"));
      host.append(chinese);
    }
    const saved = node("details", "", "reading-original"), toggle = node("summary");
    saved.open = originalOpen ?? v.originalOpen;
    const label = v.chineseSource ? "原文" : "原文（保留来源语言）";
    const sync = () => { toggle.textContent = (saved.open ? "收起" : "查看") + label; };
    saved.ontoggle = sync;
    sync();
    saved.append(toggle);
    if (!original.complete) saved.append(node("p", "暂无完整原文" + (original.kind === "excerpt" ? "；以下为订阅源保存内容，可能仅含节选，不能代替官网全文。" : original.kind === "provided" ? "；以下为手动提供的文本，未确认是否为完整来源正文。" : original.kind === "normalized" ? "；以下为已保存的规范正文，未冒充来源全文。" : "；请查看原始链接。"), "muted"));
    else saved.append(node("p", "以下为当前版本保存的来源正文；未重新访问官网，当前招聘条件请核对来源链接。", "muted"));
    if (v.body) {
      saved.append(readingText("div", readableOriginal(v.body), "body-text saved-original-body"));
      const exact = node("details", "", "reading-exact");
      exact.open=exactOpen??false;
      exact.append(node("summary", "查看保存的原始文本（含格式标记）"), readingText("pre", v.body, "body-text"));
      saved.append(exact);
    }
    host.append(saved);
  });
}

let translationStartTimer, translationPollTimer, translationGeneration=0;
function scheduleTranslation() {
  clearTimeout(translationStartTimer);
  translationStartTimer=setTimeout(()=>translateVisible().catch(()=>translationMessage("本地翻译暂不可用，原文照常可读。")),0);
}
function visibleReadingItems() {
  return [...new Map([...document.querySelectorAll(".reading-title")].map(host=>[host.readingItem.id,host.readingItem])).values()].slice(0,20);
}
function translationMessage(value) {
  const message=document.querySelector("#translation-progress");
  if(message)message.textContent=value;
}
async function translateVisible(retry=false) {
  const generation=++translationGeneration;
  clearTimeout(translationPollTimer);
  const all=visibleReadingItems(), tools=document.querySelector("#reading-tools");
  tools.hidden=readingMode==="original" || !all.length;
  if(tools.hidden)return;
  const depth=section==="detail"?2:1;
  const items=all.filter(item=>{
    const view=SignalHubReading.view(item,readingMode), t=view.translation;
    return (!view.chineseSource || !SignalHubReading.hasChinese(view.title)) && item.reading?.error!=="source_updated" && (retry || !item.reading?.error) && !(t.body_zh && t.title_zh && t.summary_zh && t.reviewed===true) && (t.depth||0)<depth;
  });
  if(!items.length) {translationMessage(all.some(x=>x.reading?.error)?"有参考译文生成失败或内容已更新；保留原文，可重试。":all.every(x=>{const v=SignalHubReading.view(x,readingMode);return v.chineseSource&&SignalHubReading.hasChinese(v.title);})?"当前内容为中文，可直接阅读。":"已有译文已缓存；机器参考内容仍需核验。");return;}
  const runtime=await api("/translations/status");
  if(generation!==translationGeneration)return;
  if(!runtime.available) {translationMessage(runtime.message);return;}
  const request=await api("/translations","POST",{ids:items.map(x=>x.id),depth,retry});
  if(generation!==translationGeneration)return;
  if(request.state!=="accepted") {translationMessage(request.message);return;}
  translationMessage("本地免费参考翻译处理中，可继续阅读；不会发送内容到外部服务。");
  const poll=async(attempt=0)=>{
    if(generation!==translationGeneration)return;
    const rows=await api("/reading?"+items.map(x=>"ids="+x.id).join("&"));
    if(generation!==translationGeneration)return;
    let changed=false;
    for(const row of rows) {
      const item=items.find(x=>x.id===row.id);
      if(!item)continue;
      const next=row.content_hash && row.content_hash!==item.content_hash?{status:"stale",error:"source_updated"}:row.reading;
      if(JSON.stringify(item.reading)!==JSON.stringify(next)){item.reading=next;changed=true;}
    }
    if(changed)document.querySelectorAll("[data-reading]").forEach(host=>readingBindings.get(host)?.());
    const pending=items.some(x=>!x.reading?.error && ((x.reading?.translation?.depth||0)<depth || x.reading?.processing));
    if(pending && attempt<60)translationPollTimer=setTimeout(()=>poll(attempt+1).catch(()=>translationMessage("翻译状态暂不可用，后台任务保留；可手动检查。")),3000);
    else translationMessage(pending?"后台仍在处理，可稍后点击检查；原文可正常阅读。":items.some(x=>x.reading?.error)?"部分译文失败，原文已保留，可点击重试。":"本页参考译文已缓存；请结合原文核验条件。");
  };
  await poll();
}
document.querySelector("#translate-visible").onclick=()=>translateVisible(true).catch(()=>translationMessage("本地翻译暂不可用，原文照常可读。"));
function itemCard(item, compact = false, index = 1) {
  const p = item.payload,
    row = node("article", "", "intelligence-row"),
    main = node("div", "", "entry-body"),
    source = node("span", p.company || "来源待确认", "entry-source"),
    title = readingTitle(item);
  const metadata = node("div", "", "entry-meta");
  if (p.kind !== "release")
    metadata.append(
      tag(p.country || "国家未知", p.country ? "info" : "warning"),
    );
  else {
    metadata.append(tag("技术更新", "info"));
    if (p.version_tag) metadata.append(tag(p.version_tag, "info"));
  }
  if (p.city) metadata.append(tag(p.city));
  else if (p.kind === "job") metadata.append(tag(p.country ? "城市未知" : "地点未知", "warning"));
  const extraLocations = (p.locations || []).filter(x => !x.primary);
  for (const location of extraLocations.slice(0, 3))
    metadata.append(tag("附加：" + ([location.country, location.city || location.name].filter(Boolean).join(" · ") || "地点未知"), location.country ? "info" : "warning"));
  if (extraLocations.length > 3) metadata.append(tag("另有 " + (extraLocations.length - 3) + " 个地点 · 见详情", "info"));
  if (p.kind === "job")
    metadata.append(
      tag(
        labels[p.employment_type] || "岗位类型未知",
        p.employment_type ? "info" : "warning",
      ),
    );
  if (p.kind === "job") {
    metadata.append(tag("实习类别：" + (p.internship_type || "未知"), p.internship_type ? "info" : "warning"));
    metadata.append(tag(({confirmed:"明确接受本科在读（其他资格另核验）",excluded:"本科条件不符合",unconfirmed:"本科在读资格未知"}[item.bachelor_status]) || "本科在读资格未知",item.bachelor_status === "confirmed" ? "success" : "warning"));
  }
  if (item.hard_status)
    metadata.append(
      tag(
        labels[item.hard_status],
        item.hard_status === "eligible"
          ? "success"
          : item.hard_status === "not_eligible"
            ? "danger"
            : "warning",
      ),
    );
  if (p.kind === "opportunity") {
    metadata.append(
      tag(
        p.funding ? "资助条件已提供" : "资助未知",
        p.funding ? "info" : "warning",
      ),
    );
    metadata.append(tag("签证信息未确认", "warning"));
  }
  if (p.kind === "job" && item.mainland_work_status === "non_mainland") metadata.append(tag("港澳台工作地点 · 不属大陆中心", "warning"));
  if (p.kind === "job" && item.mainland_work_status === "secondary_review") metadata.append(tag("附加大陆地点待核验", "warning"));
  if (p.kind === "job") {
    const origin = item.employer?.status === "verified" ? item.employer.origin : null;
    metadata.append(tag(origin === "china_local" ? "中国本土企业" : origin === "foreign" ? "已核验境外企业" : "企业待分类", ["china_local", "foreign"].includes(origin) ? "info" : "warning"));
    const recruitment = item.recruitment;
    metadata.append(tag(recruitment?.label || "历史存档，状态未知", recruitment?.state === "closed" ? "danger" : recruitment?.state === "recently_listed" ? "info" : "warning"));
    if (!p.published_at) metadata.append(tag("发布日期未知", "warning"));
  }
  if (p.is_demo) metadata.append(tag("演示数据", "warning"));
  if (item.deadline_status === "expired")
    metadata.append(tag("申请已截止", "danger"));
  append(
    main,
    source,
    title,
    metadata,
    readingSummary(item),
  );
  if (p.kind === "job" && item.explanation) {
    const result=item.explanation;
    if(p.qualification_review_notes?.length)main.append(node("p","原文资格需复核：" + p.qualification_review_notes.join("；"),"entry-match-reasons"));
    const leading=result.qualifications?.find(c=>c.status === "conflict")?.reason || result.breakdown?.find(c=>c.key === "role")?.reason;
    const next=result.nextSteps?.[0];
    const pending=[...(result.qualifications || []).filter(c=>c.status === "unconfirmed").map(c=>c.label),...(result.skillConditions || []).filter(c=>c.status === "unconfirmed" && c.requirement === "required").map(c=>"必备技能 " + c.names.join(" / "))];
    if(pending.length)main.append(node("p","待确认：" + [...new Set(pending)].join("；"),"entry-match-reasons"));
    main.append(node("p",[leading,next && next!==leading?next:null].filter(Boolean).slice(0,2).join("；"),"entry-match-reasons"), Object.assign(node("a","查看详细评分解释","reading-explanation-link"),{href:"/view/detail?id="+item.id}));
  }
  if (p.kind === "job") {
    const provenance=(item.provenance || []).map(x=>x.name).filter(Boolean);
    main.append(node("p", "来源：" + (provenance.join(" / ") || "未存档") + "；最近人工核验：" + (p.source_verified_at ? new Date(p.source_verified_at).toLocaleString("zh-CN", {timeZone:"Asia/Shanghai"}) : "未知（采集成功不等于仍在招聘）"),"muted"));
    if (p.source_verification_note)main.append(node("p","导入者核验说明："+p.source_verification_note,"muted"));
    if (p.url)main.append(Object.assign(node("a","官方申请 / 核对原始岗位"),{href:p.url,target:"_blank",rel:"noopener noreferrer"}));
  }
  const right = node("div", "", "entry-indicator");
  if (p.kind === "job") right.append(item.matching_status === "pending" ? tag("等待匹配刷新", "warning") : scoreIndicator(item.score));
  else
    append(
      right,
      timeNode(p.published_at || item.first_seen),
      node("small", p.published_at ? "发布时间" : "发现时间", "muted"),
    );
  append(
    row,
    node("span", String(index).padStart(2, "0"), "entry-ordinal"),
    main,
    right,
  );
  return row;
}
let alertPage = 0;
let alertState = "unread", alertType = "actionable";
const alertTypes = { change: "原始记录变化", maintenance: "解析维护历史", subscription: "订阅匹配", schedule: "已确认日程", other: "其他提醒" };
function jobScopeLink(label, scope, view = "target") {
  return Object.assign(node("a", label), {href: "/view/" + (scope === "foreign" ? "foreign" : "domestic") + "?" + new URLSearchParams({scope, view})});
}
async function overview() {
  const [jobs, releases, allSummary] = await Promise.all([
    api("/job-overview"),
    api("/items?" + query({kind: "release", size: 5, sort: "updated_desc"})),
    api("/alerts/summary"),
  ]);
  const alertQuery = new URLSearchParams({ state: alertState, type: alertType, includeDemo: String(demo.checked) });
  const summary = await api("/alerts/summary?" + alertQuery);
  alertPage = Math.min(alertPage, Math.max(0, Math.ceil(summary.total / 12) - 1));
  const alerts = await api("/alerts?" + alertQuery + "&page=" + alertPage + "&size=12");
  content.replaceChildren();
  const metrics = node("div", "", "metrics");
  [
    ["本土企业 · 大陆真实岗位", jobs.classification.domestic.jobs],
    ["在华外企 · 大陆真实岗位", jobs.classification.foreign.jobs],
    ["符合已知条件的技术实习", jobs.attention.total],
    ["技术实习 · 资格待核验", jobs.leads.total],
  ].forEach(([label, total], i) =>
    metrics.append(
      append(
        node("div", "", "metric " + (i === 2 ? "metric-info" : "")),
        node("span", label, "muted"),
        node("strong", total),
      ),
    ),
  );
  content.append(metrics);
  const scopeNote = node("div", "", "guidance");
  scopeNote.append(node("p", "中国求职推荐仅使用已记录中国大陆主工作地点的真实岗位，按当前档案识别目标技术方向。成都、重庆优先，其次匹配度、内容更新时间；每个板块同一企业最多展示 2 条，板块间不重复。资格符合不等于目前仍在招聘，申请前请核验官方原文。"));
  scopeNote.append(node("p", "首页推荐始终排除演示数据、海外和地点未知岗位。企业归属未知保留“企业待分类”标签，不计入本土企业或在华外企数量。", "muted"));
  scopeNote.append(actionGroup(
    jobScopeLink("本土企业岗位（" + jobs.classification.domestic.jobs + "）", "domestic", "all"),
    jobScopeLink("在华外企岗位（" + jobs.classification.foreign.jobs + "）", "foreign", "all"),
    jobScopeLink("大陆企业待分类（" + jobs.classification.unclassified.jobs + "）", "unclassified", "all"),
    jobScopeLink("全球全部存档（含海外 / 未知）", "all", "all"),
  ));
  if (!jobs.classification.domestic.jobs) scopeNote.append(node("p", "当前尚无已核验中国本土企业岗位；本土类别实际贡献岗位的来源为 " + jobs.classification.domestic.sourceCount + " 个。尚未形成“本土企业已核验 + 大陆工作地点”的真实岗位记录，可从官方具体 JD 导入，或先查看在华外企及待分类线索。", "muted"));
  content.append(scopeNote);
  const recommendations = [
    ["attention", "符合已知条件的技术实习", "本科在读资格明确，严格资格检查通过；不推定可于 2027 年春季入职或现在仍在招。", "当前没有符合全部已知条件的技术实习", "资格缺失或明确冲突不会被当成符合；可继续查看下方待核验线索。"],
    ["leads", "技术实习线索 · 资格待核验", "技术方向符合，尚无已知硬性冲突；至少有资格条件待确认，不代表已经符合。", "当前没有可展示的待核验实习线索", "需要大陆工作地点、目标技术方向及存档来源；不会以海外或不相关岗位补足。"],
    ["target", "大陆目标技术岗位 · 补充线索", "补充展示其余目标方向岗位；可能不是实习，或来源核验尚未满足实习线索条件。已知硬性冲突与明确失效岗位不进入首页。", "当前没有其他合格候选", "全部存档仍可查看；未知招聘类型、日期和资格保持未知。"],
  ];
  for (const [view, title, description, emptyTitle, emptyDescription] of recommendations) {
    const linkText = {attention: "查看严格视图 →", leads: "查看全部实习线索 →", target: "查看目标方向全部 →"}[view];
    const preview = jobs[view], panel = card(title, description, jobScopeLink(linkText, "mainland", view));
    panel.dataset.jobPreview = view;
    panel.append(node("p", "中国大陆 · 真实数据 · " + preview.total + " 条候选，本页展示 " + preview.items.length + " 条 · 排序：成都 / 重庆优先 → 匹配度 → 本地内容更新时间", "muted"));
    if (view !== "attention") panel.append(node("p", "本栏候选已排除上方板块；完整视图会保留其原有范围与资格标签。", "muted"));
    if (!preview.items.length) panel.append(emptyState(emptyTitle, emptyDescription));
    preview.items.forEach((item, index) => panel.append(itemCard(item, true, index + 1)));
    content.append(panel);
  }
  const start = card("开始使用", "从个人档案到真实来源，建立你的信息工作流"),
    guide = node("div", "", "guidance");
  append(
    guide,
    node(
      "p",
      "先完善求职档案，再粘贴 JD 或接入公开信息源。未知条件保持未知，演示数据明确标记。",
    ),
    actionGroup(
      button(
        "载入离线演示",
        async () => {
          const r = await api("/demo", "POST", {});
          demo.checked = true;
          store("signalhubDemo", "true");
          msg(
            "演示任务 #" +
              r.taskId +
              " 已排队；请确保 Python worker 已启动，稍后刷新。",
          );
        },
        true,
      ),
      button(
        "刷新匹配与提醒",
        async () => {
          const r = await api("/matches/refresh", "POST", {});
          msg("已计算 " + r.matchedJobs + " 个岗位。");
          await overview();
        },
        "btn-secondary",
      ),
    ),
  );
  start.append(guide);
  content.append(start);
  const technology = card("技术动态 · 最近更新", "独立技术栏目，按本地内容更新时间倒序；不代表发布时间，与岗位推荐分开");
  if (!releases.items.length)
    technology.append(
      emptyState("暂无技术动态", "添加 GitHub 仓库或技术 RSS 来源。"),
    );
  releases.items.forEach((i, n) =>
    technology.append(itemCard(i, true, n + 1)),
  );
  content.append(technology);
  const notices = card("站内提醒 · 全部存档范围", "包括海外岗位与技术记录；默认未读业务提醒，提醒不等于中国求职推荐");
  const filters = node("form", "", "toolbar");
  const stateField = select("alertState", "阅读状态", [["unread", "未读"], ["all", "全部"], ["read", "已读"]], alertState);
  const typeField = select("alertType", "提醒分类", [["actionable", "业务提醒"], ["all", "全部历史"], ...Object.entries(alertTypes)], alertType);
  filters.append(stateField, typeField, button("筛选提醒", async () => { alertState = stateField.querySelector("select").value; alertType = typeField.querySelector("select").value; alertPage = 0; await overview(); }));
  filters.addEventListener("submit", e => e.preventDefault());
  notices.append(filters, node("p", "全库未读 " + allSummary.unread + " 条；同一原始记录的解析升级归为维护历史，不能视为官网改动。演示提醒遵循顶部开关。", "muted"));
  if (summary.unread) notices.append(button("将当前筛选结果标记已读（" + summary.unread + "条）", async () => {
    const r = await api("/alerts/read?" + alertQuery + "&throughId=" + summary.through_id, "PUT", {});
    msg("已标记 " + r.updated + " 条；提醒历史保留，新到达提醒不受影响。");
    await overview();
  }, "btn-secondary"));
  if (!alerts.length)
    notices.append(
      emptyState("暂无提醒", "创建订阅后，重要变化会出现在这里。"),
    );
  notices.append(node("p", "第 " + (alertPage + 1) + " 页 · 当前筛选 " + summary.total + " 条 · 未读 " + summary.unread + " 条", "muted"));
  alerts.forEach((a, n) => {
    const row = node("article", "", "notification-row");
    append(
      row,
      node("span", String(alertPage * 12 + n + 1).padStart(2, "0"), "entry-ordinal"),
      append(
        node("div"),
        tag(a.read_at ? "已读" : "未读", a.read_at ? "neutral" : "danger"),
        tag(alertTypes[a.alert_type] || "其他提醒", a.alert_type === "maintenance" ? "warning" : "info"),
        node("p", plainText(a.message, 0)),
        timeNode(a.created_at),
        a.item_id ? Object.assign(node("a", "查看详情与版本"), {href: "/view/detail?id=" + a.item_id}) : null,
      ),
      a.read_at
        ? null
        : button(
            "标记已读",
            async () => {
              await api("/alerts/" + a.id + "/read", "PUT", {});
              await overview();
            },
            "btn-text",
          ),
    );
    notices.append(row);
  });
  const paging = actionGroup();
  if (alertPage > 0) paging.append(button("较新提醒", async () => { alertPage--; await overview(); }));
  if ((alertPage + 1) * 12 < summary.total) paging.append(button("更早提醒", async () => { alertPage++; await overview(); }));
  notices.append(paging);
  content.append(notices);
}
function filterForm() {
  const f = node("form", "", "toolbar");
  append(
    f,
    field("q", "搜索标题 / 正文"),
    field("city", "城市"),
    field("province", "省份 / 地区（明确记录）"),
    select("remote", "远程条件", [["", "全部"], ["true", "明确支持远程"], ["false", "明确不支持远程"], ["unknown", "未确认"]]),
    field("internship_type", "实习类型，例如日常 / 暑期"),
    field("recruitment_batch", "招聘批次，例如春招 / 秋招"),
    select("company_type", "企业类型（岗位按核验资料）", [
      ["", "全部"],
      ["unknown", "尚未核验"],
      ["publicly_listed", "上市公司"],
      ["foundation_owned", "基金会主要持股"],
      ...Object.entries(labels).filter(([k]) =>
        [
          "foreign",
          "private",
          "central_state",
          "local_state",
          "joint_venture",
          "finance",
          "public_institution",
          "research",
        ].includes(k),
      ),
    ]),
    select("category", "职业方向", [
      ["", "全部"],
      ["data_engineering", "数据开发"],
      ["java_backend", "Java 后端"],
      ["ai", "AI 应用"],
      ["data_analysis", "数据分析"],
      ["python", "Python"],
    ]),
    select("employment_type", "招聘类型", [
      ["", "全部"],
      ["internship", "实习"],
      ["campus", "校招"],
      ["full_time", "全职"],
    ]),
    field("country", "国家代码 CN / SG"),
    field("education", "最低学历代码"),
    field("source", "来源 ID", "number"),
    field("from", "首次发现从", "date"),
    field("to", "首次发现至", "date"),
  );
  const submit = node("button", "筛选", "primary");
  submit.type = "submit";
  f.append(submit);
  return f;
}
async function listing() {
  content.replaceChildren();
  const f = filterForm(), out = node("div"), isJob = ["domestic", "foreign"].includes(section);
  if (section !== "technology") content.append(filterTabs(f, section === "opportunities"));
  const advanced = node("details", "", "advanced-filters");
  append(advanced, node("summary", "搜索与更多筛选"), f);
  append(content, advanced, out);
  const pager = createPagedLoader();
  let scope, sorting, eligibility, jobView, summary, coverageNote;
  const scopeNames = {mainland: "大陆实习与求职机会", domestic: "中国本土企业岗位", foreign: "在华外企岗位", unclassified: "企业待分类 · 大陆", all: "全部存档岗位"};
  if (isJob) {
    summary = await api("/classification-summary");
    const initial = new URLSearchParams(location.search), controls = node("div", "", "toolbar job-reading-controls");
    const initialScope = Object.hasOwn(scopeNames, initial.get("scope")) ? initial.get("scope") : section;
    const initialView = ["attention", "leads", "target", "all"].includes(initial.get("view")) ? initial.get("view") : "target";
    scope = select("scope", "岗位范围", [["mainland", "大陆全部企业"], ["domestic", "中国本土企业 · 大陆"], ["foreign", "在华外企 · 大陆"], ["unclassified", "大陆岗位 · 企业待分类"], ["all", "全部存档岗位（含海外/未知）"]], initialScope).querySelector("select");
    sorting = select("sort", "排序", [["match_desc", "匹配度：从高到低"], ["recommendation", "成都 / 重庆优先，再按匹配度"], ["match_asc", "匹配度：从低到高"], ["updated_desc", "最近更新（本地内容）"], ["published_desc", "最新发布（未知置后）"], ["first_seen_desc", "最近发现"], ["deadline_asc", "截止日期最近"]], "match_desc").querySelector("select");
    eligibility = select("eligibility", "资格范围", [["", "全部资格状态"], ["hide", "隐藏明确不符合"], ["eligible", "符合已知条件"], ["insufficient_information", "信息不足"], ["not_eligible", "明确不符合"], ["pending", "等待刷新匹配"]]).querySelector("select");
    jobView = select("jobView", "关注视图", [["target", "目标技术岗位 · 含待核验"], ["leads", "目标实习线索 · 含待核验"], ["attention", "严格符合全部已知条件"], ["all", "当前类别全部岗位"]], initialView).querySelector("select");
    controls.append(jobView.parentElement, scope.parentElement, sorting.parentElement, eligibility.parentElement);
    content.insertBefore(node("p", "默认展示目标技术岗位：资格未知、明确不符合、招聘类型未知均保留真实标签，可逐条核验。实习线索排除已知硬性冲突；严格视图还要求本科在读条件明确、全部已知资格通过。任何视图都不保证现在仍在招聘或可以在 2027 年春季入职。", "muted"), advanced);
    content.insertBefore(controls, advanced);
    for (const control of [scope, sorting, eligibility, jobView]) control.onchange = () => { load(0).catch(e => msg(e.message, true)); };
    const categories = node("div", "", "guidance");
    categories.append(node("p", "真实岗位分类：本土企业大陆 " + summary.domestic.jobs + " · 在华外企 " + summary.foreign.jobs + " · 大陆企业待分类 " + summary.unclassified.jobs + "。另有 " + summary.secondaryMainlandListed + " 条主地点海外 / 未知、附加大陆记录待核验；" + summary.explicitNonMainland + " 条国家代码 CN 但地点明确港澳台的岗位，均保留于全部存档。", "muted"));
    categories.append(actionGroup(jobScopeLink("大陆企业待分类", "unclassified", "all"), jobScopeLink("全球全部存档（含海外 / 未知）", "all", "all")));
    content.insertBefore(categories, advanced);
    coverageNote = node("div", "", "job-coverage");
    content.insertBefore(coverageNote, advanced);
  }
  const clearFilters = async nextView => {
    f.reset();
    if (eligibility) eligibility.value = "";
    if (nextView) jobView.value = nextView;
    await load(0);
  };
  // 翻页、清除筛选后若用户已滚过结果顶部，回到结果开头并把焦点交给标题，否则会停在新一页的底部。
  const revealResults = panel => {
    if (!pastTop(out.getBoundingClientRect())) return;
    out.scrollIntoView({block: "start"});
    const heading = panel.querySelector("h2");
    if (heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}); }
  };
  let pending = 0;
  const load = async target => {
    pending++; out.classList.add("is-loading"); out.setAttribute("aria-busy", "true");
    try { await render(target); }
    finally { if (!--pending) { out.classList.remove("is-loading"); out.removeAttribute("aria-busy"); } }
  };
  const render = async (target = pager.page) => {
    const args = Object.fromEntries(new FormData(f));
    if (isJob) {
      args.domain = scope.value; args.sort = sorting.value; args.view = jobView.value;
      if (eligibility.value === "hide") args.hideIneligible = "true";
      else if (eligibility.value) args.hard_status = eligibility.value;
    } else {
      args.kind = section === "technology" ? "release" : "opportunity";
      args.sort = "updated_desc";
    }
    args.page = target;
    const loaded = await pager.load(target, () => Promise.all([
      api("/items?" + query(args)),
      isJob ? api("/job-coverage?" + new URLSearchParams({domain: args.domain})) : Promise.resolve(null),
    ]));
    if (!loaded) return; // 已被更新的请求取代
    const [r, coverage] = loaded, page = pager.page;
    out.replaceChildren();
    const name = isJob ? scopeNames[scope.value] : section === "technology" ? "技术情报" : "海外机会";
    if (isJob) {
      const url = new URL(location.href);
      url.searchParams.set("scope", scope.value); url.searchParams.set("view", jobView.value);
      history.replaceState(null, "", url);
      document.querySelector("#intro").textContent = scope.value === "all" ? "全球岗位存档，包括海外、地点未知和企业待分类记录；与中国求职推荐分开。" : scope.value === "unclassified" ? "工作地点明确为中国大陆，企业归属尚未核验；不计作本土企业或在华外企。" : name + "；按企业归属与主工作地点分类，资格和在招状态分别核验。";
      coverageNote.replaceChildren(node("p", "当前类别真实覆盖：" + coverage.jobs + " 条岗位 · " + coverage.sourceCount + " 个实际贡献来源 · " + coverage.employerCount + " 个雇主。目标技术方向 " + coverage.target + " 条；实习线索 " + coverage.leads + " 条（含严格符合）；严格符合 " + coverage.attention + " 条；等待刷新匹配 " + coverage.pending + " 条。", "muted"));
      coverageNote.append(node("p", "覆盖数排除演示数据，不受搜索、招聘类型和资格筛选影响；来源数仅计已贡献本类别存档岗位的来源，不代表已配置来源总数或当前在招数量。", "muted"));
      if (coverage.sources.length) {
        const sources = node("details"), list = node("ul");
        sources.append(node("summary", "查看真实来源覆盖"));
        coverage.sources.forEach(source => list.append(node("li", source.name + " · " + source.jobs + " 条存档岗位")));
        sources.append(list); coverageNote.append(sources);
      }
    }
    const panel = card(name, "共 " + r.total + " 条信息" + (demo.checked ? "（含明确标记的演示数据）" : "（真实数据）") + " · 第 " + (page + 1) + " 页 · " + (sorting ? sorting.selectedOptions[0].textContent : "最近更新（本地内容）"));
    if (!r.total) {
      if (!isJob) {
        panel.append(emptyState("没有符合当前筛选的信息", "可清除筛选，查看此栏目的全部存档。"), actionGroup(button("清除筛选", () => clearFilters())));
      } else {
        let title, description;
        if (!coverage.jobs) {
          title = {domestic: "当前尚无已核验中国本土企业岗位", foreign: "当前尚无已核验在华外企岗位", unclassified: "当前尚无企业待分类的大陆岗位", mainland: "当前尚无已核验大陆工作地点的真实岗位", all: "当前尚无真实岗位存档"}[scope.value];
          description = "当前类别真实岗位 0 条，实际贡献来源 " + coverage.sourceCount + " 个。" + ({domestic: "尚未形成“已核验本土企业 + 大陆主工作地点”的岗位记录。", foreign: "尚未形成“已核验境外企业 + 大陆主工作地点”的岗位记录。", unclassified: "主工作地点为大陆且企业归属未核验的记录目前为空。", mainland: "已有海外或地点未知记录不作为大陆岗位补充。", all: "需要先导入合法获得的具体岗位原文并保留官方链接。"}[scope.value]) + "这属于来源覆盖缺口，不表示你不符合岗位条件。";
        } else if (!coverage[jobView.value]) {
          title = jobView.value === "attention" ? "本类别有真实岗位，但严格符合结果为 0" : jobView.value === "leads" ? "本类别有真实岗位，但暂无可确认的目标实习线索" : "本类别有真实岗位，但暂无已计算的目标技术方向结果";
          description = "本类别保存了 " + coverage.jobs + " 条真实岗位。当前视图受技术方向、实习类型、来源核验或个人资格条件限制；资料未知和明确冲突不会被视为符合。等待刷新匹配 " + coverage.pending + " 条。可查看本类别全部岗位及每条的资格说明。";
        } else {
          title = "当前筛选没有结果；本类别和视图仍有岗位";
          description = "当前类别有 " + coverage.jobs + " 条真实岗位，该视图原有 " + coverage[jobView.value] + " 条。搜索、城市、招聘类型或资格筛选将结果缩小为 0；清除筛选即可恢复当前视图。";
        }
        const empty = emptyState(title, description), shortcuts = actionGroup();
        empty.dataset.emptyReason = !coverage.jobs ? "coverage" : !coverage[jobView.value] ? "view" : "filters";
        if (coverage[jobView.value]) shortcuts.append(button("清除筛选", () => clearFilters()));
        if (coverage.leads && jobView.value !== "leads") shortcuts.append(button("查看待核验实习线索（" + coverage.leads + "）", () => clearFilters("leads")));
        if (coverage.jobs) shortcuts.append(button("查看当前类别全部岗位（" + coverage.jobs + "）", () => clearFilters("all")));
        else shortcuts.append(jobScopeLink("查看大陆全部企业岗位", "mainland", "all"), Object.assign(node("a", "导入官方具体 JD"), {href: "/view/import"}), Object.assign(node("a", "查看来源与采集状态"), {href: "/view/monitor"}));
        panel.append(empty, shortcuts);
      }
    } else if (section === "technology") {
      const first = r.items[0], lead = itemCard(first, false, page * 20 + 1);
      lead.classList.add("technology-lead"); panel.append(lead);
      const grid = node("div", "", "technology-grid");
      r.items.slice(1).forEach((item, index) => grid.append(itemCard(item, false, page * 20 + index + 2)));
      panel.append(grid);
    } else r.items.forEach((item, index) => panel.append(itemCard(item, false, page * 20 + index + 1)));
    const actions = actionGroup();
    if (r.total) actions.append(button("清除筛选", () => clearFilters(), "btn-secondary"));
    if (page > 0) actions.append(button("上一页", () => load(page - 1), "btn-secondary"));
    if ((page + 1) * 20 < r.total) actions.append(button("下一页", () => load(page + 1), "btn-secondary"));
    panel.append(actions); out.append(panel); revealResults(panel);
  };
  f.onsubmit = async e => {
    e.preventDefault();
    try { await load(0); } catch (e) { msg(e.message, true); }
  };
  await load();
}
async function skills() {
  const profile = await api("/profile");
  content.replaceChildren();
  const f = filterForm(),
    out = node("div"),
    filters = node("details", "", "advanced-filters");
  append(filters, node("summary", "样本范围与筛选"), f);
  append(content, filters, out);
  const load = async () => {
    const r = await api(
      "/skills?" + query(Object.fromEntries(new FormData(f))),
    );
    out.replaceChildren();
    const chart = card(
      "技能需求样本",
      "墨绿：已确认 · 琥珀：学习中 · 朱红：档案尚未确认",
    );
    const legend=chart.querySelector(".section-heading p");
    legend.replaceChildren(tag("已确认", "success"), node("span", " "), tag("学习中", "warning"), node("span", " "), tag("档案尚未确认", "danger"));
    const sample = node("div", "", "guidance");
    append(
      sample,
      append(
        node("p"),
        node("span", "样本量 " + r.sampleSize + " 个唯一岗位 · 统计时间 "),
        timeNode(r.generatedAt),
      ),
      node("p", r.timeBasis, "muted"),
      node("p", r.limitation, "muted"),
    );
    chart.append(sample);
    const normalized = (s) => s.toLowerCase().replace(/[-\s]/g, "");
    const known = (profile.skills || []).map(normalized),
      learning = (profile.learningSkills || []).map(normalized),
      counts = new Map();
    r.skills.forEach((s) =>
      counts.set(s.skill, (counts.get(s.skill) || 0) + Number(s.jobs)),
    );
    const plot = node("div", "", "skill-chart");
    [...counts]
      .sort((a, b) => b[1] - a[1])
      .forEach(([name, count], n) => {
        const tone = known.includes(normalized(name))
          ? "success"
          : learning.includes(normalized(name))
            ? "warning"
            : "danger";
        const row = node("div", "", "skill-chart-row");
        const track = node("div", "", "skill-bar-track"),
          bar = node("div", "", "skill-bar skill-bar-" + tone);
        bar.style.width =
          (r.sampleSize ? Math.min(100, (count / r.sampleSize) * 100) : 0) +
          "%";
        track.append(bar);
        append(
          row,
          node("span", String(n + 1).padStart(2, "0"), "entry-ordinal"),
          node("span", name, "skill-name"),
          track,
          node("strong", count, "skill-count tone-" + tone),
          node(
            "span",
            r.sampleSize
              ? ((100 * count) / r.sampleSize).toFixed(1) + "%"
              : "—",
            "muted",
          ),
        );
        plot.append(row);
      });
    if (!counts.size)
      plot.append(
        emptyState("还没有技能样本", "导入岗位后可查看技能需求与档案差距。"),
      );
    chart.append(plot);
    out.append(chart);
    const provenance = card(
      "来源与要求性质",
      "必备和加分分别保留，每个岗位技能只统计一次",
    );
    provenance.append(
      node(
        "p",
        "来源：" +
          r.sources
            .map((s) => s.name + "（" + statusText(s.status) + "）")
            .join("、"),
        "entry-source",
      ),
      table(
        ["技能", "要求性质", "岗位数", "样本占比"],
        r.skills.map((s) => [
          s.skill,
          tag(
            labels[s.requirement],
            s.requirement === "required" ? "info" : "neutral",
          ),
          s.jobs,
          r.sampleSize ? ((100 * s.jobs) / r.sampleSize).toFixed(1) + "%" : "—",
        ]),
      ),
    );
    out.append(provenance);
  };
  f.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await load();
    } catch (e) {
      msg(e.message, true);
    }
  };
  await load();
}
async function settings() {
  const p = await api("/profile");
  content.replaceChildren();
  const c = card("个人求职档案"),
    f = node("form"),
    grid = node("div", "", "grid");
  for (const [k, l] of [
    ["skills", "已确认掌握技能"],
    ["learningSkills", "正在学习的技能"],
    ["cities", "目标城市"],
    ["roles", "岗位方向代码：data_engineering / java_backend / python / ai / data_analysis / software"],
    ["employmentTypes", "目标招聘类型代码：internship / campus / full_time（留空不限）"],
    ["companyTypes", "企业类型代码：foreign / private / central_state 等"],
    ["excludedTerms", "排除条件"],
    ["internshipTypes", "接受的实习类型：日常 / 暑期 / 寒假 / 长期 / 可转正"],
  ])
    grid.append(field(k, l + "（逗号分隔）", "text", (p[k] || []).join(", ")));
  append(
    grid,
    select(
      "education",
      "当前学历",
      [
        ["", "尚未填写"],
        ["associate", "大专"],
        ["bachelor", "本科"],
        ["master", "硕士"],
        ["doctor", "博士"],
      ],
      p.education,
    ),
    field("graduationYear", "预计毕业年份", "number", p.graduationYear),
    field("major", "专业", "text", p.major),
    select("currentlyStudying", "当前是否在读", [["", "尚未确认"], ["true", "在读"], ["false", "已不在读"]], p.currentlyStudying == null ? "" : String(p.currentlyStudying)),
    select("hasInternshipExperience", "是否有相关实习经历", [["", "尚未确认"], ["true", "有"], ["false", "无"]], p.hasInternshipExperience == null ? "" : String(p.hasInternshipExperience)),
    field("workExperienceYears", "累计工作经验（年，未知留空；相关领域口径需另核验）", "number", p.workExperienceYears),
    field("availableDays", "每周最多到岗天数", "number", p.availableDays),
    field("availableMonths", "可持续月数", "number", p.availableMonths),
    field("internshipStartFrom", "期望实习开始窗口 · 从（具体日期可编辑）", "date", p.internshipStartFrom),
    field("internshipStartTo", "期望实习开始窗口 · 至", "date", p.internshipStartTo),
    select(
      "hardCity",
      "城市是否为硬性限制",
      [
        ["false", "偏好"],
        ["true", "硬性限制"],
      ],
      String(p.hardCity),
    ),
    field("minimumSalary", "最低薪资", "number", p.minimumSalary),
    select(
      "salaryPeriod",
      "薪资周期",
      [
        ["", "未知"],
        ["day", "日"],
        ["month", "月"],
        ["year", "年"],
        ["hour", "小时"],
      ],
      p.salaryPeriod,
    ),
    field("salaryCurrency", "薪资币种，例如 CNY", "text", p.salaryCurrency),
  );
  for (const k of ["role", "skills", "city", "company", "qualifications"])
    grid.append(
      field("weight_" + k, "匹配权重 · " + ({role:"岗位方向",skills:"技能",city:"城市",company:"企业",qualifications:"招聘资格"}[k]), "number", p.weights?.[k] ?? ({role:35,skills:40,city:10,company:0,qualifications:15}[k])),
    );
  append(
    f,
    grid,
    button(
      "保存档案",
      async () => {
        const data = Object.fromEntries(new FormData(f));
        for (const k of [
          "skills",
          "learningSkills",
          "cities",
          "roles",
          "companyTypes",
          "excludedTerms",
          "internshipTypes",
          "employmentTypes",
        ])
          data[k] = data[k]
            .split(/[,，]/)
            .map((s) => s.trim())
            .filter(Boolean);
        data.hardCity = data.hardCity === "true";
        for (const k of ["currentlyStudying", "hasInternshipExperience"])
          data[k] = data[k] === "" ? null : data[k] === "true";
        data.weights = {};
        for (const k of ["role", "skills", "city", "company", "qualifications"]) {
          data.weights[k] = Number(data["weight_" + k]);
          delete data["weight_" + k];
        }
        for (const k of [
          "graduationYear",
          "availableDays",
          "availableMonths",
          "minimumSalary",
          "workExperienceYears",
        ])
          data[k] = data[k] ? Number(data[k]) : null;
        for (const k of [
          "education",
          "salaryPeriod",
          "salaryCurrency",
          "major",
          "internshipStartFrom",
          "internshipStartTo",
        ])
          if (!data[k]) data[k] = null;
        await api("/profile", "PUT", data);
        try {
          await api("/matches/refresh", "POST", {});
          msg("档案已保存，岗位匹配已更新。");
        } catch (e) {
          msg("档案已保存；匹配暂未刷新，旧评分已停止展示，可在总览重试。", true);
        }
        await settings();
      },
      true,
    ),
  );
  decorateProfileForm(f, p);
  f.elements.workExperienceYears.step = "any";
  f.elements.workExperienceYears.min = "0";
  f.elements.workExperienceYears.max = "60";
  c.append(
    node(
      "p",
      "初始档案为空。这里的编辑只保存到本地；未填写技能表示尚未确认掌握。",
      "muted",
    ),
    f,
  );
  content.append(c);
  const ai = card("可选 AI 增强");
  append(
    ai,
    node(
      "p",
      "默认关闭；真实模型只可在 .env 中显式授权、配置密钥、真实价格与预算。MOCK 明确标记为规则演示。",
    ),
    pre(await api("/ai")),
  );
  content.append(ai);
}
async function imports() {
  content.replaceChildren();
  const sources = (await api("/monitor")).sources.filter(x => x.adapter === "manual");
  const sourceOptions = sources.map(x => [String(x.id), x.name + " · #" + x.id]);
  const c = card("粘贴信息 · 保留来源"),
    f = node("form"),
    grid = node("div", "", "grid");
  append(
    grid,
    select("kind", "信息类型", [
      ["job", "岗位"],
      ["opportunity", "海外机会"],
      ["release", "技术更新"],
    ]),
    field("external_id", "官网职位编号 / 稳定标识（可选；同一岗位更新时沿用）"),
    field("title", "标题"),
    field("company", "企业 / 机构"),
    field("url", "官方链接（只保存，不自动抓取）"),
    select("company_type", "企业类型", [
      ["unknown", "未知"],
      ...Object.entries(labels).filter(([k]) =>
        [
          "foreign",
          "private",
          "central_state",
          "local_state",
          "joint_venture",
          "finance",
          "public_institution",
          "research",
          "other",
        ].includes(k),
      ),
    ]),
    field("country", "国家代码，例如 CN"),
    field("city", "城市"),
    field("graduation_year", "明确的招聘届别；未知留空", "number"),
    field("deadline", "官方截止日期；未知留空", "date"),
    select("employment_type", "招聘类型（只按官方明确标识）", [["", "未知 / 从JD解析"],["internship","实习"],["campus","校招正式岗"],["full_time","社招全职"]]),
    field("internship_type", "实习类别：日常 / 长期 / 暑期，未知留空"),
    field("start_date", "官方明确到岗日期；未知留空", "date"),
    field("end_date", "官方明确结束日期；未知留空", "date"),
    select("status", "逐岗招聘状态（未知不猜）", [["", "未知 / 历史存档"], ["pending_review", "等待人工核验"], ["open", "本人已核验官方仍在列（需时间和说明）"], ["closed", "官方明确关闭（需时间和说明）"]]),
    field("source_verified_at", "最近人工核验时间（如2026-10-15T10:00:00+08:00；未核验留空）"),
    field("source_verification_note", "核验说明：官网职位编号、当前在列/关闭证据、JD/地点/资格、文件许可依据"),
    field("total_cost", "海外项目费用；未知留空"),
    field("funding", "资助原文；未知留空"),
    field("language", "语言要求"),
    field("eligibility", "项目资格"),
  );
  append(
    f,
    grid,
    field("body", "招聘 JD / 公告 / Release Notes 原文", "textarea"),
    select("sourceId", "保存到手动来源", sourceOptions, "1"),
    field("is_demo", "这是合成演示信息（默认不计入真实统计）", "checkbox"),
    button(
      "提交解析任务",
      async () => {
        const data = Object.fromEntries(new FormData(f)),
          sourceId = Number(data.sourceId);
        delete data.sourceId;
        for (const k of Object.keys(data)) if (data[k] === "") delete data[k];
        if (data.graduation_year)
          data.graduation_year = Number(data.graduation_year);
        data.is_demo = f.elements.is_demo.checked;
        if (!data.title?.trim()) throw Error("请填写官方职位标题；未知信息请留空，不推测岗位内容。");
        if (data.kind === "job" && !data.body?.trim()) throw Error("请粘贴合法取得的 JD 正文；官方链接只保存，不自动抓取或绕过访问限制。");
        if (!data.external_id) {
          const identity = data.url || [data.title, data.company || "", data.body].join("\n");
          const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(data.kind + "\n" + identity));
          data.external_id = "manual-" + Array.from(new Uint8Array(hash), x => x.toString(16).padStart(2, "0")).join("");
        }
        const r = await api("/imports", "POST", { sourceId, records: [data] });
        msg(
          "任务 #" +
            r.taskId +
            " 已排队。Python worker 解析后可在信息列表查看；任务页可查看失败原因。",
        );
        await taskFeedback(r.taskId);
      },
      true,
    ),
  );
  f.prepend(node("span", "01 · 单条信息", "entry-source"));
  c.append(node("p","填写官方标题、企业、地点并粘贴完整JD；技能、学历、届别和实习时长按明确原文解析，未知不补猜。稳定标识留空时按链接（无链接则按正文）生成；无链接的岗位更新请沿用原标识。官方链接仅保存，不抓取。复制官方完整JD后再标记人工核验；仅链接没有资格证据，不进入关注候选。授权文件使用CSV/JSON，保留未知值。企业归属需另有官方依据，导入选择民企不会自动变成已核验本土企业。", "muted"),
    Object.assign(node("a","国内官方来源入口与导入说明"),{href:"/job-sources.html"}),f);
  content.append(c);
  const upload = card("批量导入 CSV / JSON"),
    uf = node("form");
  append(
    uf,
    select("sourceId", "文件保存到手动来源", sourceOptions, "1"),
    field("file", "文件（最多 2MB / 1000 行）", "file"),
    button("上传并解析", async () => {
      const r = await api("/imports/file", "POST", new FormData(uf));
      msg("任务 #" + r.taskId + " 已排队。");
      await taskFeedback(r.taskId);
    }),
  );
  uf.prepend(node("span", "02 · 批量导入", "entry-source"));
  upload.append(
    node(
      "p",
      "每行至少包含 kind、external_id、title；完整格式见 docs/API.md。文件应来自你有权使用的来源。",
      "muted",
    ),
    uf,
  );
  content.append(upload);
}
async function subscriptions() {
  content.replaceChildren();
  const c = card("创建与编辑订阅", "启用后追踪匹配信息；不新增已明确过期或关闭的岗位、机会提醒，历史保留。截止当天与有效性未知的信息仍可提醒，演示须主动勾选。"),
    f = node("form");
  let editing = null;
  const ruleFields = ["kind", "country", "city", "company_type", "category", "employment_type", "q", "minimumScore"];
  const save = button(
    "创建订阅",
    async () => {
      const rules = JSON.parse(f.elements.rules.value.trim() || "{}");
      for (const key of ruleFields) {
        const value = f.elements["rule_" + key].value.trim();
        if (value) rules[key] = key === "minimumScore" ? Number(value) : value;
      }
      rules.includeDemo = f.elements.rule_includeDemo.checked;
      const data = {
        name: f.elements.name.value,
        rules,
        enabled: editing ? editing.enabled : true,
      };
      if (editing) await api("/subscriptions/" + editing.id, "PUT", data);
      else await api("/subscriptions", "POST", data);
      await api("/matches/refresh", "POST", {});
      msg("订阅已保存并完成匹配。");
      await subscriptions();
    },
    true,
  );
  append(
    f,
    field("name", "订阅名称"),
    append(node("div", "", "grid"),
      select("rule_kind", "信息类型", [["", "全部"], ["job", "岗位"], ["opportunity", "海外机会"], ["release", "技术更新"]], "job"),
      field("rule_country", "工作国家代码（例如 CN，未知留空）", "text", "CN"),
      field("rule_city", "工作城市（可留空）"),
      select("rule_company_type", "企业类型（按核验资料）", [["", "全部"], ...Object.entries(labels).filter(([key]) => ["foreign", "private", "joint_venture", "central_state", "local_state", "finance", "public_institution", "research", "other", "unknown"].includes(key))]),
      select("rule_category", "岗位方向", [["", "全部"], ["data_engineering", "数据开发"], ["java_backend", "Java 后端"], ["ai", "AI 应用"], ["data_analysis", "数据分析"]]),
      select("rule_employment_type", "招聘类型", [["", "全部"], ["internship", "实习"], ["campus", "校招"], ["full_time", "全职"]]),
      field("rule_q", "标题、正文或企业关键词（可留空）"),
      field("rule_minimumScore", "最低匹配分（可留空）", "number")),
    field("rule_includeDemo", "包含合成演示信息", "checkbox"),
    disclosure("高级订阅条件（可选）", field("rules", "补充 JSON 条件（例如省份、远程要求）；同名条件以上方为准", "textarea", "{}")),
    actionGroup(save),
  );
  f.prepend(node("span", "01 · 编辑订阅规则", "entry-source"));
  c.append(f);
  content.append(c);
  const rows = await api("/subscriptions"),
    list = card("我的订阅", "墨绿表示启用，灰色表示暂停；开关只更新本地规则");
  if (!rows.length)
    list.append(
      emptyState("还没有订阅", "创建一条订阅，开始追踪与你相关的信息。"),
    );
  rows.forEach((sub, n) => {
    const row = node(
      "article",
      "",
      "subscription-row " +
        (sub.enabled ? "subscription-enabled" : "subscription-paused"),
    );
    const body = node("div");
    append(
      body,
      node(
        "span",
        (sub.rules.kind || "全部类型").toUpperCase(),
        "entry-source",
      ),
      node("h3", sub.name),
      node(
        "p",
        Object.entries(sub.rules)
          .map(([k, v]) => k + "：" + v)
          .join(" · "),
        "muted",
      ),
    );
    const control = node("label", "", "switch-control"),
      input = node("input"),
      track = node("span", "", "switch-track");
    input.type = "checkbox";
    input.setAttribute("role", "switch");
    input.checked = sub.enabled;
    input.setAttribute("aria-label", sub.name + " 启用状态");
    input.onchange = async () => {
      const value = input.checked;
      input.disabled = true;
      try {
        await api("/subscriptions/" + sub.id, "PUT", {
          name: sub.name,
          rules: sub.rules,
          enabled: value,
        });
        await subscriptions();
      } catch (e) {
        input.checked = !value;
        msg(e.message, true);
      } finally {
        input.disabled = false;
      }
    };
    append(
      control,
      node("span", sub.enabled ? "已启用" : "已暂停"),
      input,
      track,
    );
    const actions = actionGroup(
      control,
      button(
        "编辑",
        () => {
          editing = sub;
          f.elements.name.value = sub.name;
          for (const key of ruleFields) f.elements["rule_" + key].value = sub.rules[key] ?? "";
          f.elements.rule_includeDemo.checked = sub.rules.includeDemo === true;
          f.elements.rules.value = JSON.stringify(Object.fromEntries(Object.entries(sub.rules).filter(([key]) => !ruleFields.includes(key) && key !== "includeDemo")), null, 2);
          save.textContent = "保存修改";
          f.scrollIntoView({ block: "start" });
        },
        "btn-text",
      ),
    );
    append(
      row,
      node("span", String(n + 1).padStart(2, "0"), "entry-ordinal"),
      body,
      actions,
    );
    list.append(row);
  });
  content.append(list);
}
function applicationForm(id, existing = {}, onSaved) {
  const f = node("form");
  append(
    f,
    select(
      "status",
      "投递状态",
      Object.entries(labels).filter(([k]) =>
        [
          "interested",
          "saved",
          "preparing",
          "applied",
          "assessment",
          "interview1",
          "interview_next",
          "offer",
          "rejected",
          "closed",
        ].includes(k),
      ),
      existing.status || "interested",
    ),
    field("nextAction", "下一步行动（仅本地，不自动提醒）", "text", existing.next_action),
    field("notes", "个人备注（仅本地）", "textarea", existing.notes),
  );
  for (const [k, l, db] of [
    ["appliedAt", "投递时间", "applied_at"],
    ["assessmentAt", "已确认笔试时间", "assessment_at"],
    ["interviewAt", "已确认面试时间", "interview_at"],
  ]) {
    const d = existing[db] ? new Date(existing[db]) : null;
    const value = d
      ? new Date(d.getTime() - d.getTimezoneOffset() * 60000)
          .toISOString()
          .slice(0, 16)
      : "";
    f.append(field(k, l, "datetime-local", value));
  }
  f.append(
    button(
      "保存投递记录",
      async () => {
        const data = Object.fromEntries(new FormData(f));
        for (const k of ["appliedAt", "assessmentAt", "interviewAt"])
          data[k] = data[k] ? new Date(data[k]).toISOString() : null;
        await api("/applications/" + id, "PUT", data);
        msg("投递记录、下一步行动和历史已保存。");
        if (onSaved) {
          try {await onSaved();}
          catch (e) {msg("记录已保存，列表暂时刷新失败；编辑内容保留，可刷新页面重试。", true);}
        }
      },
      true,
    ),
  );
  return f;
}
// 投递历史：把相邻两次保存的快照比较成“改了什么”，而不是把原始 JSON 展示给用户。
const HISTORY_FIELDS = [
  ["status", "状态"],
  ["nextAction", "下一步"],
  ["appliedAt", "投递时间"],
  ["assessmentAt", "笔试时间"],
  ["interviewAt", "面试时间"],
  ["notes", "备注"],
];
const HISTORY_TIME_FIELDS = new Set(["appliedAt", "assessmentAt", "interviewAt"]);
// 历史里的时间必须能区分年份和秒数，所以复用 fullTime，而不是只到分钟、没有年份的 formatTime。
function historyTime(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? fullTime.format(date) : "—";
}
function historyChanges(previous, current, show) {
  const blank = (v) => v == null || v === "";
  return HISTORY_FIELDS.flatMap(([key, label]) => {
    const before = previous ? previous[key] : null, after = current[key];
    const same = HISTORY_TIME_FIELDS.has(key) && !blank(before) && !blank(after)
      ? Date.parse(before) === Date.parse(after) // 同一时刻的不同写法不算变化
      : (blank(before) && blank(after)) || before === after;
    if (same) return [];
    return [{key, label, before: blank(before) ? "" : show(key, before), after: blank(after) ? "" : show(key, after)}];
  });
}
function historyEntries(rows, show) {
  const sorted = [...rows].sort((a, b) => b.id - a.id);
  return sorted.map((row, i) => {
    const previous = sorted[i + 1] ? sorted[i + 1].snapshot || {} : null;
    return {id: row.id, createdAt: row.created_at, first: !previous, changes: historyChanges(previous, row.snapshot || {}, show)};
  });
}
function applicationHistoryView(rows) {
  if (!rows.length)
    return emptyState("还没有保存过进度", "在“编辑进度与下一步”里保存一次，这里会按时间列出每次变化。", true);
  const show = (key, v) => key === "status" ? labels[v] || v : HISTORY_TIME_FIELDS.has(key) ? historyTime(v) : String(v);
  const list = node("ol", "", "history-timeline");
  list.setAttribute("aria-label", "投递历史，最新在前");
  historyEntries(rows, show).forEach((e) => {
    const li = node("li", "", "history-entry"), time = node("time", historyTime(e.createdAt), "history-time");
    time.dateTime = e.createdAt;
    li.append(time, node("strong", e.first ? "创建记录" : e.changes.length ? "更新记录" : "已保存，内容没有变化", "history-title"));
    if (e.changes.length) {
      const changes = node("ul", "", "history-changes");
      e.changes.forEach((c) => changes.append(node("li", c.label + "：" +
        (e.first ? c.after : (c.before || "未填写") + " → " + (c.after || "已清空")))));
      li.append(changes);
    }
    list.append(li);
  });
  return append(node("div", "", "history-panel"), node("p", "共 " + rows.length + " 次保存，最新在前", "muted"), list);
}
async function applications() {
  content.replaceChildren();
  let rows = await api("/applications");
  const panel = card("收藏与投递", "搜索已保存的岗位，核对原文与资格，再安排下一步；所有记录仅保存在本地"),
    filters = node("form", "", "toolbar"), board = node("div", "", "application-board"),
    params = new URLSearchParams(location.search),
    search = field("q", "搜索标题 / 企业 / 城市 / 备注 / 下一步", "search", params.get("q") || ""),
    status = select("status", "记录状态", [["", "全部状态"], ...["interested", "saved", "preparing", "applied", "assessment", "interview1", "interview_next", "offer", "rejected", "closed"].map(k => [k, labels[k]])], params.get("status") || ""),
    count = node("p", "", "muted");
  const draw = () => {
    const q = search.querySelector("input").value.trim().toLocaleLowerCase(), selectedStatus = status.querySelector("select").value;
    const visible = rows.filter(r => (demo.checked || !r.is_demo) && (!selectedStatus || r.status === selectedStatus) &&
      (!q || [r.title, r.company, r.city, r.notes, r.next_action].some(v => String(v || "").toLocaleLowerCase().includes(q))));
    const query = new URLSearchParams();
    if (q) query.set("q", search.querySelector("input").value.trim());
    if (selectedStatus) query.set("status", selectedStatus);
    history.replaceState(null, "", location.pathname + (query.size ? "?" + query : ""));
    count.textContent = "当前 " + visible.length + " 条记录；收藏在“关注与投递”栏，可按“已收藏”筛选。";
    board.replaceChildren();
    if (!visible.length) {
      board.append(emptyState(rows.length ? "没有符合筛选的记录" : "还没有收藏或投递记录", rows.length ? "清空搜索或切换状态；合成记录遵循顶部演示开关。" : "在岗位详情中选择“已收藏”并保存，再回到这里。"));
      return;
    }
    const stages = [
      ["关注与投递", "info", ["interested", "saved", "preparing", "applied", "assessment"]],
      ["面试中", "warning", ["interview1", "interview_next"]],
      ["Offer", "success", ["offer"]], ["已结束", "neutral", ["rejected", "closed"]],
    ];
    for (const [title, tone, statuses] of stages) {
      const col = node("section", "", "application-column stage-" + tone), selected = visible.filter(r => statuses.includes(r.status));
      col.append(append(node("div", "", "stage-heading"), node("h3", title), node("strong", selected.length, "stage-count")));
      selected.forEach(row => {
        const entry = node("article", "", "application-entry"), edit = node("details");
        entry.dataset.itemId = row.item_id;
        entry.append(append(node("h3"), Object.assign(node("a", row.title), {href: "/view/detail?id=" + row.item_id})),
          tag(labels[row.status], tone), node("p", [row.company || "企业未知", row.city || "城市未知"].join(" · "), "muted"));
        if (row.is_demo) entry.append(tag("合成演示信息", "warning"));
        entry.append(node("p", "下一步：" + (row.next_action || "尚未记录")));
        if (row.notes) entry.append(node("p", row.notes));
        entry.append(node("p", "截止：" + formatDate(row.deadline) + " · 最近保存：" + formatDate(row.updated_at), "muted"));
        entry.append(Object.assign(node("a", "核对官方来源、核验日期与资格 →"), {href: "/view/detail?id=" + row.item_id}));
        edit.append(node("summary", "编辑进度与下一步"), applicationForm(row.item_id, row, async () => {rows = await api("/applications"); draw();}));
        let historyPanel;
        entry.append(edit, button("投递历史", async () => {
          const value = await api("/applications/" + row.item_id + "/history");
          if (!historyPanel) {historyPanel = node("div"); entry.append(historyPanel);}
          historyPanel.replaceChildren(applicationHistoryView(value));
        }, "btn-text"));
        col.append(entry);
      });
      board.append(col);
    }
  };
  filters.append(search, status, button("筛选记录", draw));
  filters.addEventListener("submit", e => {e.preventDefault(); draw();});
  status.querySelector("select").addEventListener("change", draw);
  panel.append(filters, count, board); content.append(panel); draw();
}

function disclosure(title, child, className = "") {
  const details = node("details", "", "card disclosure-card " + className);
  append(details, node("summary", title), child);
  return details;
}
function sectionHeader(title, subtitle, action) {
  const header = node("div", "", "card-header"),
    heading = node("div", "", "section-heading");
  append(heading, node("h2", title), node("p", subtitle, "muted"));
  append(header, heading, action);
  return header;
}
function activityLogButton(article, value, id) {
  const b = node("button", "展开日志 →", "btn btn-text log-toggle"),
    log = node("div", "", "activity-log");
  b.type = "button";
  b.setAttribute("aria-expanded", "false");
  b.setAttribute("aria-controls", id);
  log.id = id;
  log.hidden = true;
  log.append(pre(value));
  b.onclick = () => {
    const open = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", String(open));
    log.hidden = !open;
    b.textContent = open ? "收起日志 ↑" : "展开日志 →";
  };
  append(article, b, log);
}
async function monitor() {
  const r = await api("/monitor");
  content.replaceChildren();
  const demoIds = new Set(
    r.sources.filter((s) => s.status === "test_data").map((s) => s.id),
  );
  const sources = demo.checked
    ? r.sources
    : r.sources.filter((s) => !demoIds.has(s.id));
  const runs = demo.checked
    ? r.runs
    : r.runs.filter((x) => !demoIds.has(x.source_id));
  const tasks = demo.checked
    ? r.tasks
    : r.tasks.filter((x) => !demoIds.has(x.source_id));
  const sourceMap = new Map(r.sources.map((s) => [s.id, s]));
  const metrics = node("div", "", "metrics");
  for (const [label, value, tone] of [
    ["数据源", sources.length, "metric-info"],
    [
      "已验证",
      sources.filter((s) => s.status === "verified").length,
      "metric-success",
    ],
    [
      "待处理任务",
      tasks.filter((t) => ["pending", "running"].includes(t.state)).length,
      "metric-warning",
    ],
    [
      "最近失败",
      runs.filter((x) => ["failed", "partial", "interrupted"].includes(x.state))
        .length,
      "metric-danger",
    ],
  ]) {
    metrics.append(
      append(
        node("div", "", "metric " + tone),
        node("span", label, "muted"),
        node("strong", value),
      ),
    );
  }
  content.append(metrics);
  const sourceSection = card(),
    refresh = button("刷新状态", monitor, "btn-text btn-sm");
  refresh.prepend(icon("refresh-cw"));
  sourceSection.append(
    sectionHeader("数据源", "公开信息的接入方式与最近验证状态", refresh),
  );
  sourceSection.append(
    table(
      ["№", "名称", "验证状态", "最近成功", "操作"],
      sources.map((s) => {
        const name = node("div"),
          label = node("span", s.name, "source-name");
        label.title = s.name;
        append(name, label, node("span", s.adapter, "adapter-tag cell-sub"));
        if (!s.enabled) name.append(node("span", "已停用", "cell-sub"));
        const actions = node("div", "", "cell-actions");
        if (s.adapter !== "manual") {
          const collect = button(
            "采集",
            async () => {
              const task = await api(
                "/sources/" + s.id + "/collect",
                "POST",
                {},
              );
              msg("采集任务 #" + task.taskId + " 已排队。");
              await taskFeedback(task.taskId);
            },
            "btn-secondary btn-sm",
          );
          collect.prepend(icon("play"));
          collect.disabled = !s.enabled;
          if (!s.enabled) collect.title = "请先启用数据源";
          actions.append(collect);
        }
        actions.append(
          button(
            s.enabled ? "禁用" : "启用",
            async () => {
              await api(
                "/sources/" + s.id + "/enabled?enabled=" + !s.enabled,
                "PUT",
                {},
              );
              await monitor();
            },
            "btn-text btn-sm " + (s.enabled ? "danger-hover" : ""),
          ),
        );
        return [
          node("span", String(s.id).padStart(2, "0"), "source-ordinal"),
          name,
          badge(s.status),
          timeNode(s.last_success),
          actions,
        ];
      }),
      {
        className: "source-table",
        emptyTitle: "暂无数据源",
        emptyText: "添加公开 API、RSS 或手动导入来源开始使用。",
      },
    ),
  );
  content.append(sourceSection);
  const recent = card();
  recent.append(sectionHeader("最近任务", "各来源最近一次活动，按时间倒序"));
  const feed = node("div", "", "task-feed");
  // 复用已有监控响应，不新增请求。队列与采集运行关联后只展示一次。
  const linkedRunIds = new Set(
    tasks.map((t) => t.result?.run_id).filter(Boolean),
  );
  const activities = [
    ...tasks.map((t) => ({
      sourceId: t.source_id,
      state: t.state,
      time: t.created_at,
      id: "task-" + t.id,
      log: {
        taskId: t.id,
        type: t.task_type,
        attempts: t.attempts,
        result: t.result,
        error: t.error,
      },
      kind: "task",
    })),
    ...runs
      .filter((x) => !linkedRunIds.has(x.id))
      .map((x) => ({
        sourceId: x.source_id,
        state: x.state,
        time: x.ended_at || x.started_at,
        id: "run-" + x.id,
        log: {
          runId: x.id,
          state: statusText(x.state),
          startedAt: x.started_at,
          endedAt: x.ended_at,
          collected: x.collected,
          parsed: x.parsed,
          failed: x.failed,
          inserted: x.inserted,
          updated: x.updated,
          deduplicated: x.deduplicated,
          seconds: x.duration_seconds,
          errors: parseArray(x.errors),
        },
        kind: "run",
      })),
  ].sort((a, b) => new Date(b.time) - new Date(a.time));
  const seen = new Set(),
    latest = [];
  for (const activity of activities) {
    if (!seen.has(activity.sourceId)) {
      seen.add(activity.sourceId);
      latest.push(activity);
    }
    if (latest.length === 3) break;
  }
  for (const activity of latest) {
    const source = sourceMap.get(activity.sourceId),
      article = node("article", "", "activity"),
      meta = node("div", "", "activity-meta");
    const state =
      activity.state === "success" || activity.state === "not_modified"
        ? "done"
        : activity.state;
    append(meta, badge(state), timeNode(activity.time));
    append(
      article,
      meta,
      node("h3", source?.name || "来源 #" + activity.sourceId),
      node("span", source?.adapter || "—", "adapter-tag"),
    );
    activityLogButton(article, activity.log, "activity-log-" + activity.id);
    feed.append(article);
  }
  if (!latest.length)
    feed.append(
      emptyState(
        "还没有任务记录",
        "提交一次采集或导入任务后，可以在这里展开日志。",
      ),
    );
  recent.append(feed);
  content.append(recent);
  const quality = node("div");
  quality.append(
    table(
      [
        "来源 / 运行 ID",
        "结果",
        "采集 / 成功 / 失败",
        "新增 / 更新 / 去重",
        "耗时",
      ],
      runs.map((x) => {
        const source = node("div");
        append(
          source,
          node("span", x.name, "source-name"),
          node("span", ({collect:"公开采集",import:"信息导入",archive_reparse:"存档重解析",legacy:"历史运行"}[x.mode] || "历史运行") + " · RUN " + x.id, "cell-sub"),
        );
        const errors = parseArray(x.errors);
        if (errors.length) {
          const d = node("details");
          append(
            d,
            node("summary", "查看 " + errors.length + " 项异常"),
            pre(errors),
          );
          source.append(d);
        }
        return [
          source,
          badge(x.state),
          node(
            "span",
            x.collected + " / " + x.parsed + " / " + x.failed,
            "number",
          ),
          node(
            "span",
            x.inserted + " / " + x.updated + " / " + x.deduplicated,
            "number",
          ),
          node("span", Number(x.duration_seconds).toFixed(2) + " s", "number"),
        ];
      }),
      {
        className: "run-table",
        emptyTitle: "暂无采集记录",
        emptyText: "启动 Python worker 后可查看采集质量和失败原因。",
      },
    ),
  );
  content.append(
    disclosure(
      "采集与数据质量 · 全部 " + runs.length + " 次运行",
      quality,
      "task-history",
    ),
  );
  const queue = node("div");
  queue.append(
    table(
      ["任务 ID", "类型", "状态", "尝试次数", "结果"],
      tasks.map((t) => {
        const result = node("div");
        if (t.error) result.append(node("span", t.error));
        else if (t.result) {
          result.append(node("span", statusText(t.result.state), "muted"));
          const d = node("details");
          append(d, node("summary", "展开任务结果"), pre(t.result));
          result.append(d);
        } else result.append(node("span", "等待执行结果", "weak"));
        return [
          node("span", "#" + t.id, "number"),
          node(
            "span",
            { import: "导入", collect: "采集", enrich: "AI 增强" }[
              t.task_type
            ] || t.task_type,
          ),
          badge(t.state),
          node("span", t.attempts, "number"),
          result,
        ];
      }),
      {
        className: "task-table",
        emptyTitle: "暂无队列任务",
        emptyText: "提交采集、导入或增强请求后会保留任务记录。",
      },
    ),
  );
  content.append(disclosure("任务队列记录 · " + tasks.length + " 条", queue));
  const f = node("form");
  append(
    f,
    field("name", "来源名称"),
    select("adapter", "接入方式", [
      ["manual", "仅手动导入"],
      ["github", "GitHub Releases"],
      ["greenhouse", "Greenhouse"],
      ["ashby", "Ashby 公开招聘"],
      ["smartrecruiters", "SmartRecruiters 公开招聘"],
      ["lever", "Lever 公开招聘"],
      ["rss", "RSS / Atom"],
    ]),
    field(
      "config",
      "JSON 配置（GitHub 使用 repo；招聘接口使用 board；SmartRecruiters/Lever 可加 country、intern_only、max_items；Lever 可加 commitment；RSS 使用 url）",
      "textarea",
      "{}",
    ),
    node(
      "p",
      '示例：GitHub {"repo":"pallets/flask"}。RSS 主机需加入采集器许可清单。',
      "muted",
    ),
    button(
      "保存来源",
      async () => {
        const result = await api("/sources", "POST", {
          name: f.elements.name.value,
          adapter: f.elements.adapter.value,
          config: JSON.parse(f.elements.config.value),
          enabled: false,
        });
        msg("来源 #" + result.id + " 已创建，默认停用。确认访问条款后可启用。");
        await monitor();
      },
      true,
    ),
  );
  content.append(disclosure("添加合法公开数据源", f));
  if (r.duplicateCandidates.length) {
    const details = node("div");
    append(
      details,
      node("p", "相似信息保留为候选，没有自动合并。", "muted"),
      table(
        ["信息 A", "信息 B", "依据 / 置信度"],
        r.duplicateCandidates.map((x) => [
          x.title_a,
          x.title_b,
          x.reason + " · " + x.confidence,
        ]),
      ),
    );
    content.append(
      disclosure(
        "疑似跨来源重复 · " + r.duplicateCandidates.length + " 组",
        details,
      ),
    );
  }
}

function definitionList(facts) {
  const list = node("dl", "", "facts");
  for (const [label, value] of facts) {
    const group = node("div", "", "fact");
    append(
      group,
      node("dt", label),
      append(
        node("dd"),
        value instanceof Node ? value : node("span", value ?? "—"),
      ),
    );
    list.append(group);
  }
  return list;
}
function salaryLabel(salary) {
  if (salary?.minimum == null)
    return salary?.raw?.includes("面议") ? "面议" : "—";
  const range =
    salary.minimum === salary.maximum
      ? String(salary.minimum)
      : salary.minimum + "–" + salary.maximum;
  return (
    range +
    " " +
    (salary.currency === "CNY" ? "元" : salary.currency || "币种待确认") +
    "/" +
    ({ day: "天", month: "月", year: "年", hour: "小时" }[salary.period] ||
      "周期待确认") +
    (salary.months ? " · " + salary.months + "薪" : "")
  );
}
function evidenceDisclosure(evidence) {
  if (!evidence) return node("small", "依据为保存的结构字段；可展开完整原文核验", "muted");
  const d=node("details");d.append(node("summary","查看原文证据"),readingText("p",evidence,"body-text"));return d;
}
async function detail() {
  const id = document.body.dataset.itemId,
    r = await api("/items/" + id),
    p = r.payload;
  content.replaceChildren();
  const c = card();
  c.append(readingTitle(r, true), readingSummary(r, true));
  c.append(
    node(
      "p",
      (p.company || "机构未知") +
        " · " +
        (p.country || "国家未知") +
        " · " +
        (p.city || "城市未知"),
      "muted",
    ),
  );
  if (p.kind === "job") {
    const employer=r.employer || {};
    c.append(node("p", employer.status === "verified" ? "雇主集团归属已核验：" + (employer.origin === "china_local" ? "中国本土" : "境外企业") : "企业待分类：原来源标签尚不能替代核验", "muted"));
    if(employer.name) {
      c.append(definitionList([["总部国家（独立于工作地点）",parseArray(employer.headquarters_countries).join(" / ")],["集团性质",({private:"民营/私人持有",publicly_listed:"上市公司",foundation_owned:"基金会主要持股",central_state:"央企",local_state:"地方国企",public_institution:"事业单位",joint_venture:"合资",unknown:"所有制待核验"}[employer.ownership] || employer.ownership)],["企业行业",employer.industry],["核验说明",employer.basis],["核验日期",formatDate(employer.verified_on)]]));
      parseArray(employer.evidence_urls).forEach(url=>c.append(Object.assign(node("a","查看企业核验依据"),{href:url,target:"_blank",rel:"noopener noreferrer"})));
    }
  }
  if (p.locations?.length) {
    const places = node("div", "", "entry-meta");
    p.locations.forEach(x => places.append(tag((x.primary ? "主要：" : "附加：") + [x.country, x.city || x.name].filter(Boolean).join(" · "), x.country ? "info" : "warning")));
    c.append(places);
    if (p.locations.length > 1) c.append(node("p", "官方列出多个地点；具体工作地、签证或搬迁要求请核对完整岗位原文。", "muted"));
  }
  if (p.is_demo)
    c.append(node("span", "合成演示数据，不是真实机会", "badge badge-warning"));
  const education = {
    associate: "大专",
    bachelor: "本科",
    master: "硕士",
    doctor: "博士",
    high_school: "高中",
  };
  c.append(
    definitionList([
      ["学历要求", education[p.education]],
      ["招聘届别", p.graduation_years?.length ? p.graduation_years.join(" / ") + "届" : p.graduation_year ? p.graduation_year + "届" : null],
      ["发布时间", timeNode(p.published_at)],
      ["本地内容更新", timeNode(r.updated_at)],
      ["招聘状态", r.recruitment?.label || "历史存档，状态未知"],
      ["状态依据与边界", r.recruitment?.basis],
      ["申请截止", formatDate(p.deadline)],
      [
        "截止状态",
        { open: "尚未截止", expired: "已截止", unknown: "尚未确认" }[
          r.deadline_status
        ],
      ],
      ["薪资", salaryLabel(p.salary)],
      ["实习类型", p.internship_type],
      ["本科在读资格", {confirmed:"原文明确接受本科在读；其他资格另核验",excluded:"本科条件不符合",unconfirmed:"未确认，不能认定符合"}[r.bachelor_status]],
      ["官方明确到岗日期", formatDate(p.start_date)],
      ["最近人工核验（导入者声明）", timeNode(p.source_verified_at)],
      ["人工核验说明", p.source_verification_note],
      ["在读要求", p.student_required == null ? null : p.student_required ? "明确要求在读" : "不要求在读"],
      ["专业要求（原文）", p.major],
      ["每周到岗", p.days_per_week ? p.days_per_week + "天" : null],
      ["持续时间", p.duration_months ? p.duration_months + "个月" : null],
      ...(p.kind === "opportunity"
        ? [
            ["项目开始 / 窗口起点", formatDate(p.start_date)],
            ["项目结束 / 窗口终点", formatDate(p.end_date)],
            ["总体费用", p.total_cost],
            ["资助信息", p.funding],
            ["语言要求", p.language],
            ["申请资格", p.eligibility],
          ]
        : []),
    ]),
  );
  if (p.risk_notes?.length)
    c.append(node("p", p.risk_notes.join("；"), "muted"));
  if (p.experience_requirements?.length) {
    append(c, node("h3", "经验年数与原文证据"), table(["性质 / 口径", "年数边界", "证据"], p.experience_requirements.map(x => [
      (labels[x.requirement] || x.requirement) + " / " + ({work:"工作经验",related:"相关领域，需复核",unspecified:"口径未确认"}[x.scope] || "未确认"),
      (x.minimum_years == null ? "" : "至少 " + x.minimum_years + " 年") + (x.maximum_years == null ? "" : " · 最多 " + x.maximum_years + " 年"), x.evidence])));
  }
  if (p.qualification_review_notes?.length) {
    append(c, node("h3", "待复核的资格条件"), node("p", "替代资格或实习与经验年数的冲突，请核对完整原文。", "muted"));
    p.qualification_review_notes.forEach(e => c.append(node("p", e, "body-text")));
  }
  c.append(readingBody(r));
  if (p.url) {
    const a = append(
      node("a", "", "btn btn-secondary"),
      icon("external-link"),
      node("span", "打开原始链接"),
    );
    a.href = p.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    c.append(a);
  }
  content.append(c);
  const grid = node("div", "", "grid detail-evidence"),
    skills = card("技能与原文证据");
  skills.append(
    table(
      ["技能", "性质", "证据"],
      r.skills.map((s) => {
        let evidence = node("span", s.evidence);
        if (s.evidence.length > 120) {
          evidence = node("details");
          append(
            evidence,
            node("summary", s.evidence.slice(0, 100) + "…"),
            node("p", s.evidence, "body-text"),
          );
        }
        return [
          node("span", s.skill, "mono"),
          node(
            "span",
            labels[s.requirement] || s.requirement,
            "badge " +
              (s.requirement === "required" ? "badge-accent" : "badge-neutral"),
          ),
          evidence,
        ];
      }),
      {
        emptyTitle: "尚未提取到技能",
        emptyText: "原文中明确出现的技能会显示在这里，并保留证据。",
      },
    ),
  );
  if (p.skill_groups?.length) {
    append(skills, node("h3", "技能组合条件"), table(["性质", "选项与数量", "原文证据"], p.skill_groups.map(g => [labels[g.requirement] || g.requirement, "至少 " + g.minimum + " 项：" + g.names.join(" / "), g.evidence])));
  }
  if (p.unparsed_skill_conditions?.length) {
    append(skills, node("h3", "待核验的技能组合"), node("p", "以下组合尚未完整解析，请核验原文。", "muted"));
    p.unparsed_skill_conditions.forEach(e => skills.append(node("p", e, "body-text")));
  }
  const matches = card("为什么推荐这个岗位？", "基于已确认条件的规则评分，不是录用或Offer概率。");
  matches.classList.add("match-explanation");
  if (p.kind === "job") {
    const result = r.explanation;
    if (result) {
      const headline = node("div", "", "row");
      append(headline, badge(result.hardStatus), scoreIndicator(result.score));
      matches.append(headline);
      matches.append(node("p", result.recommendation || "请核验原文与未知条件", "guidance"));
      if (result.breakdown?.length) {
        matches.append(table(["评分分项", "配置权重 / 满分贡献", "已确认程度", "实际贡献", "计算依据"], result.breakdown.map(part => [
          part.label, part.requestedWeight + " / " + part.maximum.toFixed(2),
          ({confirmed:"已确认",partial:"部分确认",unconfirmed:"待确认",unmatched:"未匹配",conflict:"明确冲突"}[part.status] || part.status) + " · " + Math.round(part.ratio*100) + "%",
          part.contribution.toFixed(2), append(node("div"), node("p",part.reason), ...part.evidence.map(evidenceDisclosure)),
        ])));
        matches.querySelector(".data-table").classList.add("match-breakdown");
        matches.append(node("p", "分项合计 " + result.baseScore.toFixed(2) + " + 优先级调整 " + (result.adjustments || []).reduce((sum,a)=>sum+a.delta,0).toFixed(2) + " = 最终 " + result.score.toFixed(2) + " / 100", "muted"));
        result.adjustments?.forEach(a=>matches.append(node("p",a.reason + "（" + a.delta.toFixed(2) + "）","muted")));
      }
      if (result.qualifications?.length) {
        matches.append(node("h3", "逐项招聘资格"), table(["条件", "保存的来源值", "档案值", "结论与依据"],result.qualifications.map(check=>[
          check.label, readableValue(check.sourceValue)||"未明确",readableValue(check.profileValue)||"未填写",
          append(node("div"),badge(({confirmed:"eligible",unconfirmed:"insufficient_information",conflict:"not_eligible",not_applicable:"unknown"}[check.status])),node("p",check.reason),evidenceDisclosure(check.evidence)),
        ])));
      }
      if(result.nextSteps?.length) {
        const next=node("ul");result.nextSteps.forEach(step=>next.append(node("li",step)));
        matches.append(node("h3","下一步需要确认"),next);
      }
      matches.append(button("核对保存的岗位原文",()=>{const original=content.querySelector(".reading-original");if(original){original.open=true;original.scrollIntoView({block:"start",behavior:"smooth"});}}));
      const reasons = node("ul", "", "reason-list");
      result.reasons?.forEach((text) => reasons.append(node("li", text)));
      matches.append(reasons);
      if (result.skillConditions?.length) {
        append(matches, node("h3", "逐项技能判断"), table(["条件", "已确认", "判断", "原文依据"], result.skillConditions.map(g => [
          (labels[g.requirement] || "历史条件") + " · 至少 " + g.minimum + " 项：" + g.names.join(" / "),
          g.confirmed.length ? g.confirmed.join(" / ") : "尚未确认",
          g.status === "satisfied" ? "已满足" : g.status === "not_required" ? "非必需，不计分" : "尚未确认满足", evidenceDisclosure(g.evidence),
        ])));
      }
      if (result.matchedSkills?.length) {
        const chips = node("div", "", "chips");
        result.matchedSkills.forEach((s) =>
          chips.append(node("span", s, "badge badge-success")),
        );
        append(matches, node("h3", "已确认匹配技能"), chips);
      }
      if (result.unconfirmedSkills?.length) {
        const chips = node("div", "", "chips");
        result.unconfirmedSkills.forEach((s) =>
          chips.append(node("span", s, "badge badge-neutral")),
        );
        append(matches, node("h3", "档案尚未确认掌握"), chips);
      }
    } else {
      matches.append(node("p", "等待匹配刷新：尚未计算，或岗位/档案/匹配规则已变化；旧评分暂不展示。", "muted"));
      matches.append(button("刷新当前匹配", async () => {
        await api("/matches/refresh", "POST", {}); await detail();
      }));
    }
    const apps = await api("/applications");
    append(
      matches,
      node("h3", "记录投递进度"),
      applicationForm(id, apps.find((a) => String(a.item_id) === id) || {}),
    );
  } else matches.append(node("p", "该信息通过通用订阅条件筛选。", "muted"));
  append(grid, skills, matches);
  content.append(grid);
  const provenance = card("来源与版本历史");
  provenance.append(
    table(
      ["来源", "验证状态", "记录标识"],
      r.sources.map((source) => [
        node("span", source.name),
        badge(source.status),
        node("span", source.external_id, "mono"),
      ]),
    ),
  );
  r.versions.forEach((v) => {
    const d = node("details"),
      summary = node("summary");
    append(
      summary,
      node("span", "版本 " + v.version),
      timeNode(v.created_at),
      node("span", "变化字段 " + v.changed_fields, "muted"),
    );
    append(d, summary, pre(v.payload));
    provenance.append(d);
  });
  content.append(provenance);
  const ai = card("AI 增强 · 建议需核实");
  if (!r.ai.length)
    ai.append(
      node("p", "尚未执行 AI 增强。规则提取和岗位匹配可以独立使用。", "muted"),
    );
  r.ai.forEach((x) => {
    append(
      ai,
      node("span", x.provider, "adapter-tag"),
      node("p", x.result.summary, "body-text"),
    );
    const d = node("details");
    append(d, node("summary", "查看提取字段与证据"), pre(x.result));
    ai.append(d);
  });
  ai.append(
    button(
      "请求可选增强",
      async () => {
        const task = await api("/items/" + id + "/enrich", "POST", {});
        msg("任务 #" + task.taskId + " 已排队；默认 AI 关闭，不会收费。");
        await taskFeedback(task.taskId);
      },
      "btn-secondary",
    ),
  );
  content.append(ai);
}

async function render() {
  translationGeneration++;clearTimeout(translationPollTimer);clearTimeout(translationStartTimer);
  const intros = {
    overview: "一个工作台，连接求职机会、技能差距与技术变化。",
    domestic: "中国本土企业在中国大陆的岗位；企业归属与工作地点分别核验。",
    foreign: "已核验境外企业在中国大陆的岗位；海外与待分类岗位保留独立入口。",
    opportunities: "海外交流与研究机会，费用、资助和资格以官方条件为准。",
    technology: "关注开源项目与版本更新，追踪每一次有意义的变化。",
    skills: "从已收集的岗位中观察技能需求，透明呈现样本和来源。",
    subscriptions: "定义筛选条件，跟踪新信息和内容变化。",
    applications: "记录投递进度、个人备注和已确认的日程。",
    monitor: "管理公开信息源，追踪采集任务与数据质量。",
    settings: "完善求职偏好与已确认技能，让匹配结果更有依据。",
    import: "保存原始来源，粘贴正文或导入合法获得的文件。",
    detail: "查看原文、匹配依据、来源证据与历史变化。",
  };
  document.querySelector("#intro").textContent = intros[section] || "";
  content.setAttribute("aria-busy", "true");
  const loading = emptyState("正在加载", "正在读取本地数据…");
  loading.classList.add("loading");
  loading.replaceChildren(node("span", "加载中…"));
  content.replaceChildren(loading);
  try {
    if (section === "overview") await overview();
    else if (
      ["domestic", "foreign", "opportunities", "technology"].includes(section)
    )
      await listing();
    else
      await {
        skills,
        settings,
        import: imports,
        subscriptions,
        applications,
        monitor,
        detail,
      }[section]();
  } catch (e) {
    const state = emptyState(
      "暂时无法加载",
      e.message + "。检查本地服务后可以重试。",
    );
    state.classList.add("error-state");
    state.replaceChildren(
      node("strong", "暂时无法加载"),
      node("p", e.message + "。检查本地服务后可以重试。", "muted"),
      button("重新加载", render, "btn-secondary"),
    );
    content.replaceChildren(state);
  } finally {
    content.removeAttribute("aria-busy");
  }
}
demo.onchange = () => {
  store("signalhubDemo", String(demo.checked));
  render();
};
render();
