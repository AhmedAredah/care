/* frontend utilities — pure local DOM helpers, no external imports. */

(function (global) {
  "use strict";

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "class") {
          node.className = attrs[key];
        } else if (key === "text") {
          node.textContent = attrs[key];
        } else {
          node.setAttribute(key, attrs[key]);
        }
      });
    }
    if (Array.isArray(children)) {
      children.forEach(function (c) {
        if (c == null) return;
        if (typeof c === "string") node.appendChild(document.createTextNode(c));
        else node.appendChild(c);
      });
    }
    return node;
  }

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  function show(node) { if (node) node.classList.remove("hidden"); }
  function hide(node) { if (node) node.classList.add("hidden"); }

  function setBadge(node, kind, text) {
    if (!node) return;
    node.className = "badge badge-" + kind;
    node.textContent = text;
  }

  function fmtPct(value) {
    if (value === null || value === undefined) return "—";
    return (Math.round(Number(value) * 1000) / 10).toFixed(1) + "%";
  }

  function shortId(value) {
    if (!value) return "";
    return String(value).slice(0, 16);
  }

  /* Strip surrounding whitespace AND a single matched pair of quotes.
     Operators often paste paths copied from Explorer / shell with quotes:
       "C:\Users\X\file.pdf"  →  C:\Users\X\file.pdf */
  function cleanPath(value) {
    if (value == null) return "";
    var s = String(value).trim();
    if (s.length < 2) return s;
    var first = s.charAt(0);
    var last = s.charAt(s.length - 1);
    var pairs = [
      ['"', '"'],
      ["'", "'"],
      ["“", "”"],
      ["‘", "’"],
    ];
    for (var i = 0; i < pairs.length; i++) {
      if (first === pairs[i][0] && last === pairs[i][1]) {
        return s.slice(1, -1);
      }
    }
    return s;
  }

  global.OCEUtils = {
    escapeHtml: escapeHtml,
    el: el,
    clear: clear,
    show: show,
    hide: hide,
    setBadge: setBadge,
    fmtPct: fmtPct,
    shortId: shortId,
    cleanPath: cleanPath,
  };
})(window);
