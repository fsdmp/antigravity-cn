/* inject.js — Antigravity Hub 管理器界面翻译引擎 (由 zh_hub.py 通过 CDP 注入)
 *
 * 注入时机: document-start (Page.addScriptToEvaluateOnNewDocument)
 * 词典来源: DICT 占位符 (注释中故意不写字面量, 避免被替换), 由 zh_hub.py 注入时替换为 translations/hub.i18n.json
 *
 * 安全原则:
 *   - 仅做「文本节点全文精确匹配」替换, 词典里没有的文本一律不碰
 *   - 输入区物理免疫: INPUT/TEXTAREA/contenteditable/角色为文本框的子树绝不修改
 *   - 用户消息正文风险控制: 跳过常见正文容器; 精确匹配本身已排除绝大多数误替换
 */
(() => {
  "use strict";
  if (window.__AGY_ZH_INSTALLED__) return;
  window.__AGY_ZH_INSTALLED__ = true;

  const DICT = Object.create(null);
  for (const [k, v] of Object.entries(__DICT_JSON__)) DICT[k] = v;

  // 动态正则规则 (含数字计数/用户名/当前值等变体), 仅在精确匹配未命中时使用
  const PATTERNS = [
    [/^See all \((\d+)\)$/, "查看全部 ($1)"],
    [/^Hey ([\w .-]+), what should we build today\?$/, "嘿 $1，今天想做点什么？"],
    [/^Good to see you, (.+?)\. What's next\?$/, "很高兴见到你，$1。接下来做什么？"],
    [/^(.+), current: (.+)$/, "$1，当前：$2"],
    [/^Welcome back, (.+?)\. Where should we pick up\?$/, "欢迎回来，$1。我们从哪里继续？"],
    [/^Resume (\d+) comment drafts?$/, "恢复 $1 条评论草稿"],
    [/^(Show|Hide) (\d+) more$/, "$1后 $2 条"],
    [/^(\d+) (hours?|minutes?|days?|weeks?|months?) ago$/, "…"],
  ].filter(([, r]) => r !== "…");

  const IMMUNE_CLOSEST = [
    "input", "textarea", "select",
    "[contenteditable]", "[contenteditable] *",
    '[role="textbox"]', '[role="textbox"] *',
    ".monaco-editor", ".monaco-editor *",
    "code", "pre", "kbd", "samp",
  ].join(",");

  // 用户正文容器 (消息气泡/Markdown 正文等) — 这些子树不做替换
  const BODY_CONTAINER = [
    '[class*="message-body"]', '[class*="msg-body"]',
    '[data-message]', '[data-role="user"]',
  ].join(",");

  function isImmune(node) {
    let el = node.parentElement;
    if (!el) return true;
    if (el.closest(IMMUNE_CLOSEST)) return true;
    if (el.closest(BODY_CONTAINER)) return true;
    if (el.closest('[translate="no"]')) return true;
    return false;
  }

  function lookup(s) {
    let zh = DICT[s];
    if (zh !== undefined) return zh === s ? undefined : zh;
    for (const [re, rep] of PATTERNS) {
      if (re.test(s)) return s.replace(re, rep);
    }
    return undefined;
  }

  function translateTextNode(node) {
    const raw = node.nodeValue;
    if (!raw) return;
    const s = raw.trim();
    if (!s) return;
    const zh = lookup(s);
    if (zh === undefined) return;
    // 保留前后空白, 只替换中间文本
    const leadWs = raw.match(/^\s*/)[0];
    const trailWs = raw.match(/\s*$/)[0];
    node.nodeValue = leadWs + zh + trailWs;
  }

  function translateAttributes(root) {
    for (const el of root.querySelectorAll("[title],[placeholder],[aria-label],[data-tooltip]")) {
      for (const a of ["title", "placeholder", "aria-label", "data-tooltip"]) {
        const v = el.getAttribute(a);
        if (!v) continue;
        const zh = lookup(v.trim());
        if (zh !== undefined) el.setAttribute(a, zh);
      }
    }
  }

  function translateAll(root) {
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
    const walker = document.createTreeWalker(
      root.nodeType === Node.DOCUMENT_NODE ? document.body || root : root,
      NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const n of nodes) {
      if (!isImmune(n)) translateTextNode(n);
    }
    if (root.nodeType === Node.ELEMENT_NODE && root.querySelectorAll) {
      translateAttributes(root);
    }
  }

  // ---------- MutationObserver 调度 ----------
  let scheduled = false;
  const pending = new Set();
  function schedule(root) {
    pending.add(root);
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      const roots = Array.from(pending);
      pending.clear();
      for (const r of roots) translateAll(r);
    });
  }

  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "childList") {
        for (const n of m.addedNodes) {
          if (n.nodeType === Node.TEXT_NODE) { if (!isImmune(n)) translateTextNode(n); }
          else if (n.nodeType === Node.ELEMENT_NODE) schedule(n);
        }
      } else if (m.type === "characterData") {
        if (!isImmune(m.target)) translateTextNode(m.target);
      } else if (m.type === "attributes") {
        schedule(m.target);
      }
    }
  });

  function start() {
    translateAll(document);
    translateAttributes(document);
    observer.observe(document.documentElement, {
      childList: true, subtree: true, characterData: true,
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
