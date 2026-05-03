/* CARE — main UI controller. Local-only; every fetch hits /api/* on
   this same origin.

   Workflow IA: Process → Review → Export, with Plugins / Templates /
   Settings / Diagnostics under an Advanced submenu. Old hash routes
   (#dashboard, #jobs, #reports, …) are redirected to the new ones so
   bookmarks and CLI links keep working.
*/

(function () {
  "use strict";

  var u = window.OCEUtils;
  var api = window.OCEApi;
  var qa = window.OCEQAGlossary;

  var VIEWS = [
    "process", "review", "report-detail", "export",
    "plugins", "templates", "settings", "diagnostics",
  ];

  /* Old → new hash redirects. Keeps deep-links from earlier docs and
     CLI output working. */
  var HASH_REDIRECTS = {
    dashboard: "process",
    jobs: "process",
    reports: "review",
    exports: "export",
    "template-builder": "templates",
    offline: "diagnostics",
  };

  var builderInited = false;
  var activeJobsTimer = null;
  var currentReviewQueue = "attention";

  /* ---- view routing -------------------------------------------------- */

  function showView(name, params) {
    VIEWS.forEach(function (v) {
      var node = document.getElementById("view-" + v);
      if (!node) return;
      if (v === name) u.show(node); else u.hide(node);
    });
    document.querySelectorAll(".nav-link, .nav-menu-item").forEach(function (a) {
      a.classList.toggle("active", a.dataset && a.dataset.view === name);
    });
    closeAdvancedMenu();

    if (name === "process") refreshProcess();
    if (name === "review") refreshReview();
    if (name === "report-detail") openReport(params && params.report_id);
    if (name === "export") refreshExports();
    if (name === "plugins") refreshPlugins();
    if (name === "diagnostics") refreshDiagnostics();
    if (name === "settings") refreshSettings();
    if (name === "templates") {
      if (!builderInited && window.OCEBuilder) {
        window.OCEBuilder.init();
        builderInited = true;
      }
    }
  }

  function parseHash() {
    var hash = (window.location.hash || "").replace(/^#/, "");
    var parts = hash.split("/");
    var head = parts[0] || "process";

    /* Redirect legacy 'report/<id>' to 'review/<id>'. */
    if (head === "report" && parts[1]) {
      window.location.hash = "review/" + parts[1];
      return { view: "report-detail", report_id: parts[1] };
    }

    /* Apply renames for top-level views. */
    if (HASH_REDIRECTS[head]) {
      window.location.hash = HASH_REDIRECTS[head];
      head = HASH_REDIRECTS[head];
    }

    if (head === "review" && parts[1]) {
      return { view: "report-detail", report_id: parts[1] };
    }

    if (VIEWS.indexOf(head) === -1) head = "process";
    return { view: head };
  }

  function navigate() {
    var p = parseHash();
    showView(p.view, p);
  }

  /* ---- toasts -------------------------------------------------------- */

  function toast(message, kind) {
    var host = document.getElementById("toast-region");
    if (!host) return;
    var node = u.el("div", { class: "toast toast-" + (kind || "ok"), text: message });
    host.appendChild(node);
    setTimeout(function () {
      node.style.transition = "opacity 0.18s ease";
      node.style.opacity = "0";
      setTimeout(function () {
        if (node.parentNode) node.parentNode.removeChild(node);
      }, 250);
    }, 3500);
  }

  /* ---- offline status indicator (always visible) -------------------- */

  /* Tooltip copy is split across two states. Both end with an
     actionable "how to flip this" so the operator never has to guess
     which knob controls the indicator. ``offline.enabled`` is NOT a
     locked key (see care/core/governance_guard.py — only the export
     and logging guarantees are immutable), so the Settings page does
     let the operator toggle it. The runtime guard is monkey-patched
     into the process at startup, so a save needs an app restart to
     take effect — the tooltip says so. */
  var TOOLTIP_OFFLINE_ON =
    "Offline mode active. Outbound network calls (sockets, urllib, " +
    "Hugging Face client) are blocked at runtime; only loopback " +
    "(127.0.0.1, ::1, localhost) is allowed.\n\n" +
    "To disable: click here (or open Settings → offline) → uncheck " +
    "\"enabled\" → Save changes in this section → restart the app. " +
    "Note: cloud LLM providers also require offline.enabled=false " +
    "plus an explicit acknowledged_external_data_egress flag.";

  var TOOLTIP_OFFLINE_OFF =
    "Network access enabled — the runtime offline guard is OFF. " +
    "Outbound calls from this process are NOT blocked. This is " +
    "appropriate only for cloud-LLM workflows or development.\n\n" +
    "To re-enable (recommended before processing sensitive crash " +
    "reports): click here (or open Settings → offline) → check " +
    "\"enabled\" → Save changes in this section → restart the app.";

  function refreshOfflineBadge() {
    var node = document.getElementById("offline-status");
    if (!node) return;
    api.offline().then(function (data) {
      var label = node.querySelector(".offline-label");
      var ok = data.offline_guard_enabled && data.offline_config_enabled;
      node.classList.remove(
        "offline-status-on", "offline-status-off", "offline-status-unknown"
      );
      if (ok) {
        node.classList.add("offline-status-on");
        if (label) label.textContent = "Offline mode active";
        node.title = TOOLTIP_OFFLINE_ON;
      } else {
        node.classList.add("offline-status-off");
        if (label) label.textContent = "Network access enabled";
        node.title = TOOLTIP_OFFLINE_OFF;
      }
    }).catch(function () {
      node.classList.add("offline-status-unknown");
      var label = node.querySelector(".offline-label");
      if (label) label.textContent = "Status unknown";
      node.title =
        "Could not reach /api/offline/status. The server may be " +
        "starting; this badge auto-refreshes every 30 seconds.";
    });
  }

  /* Click / Enter / Space jumps to the offline section of Settings,
     which is exactly the section the tooltip tells the operator to
     edit. The section opens by default (see settings.js) so the
     "enabled" checkbox is visible without further clicks. */
  function bindOfflineBadgeClick() {
    var node = document.getElementById("offline-status");
    if (!node) return;
    node.setAttribute("role", "button");
    node.setAttribute("tabindex", "0");
    node.style.cursor = "pointer";
    function go() { window.location.hash = "settings"; }
    node.addEventListener("click", go);
    node.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        go();
      }
    });
  }

  /* ---- advanced menu ------------------------------------------------- */

  function bindAdvancedMenu() {
    var btn = document.getElementById("advanced-menu-btn");
    var menu = document.getElementById("advanced-menu");
    if (!btn || !menu) return;
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = !menu.classList.contains("hidden");
      if (open) closeAdvancedMenu();
      else openAdvancedMenu();
    });
    document.addEventListener("click", function (e) {
      if (!menu.contains(e.target) && e.target !== btn) closeAdvancedMenu();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeAdvancedMenu();
    });
  }

  function openAdvancedMenu() {
    var btn = document.getElementById("advanced-menu-btn");
    var menu = document.getElementById("advanced-menu");
    if (!menu || !btn) return;
    menu.classList.remove("hidden");
    btn.setAttribute("aria-expanded", "true");
  }

  function closeAdvancedMenu() {
    var btn = document.getElementById("advanced-menu-btn");
    var menu = document.getElementById("advanced-menu");
    if (!menu || !btn) return;
    menu.classList.add("hidden");
    btn.setAttribute("aria-expanded", "false");
  }

  /* ---- new-job drawer ------------------------------------------------ */

  function openDrawer(id) {
    var node = document.getElementById(id);
    if (!node) return;
    node.classList.remove("hidden");
    var first = node.querySelector("input, button, textarea");
    if (first) first.focus();
  }

  function closeDrawer(id) {
    var node = document.getElementById(id);
    if (!node) return;
    node.classList.add("hidden");
  }

  function bindDrawer() {
    var newJobBtn = document.getElementById("new-job-btn");
    if (newJobBtn) newJobBtn.addEventListener("click", function () {
      openDrawer("new-job-drawer");
    });

    document.querySelectorAll("[data-close-drawer]").forEach(function (n) {
      n.addEventListener("click", function () {
        closeDrawer(n.dataset.closeDrawer);
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        document.querySelectorAll(".drawer:not(.hidden)").forEach(function (d) {
          d.classList.add("hidden");
        });
      }
    });

    var form = document.getElementById("new-job-form");
    if (form) form.addEventListener("submit", submitNewJob);
  }

  function submitNewJob(event) {
    event.preventDefault();
    var input = u.cleanPath(document.getElementById("input-dir").value);
    var jurisdiction = (document.getElementById("job-jurisdiction").value || "").trim();
    var rawIds = (document.getElementById("job-template-ids").value || "").trim();
    var templateIds = rawIds
      ? rawIds.split(",").map(function (s) { return s.trim(); }).filter(Boolean)
      : [];
    var resultBox = document.getElementById("new-job-result");
    api.submitJob(input, { jurisdiction: jurisdiction, templateIds: templateIds })
      .then(function (job) {
        u.hide(resultBox);
        closeDrawer("new-job-drawer");
        toast("Run submitted (" + (job.report_ids ? job.report_ids.length : "?") +
          " reports queued)", "ok");
        refreshProcess();
        startActiveJobsPolling();
      })
      .catch(function (err) {
        resultBox.textContent = "Error: " + err.message;
        u.show(resultBox);
        toast("Submit failed: " + err.message, "bad");
      });
  }

  /* ---- Process page (jobs + active runs) --------------------------- */

  function refreshProcess() {
    refreshActiveJobs();
    refreshJobsTable();
  }

  function refreshActiveJobs() {
    var host = document.getElementById("active-jobs");
    if (!host) return;
    api.listJobs().then(function (data) {
      var running = (data.jobs || []).filter(function (j) {
        return j.status === "running" || j.status === "pending";
      });
      u.clear(host);
      if (!running.length) {
        u.hide(host);
        if (activeJobsTimer) {
          clearInterval(activeJobsTimer);
          activeJobsTimer = null;
        }
        return;
      }
      u.show(host);
      running.forEach(function (j) {
        host.appendChild(activeJobCard(j));
      });
    }).catch(function () { /* tolerate transient */ });
  }

  function activeJobCard(job) {
    var card = u.el("div", { class: "active-job-card" });
    var header = u.el("div", { class: "active-job-header" });
    header.appendChild(u.el("span", {
      class: "active-job-title",
      text: "Run " + u.shortId(job.job_id),
    }));
    header.appendChild(u.el("span", {
      class: "badge badge-warn",
      text: job.status,
    }));
    card.appendChild(header);
    card.appendChild(u.el("p", {
      class: "small muted",
      text: "Submitted " + (job.submitted_at || "") +
            " · processing report folder; this view refreshes every 2s.",
    }));
    var bar = u.el("div", { class: "progress-bar" });
    bar.appendChild(u.el("div", { class: "progress-bar-fill indeterminate" }));
    card.appendChild(bar);
    return card;
  }

  function startActiveJobsPolling() {
    if (activeJobsTimer) return;
    activeJobsTimer = setInterval(function () {
      if (document.getElementById("view-process").classList.contains("hidden")) {
        return;
      }
      refreshActiveJobs();
      refreshJobsTable();
    }, 2000);
  }

  function refreshJobsTable() {
    var tbody = document.getElementById("jobs-tbody");
    var empty = document.getElementById("jobs-empty");
    var table = document.getElementById("jobs-table");
    if (!tbody) return;
    api.listJobs().then(function (data) {
      var jobs = data.jobs || [];
      u.clear(tbody);
      if (!jobs.length) {
        if (empty) u.show(empty);
        if (table) u.hide(table);
        return;
      }
      if (empty) u.hide(empty);
      if (table) u.show(table);

      jobs.forEach(function (j) {
        var reportLinks = (j.report_ids || []).map(function (r, idx) {
          var link = u.el("a", {
            href: "#review/" + r,
            text: u.shortId(r),
          });
          if (idx > 0) {
            return [document.createTextNode(", "), link];
          }
          return [link];
        });
        var reportsCell = u.el("td");
        if (reportLinks.length) {
          reportLinks.forEach(function (parts) {
            parts.forEach(function (p) { reportsCell.appendChild(p); });
          });
        } else {
          reportsCell.textContent = "—";
        }
        var filterCell = u.el("td");
        filterCell.classList.add("muted");
        filterCell.classList.add("small");
        if (j.template_filter) {
          var pieces = [];
          if (j.template_filter.jurisdiction) {
            pieces.push("jurisdiction = " + j.template_filter.jurisdiction);
          }
          if (j.template_filter.template_ids) {
            pieces.push(
              "template_ids ∈ {" + j.template_filter.template_ids.join(", ") + "}"
            );
          }
          filterCell.textContent = pieces.join(" AND ") || "auto-detect";
          filterCell.title =
            "The template-detection step considered only templates " +
            "matching this filter. Auto-detect (no filter) considers " +
            "every installed template.";
        } else {
          filterCell.textContent = "auto-detect (all templates)";
          filterCell.title =
            "No filter — the template-detection step considered every " +
            "template in the configured templates_dir.";
        }
        var statusBadge = u.el("span", {
          class: "badge " + statusBadgeClass(j.status),
          text: j.status,
        });
        tbody.appendChild(u.el("tr", null, [
          u.el("td", null, [u.el("code", { text: u.shortId(j.job_id) })]),
          u.el("td", null, [statusBadge]),
          u.el("td", { text: j.submitted_at || "" }),
          reportsCell,
          filterCell,
          u.el("td", null, [
            j.report_ids && j.report_ids.length
              ? u.el("a", { href: "#review", text: "open queue" })
              : document.createTextNode("—"),
          ]),
        ]));
      });
    });
  }

  function statusBadgeClass(status) {
    if (status === "complete") return "badge-ok";
    if (status === "failed") return "badge-bad";
    return "badge-warn";
  }

  /* ---- Review queue ------------------------------------------------- */

  function bindReviewQueueTabs() {
    document.querySelectorAll(".queue-tab").forEach(function (t) {
      t.addEventListener("click", function () {
        currentReviewQueue = t.dataset.queue;
        document.querySelectorAll(".queue-tab").forEach(function (b) {
          b.classList.toggle("active", b === t);
          b.setAttribute("aria-selected", b === t ? "true" : "false");
        });
        refreshReview();
      });
    });
  }

  function refreshReview() {
    var tbody = document.getElementById("review-tbody");
    var empty = document.getElementById("review-empty");
    var table = document.getElementById("review-table");
    if (!tbody) return;
    api.listExports().then(function (exportsList) {
      var ids = (exportsList.reports || []).map(function (r) { return r.report_id; });
      Promise.all(ids.map(function (id) {
        return api.getReport(id).catch(function () { return null; });
      })).then(function (views) {
        var clean = views.filter(Boolean);
        var counts = countByQueue(clean);
        Object.keys(counts).forEach(function (k) {
          var n = document.querySelector('[data-queue-count="' + k + '"]');
          if (n) n.textContent = String(counts[k]);
        });
        var filtered = filterByQueue(clean, currentReviewQueue);
        u.clear(tbody);
        if (!filtered.length) {
          if (empty) u.show(empty);
          if (table) u.hide(table);
          return;
        }
        if (empty) u.hide(empty);
        if (table) u.show(table);
        filtered.forEach(function (v) { tbody.appendChild(reviewRow(v)); });
      });
    }).catch(function () { /* tolerate */ });
  }

  function isAttention(v) {
    if (v.qa_export_blocked) return true;
    if (v.qa_requires_human_review && v.review.decision === "PENDING") return true;
    if (v.review.decision === "PENDING") return true;
    return false;
  }

  function countByQueue(views) {
    var counts = { attention: 0, approved: 0, rejected: 0, all: views.length };
    views.forEach(function (v) {
      if (v.review.decision === "APPROVED") counts.approved++;
      else if (v.review.decision === "REJECTED") counts.rejected++;
      else if (isAttention(v)) counts.attention++;
    });
    return counts;
  }

  function filterByQueue(views, queue) {
    if (queue === "all") return views;
    if (queue === "approved") {
      return views.filter(function (v) { return v.review.decision === "APPROVED"; });
    }
    if (queue === "rejected") {
      return views.filter(function (v) { return v.review.decision === "REJECTED"; });
    }
    return views.filter(function (v) {
      return v.review.decision === "PENDING" && isAttention(v);
    });
  }

  function reviewRow(v) {
    var decision = v.qa_decision === "ALLOW" ? "ok" :
                   v.qa_export_blocked ? "block" : "review";
    var decisionPill = u.el("span", {
      class: "decision-pill decision-pill-" + decision,
      text: v.qa_decision + (v.qa_export_blocked ? " · blocked" : ""),
    });
    var reviewBadge = u.el("span", {
      class: "badge " + (
        v.review.decision === "APPROVED" ? "badge-ok" :
        v.review.decision === "REJECTED" ? "badge-bad" : "badge-warn"
      ),
      text: v.review.decision,
    });

    var topFlag = qa ? qa.topConcern(v.qa_flags || []) : null;
    var concernText, concernTitle;
    if (topFlag) {
      var entry = qa.explain(topFlag);
      concernText = entry.title;
      concernTitle = entry.detail + "\n\nFlag code: " + topFlag;
    } else if (v.qa_export_blocked) {
      concernText = "Export blocked";
      concernTitle = (v.qa_blocking_reasons || []).join(" · ");
    } else {
      concernText = "—";
      concernTitle = "No QA concerns raised.";
    }
    var concern = u.el("span", { class: "review-concern", text: concernText });
    concern.title = concernTitle;

    return u.el("tr", null, [
      u.el("td", null, [u.el("code", { text: u.shortId(v.report_id) })]),
      u.el("td", null, [
        u.el("span", { text: v.template_id || "—" }),
        document.createTextNode(" "),
        u.el("span", {
          class: "muted small",
          text: "(" + u.fmtPct(v.template_confidence) + ")",
        }),
      ]),
      u.el("td", null, [decisionPill]),
      u.el("td", null, [reviewBadge]),
      u.el("td", null, [concern]),
      u.el("td", null, [u.el("a", {
        href: "#review/" + v.report_id, text: "open →",
      })]),
    ]);
  }

  /* ---- Report detail ----------------------------------------------- */

  function openReport(reportId) {
    if (!reportId || !/^[0-9a-f]{16}$/.test(reportId)) {
      var t = document.getElementById("report-detail-title");
      if (t) t.textContent = "Invalid report id";
      return;
    }
    document.getElementById("report-detail-title").textContent =
      "Report " + u.shortId(reportId);
    document.getElementById("report-detail-subtitle").textContent =
      "id " + reportId;
    api.getReport(reportId).then(function (v) { renderReport(reportId, v); });
  }

  function setDecisionBanner(view) {
    var banner = document.getElementById("decision-banner");
    var title = document.getElementById("decision-banner-title");
    var subtitle = document.getElementById("decision-banner-subtitle");
    var actions = document.getElementById("decision-banner-actions");
    if (!banner) return;
    banner.classList.remove(
      "decision-banner-ok",
      "decision-banner-review",
      "decision-banner-block",
      "decision-banner-unknown"
    );
    u.clear(actions);

    if (view.qa_export_blocked) {
      banner.classList.add("decision-banner-block");
      title.textContent = "Export blocked by the fail-closed gate";
      subtitle.textContent =
        (view.qa_blocking_reasons && view.qa_blocking_reasons[0])
          ? view.qa_blocking_reasons[0]
          : "Pipeline refused to export until the upstream issue is resolved.";
      banner.querySelector(".decision-banner-icon").innerHTML = svgIcon("lock");
    } else if (view.qa_requires_human_review || view.review.decision === "PENDING") {
      banner.classList.add("decision-banner-review");
      title.textContent = "Awaiting reviewer";
      subtitle.textContent =
        "Pipeline allowed export. A reviewer should compare the redacted " +
        "diagram and narrative against the original before approving.";
      banner.querySelector(".decision-banner-icon").innerHTML = svgIcon("eye");
    } else if (view.review.decision === "APPROVED") {
      banner.classList.add("decision-banner-ok");
      title.textContent = "Approved for release";
      subtitle.textContent =
        "Reviewer " + (view.review.reviewer || "—") + " approved this " +
        "report. Redacted artifacts are safe to release.";
      banner.querySelector(".decision-banner-icon").innerHTML = svgIcon("check");
    } else if (view.review.decision === "REJECTED") {
      banner.classList.add("decision-banner-block");
      title.textContent = "Rejected by reviewer";
      subtitle.textContent =
        "Reviewer " + (view.review.reviewer || "—") + " rejected this " +
        "report. Redacted artifacts remain on disk for audit only.";
      banner.querySelector(".decision-banner-icon").innerHTML = svgIcon("x");
    } else {
      banner.classList.add("decision-banner-unknown");
      title.textContent = "Status unknown";
      subtitle.textContent = "";
      banner.querySelector(".decision-banner-icon").innerHTML = "";
    }
  }

  function svgIcon(name) {
    /* Inline SVG strings — local-only, no external sprite. */
    var common = 'viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
    if (name === "check") {
      return '<svg ' + common + '><polyline points="5 12 10 17 19 8"></polyline></svg>';
    }
    if (name === "lock") {
      return '<svg ' + common + '><rect x="4" y="10" width="16" height="10" rx="2"></rect><path d="M8 10 V7 a4 4 0 0 1 8 0 v3"></path></svg>';
    }
    if (name === "eye") {
      return '<svg ' + common + '><path d="M2 12 s4 -7 10 -7 10 7 10 7 -4 7 -10 7 -10 -7 -10 -7 z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
    }
    if (name === "x") {
      return '<svg ' + common + '><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>';
    }
    return "";
  }

  function renderReport(reportId, v) {
    setDecisionBanner(v);
    renderReportMeta(v);
    renderQAFlags(v);
    renderDiagram(reportId, v);
    renderNarrative(reportId, v);

    var approveBtn = document.getElementById("approve-btn");
    if (approveBtn) {
      approveBtn.disabled = !!v.qa_export_blocked;
      approveBtn.title = v.qa_export_blocked
        ? "Cannot approve — pipeline QA gate already blocked the export. " +
          "Reprocess after correcting the upstream issue."
        : "Mark this report as approved for release.";
    }
    var openExportBtn = document.getElementById("open-export-btn");
    if (openExportBtn) {
      openExportBtn.disabled = !!v.qa_export_blocked;
      openExportBtn.onclick = function () {
        window.location.hash = "export";
      };
    }
    if (window.OCEReview) window.OCEReview.bind(reportId, refreshReport);
    function refreshReport() { openReport(reportId); }
  }

  function renderReportMeta(v) {
    var meta = document.getElementById("report-meta");
    if (!meta) return;
    u.clear(meta);
    var rows = [
      ["Template", v.template_id || "—"],
      ["Template confidence", u.fmtPct(v.template_confidence)],
      ["Diagram confidence", u.fmtPct(v.diagram_confidence)],
      ["Narrative confidence", u.fmtPct(v.narrative_confidence)],
      ["Text source", v.text_source || "—"],
      ["OCR provider used", v.ocr_provider_used || "—"],
      ["Pipeline decision", v.qa_decision],
      ["Reviewer decision", v.review.decision],
      ["PII entities", String(v.qa_pii_entity_count)],
      ["PII unmapped", String(v.qa_pii_unmapped_count)],
    ];
    rows.forEach(function (pair) {
      meta.appendChild(u.el("dt", { text: pair[0] }));
      meta.appendChild(u.el("dd", { text: pair[1] }));
    });
  }

  function renderQAFlags(v) {
    var flagsHost = document.getElementById("qa-flags");
    var emptyMsg = document.getElementById("qa-empty");
    var blockHost = document.getElementById("qa-blocking-reasons");
    if (!flagsHost) return;
    u.clear(flagsHost);
    u.clear(blockHost);
    var flags = v.qa_flags || [];
    if (!flags.length) {
      if (emptyMsg) u.show(emptyMsg);
    } else {
      if (emptyMsg) u.hide(emptyMsg);
      flags.forEach(function (code) {
        var entry = qa ? qa.explain(code) : { title: code, detail: code, severity: "review" };
        var li = u.el("li", { text: entry.title });
        li.title = entry.detail + (entry.advice ? "\n\nNext step: " + entry.advice : "") +
          "\n\nFlag code: " + code;
        if (entry.severity === "block") li.classList.add("flag-block");
        else if (entry.severity === "info") li.classList.add("flag-info");
        flagsHost.appendChild(li);
      });
    }
    if (v.qa_export_blocked && (v.qa_blocking_reasons || []).length) {
      blockHost.appendChild(u.el("p", {
        text: "Export blocked. Reasons:",
      }));
      var ul = u.el("ul");
      (v.qa_blocking_reasons || []).forEach(function (r) {
        ul.appendChild(u.el("li", { text: r }));
      });
      blockHost.appendChild(ul);
    }
  }

  function renderDiagram(reportId, v) {
    var host = document.getElementById("diagram-host");
    var status = document.getElementById("diagram-status");
    if (!host) return;
    u.clear(host);
    if (v.qa_export_blocked) {
      host.appendChild(u.el("p", {
        class: "muted small",
        text: "Diagram preview unavailable — export was blocked by the QA gate.",
      }));
      return;
    }
    var img = u.el("img", {
      alt: "Redacted crash diagram",
      src: api.diagramUrl(reportId),
    });
    host.appendChild(img);
    if (status) {
      status.textContent = "Redacted page crop. Original PDFs are never served.";
    }
  }

  function renderNarrative(reportId, v) {
    var narrHost = document.getElementById("narrative-host");
    var piiList = document.getElementById("pii-list");
    var piiEmpty = document.getElementById("pii-empty");
    if (!narrHost) return;
    u.clear(narrHost);
    u.clear(piiList);

    if (v.qa_export_blocked) {
      narrHost.appendChild(u.el("p", {
        class: "muted small",
        text: "Narrative unavailable — export blocked by the QA gate.",
      }));
      if (piiEmpty) u.show(piiEmpty);
      return;
    }

    api.getReportNarrative(reportId).then(function (payload) {
      renderNarrativeWithHighlights(narrHost, piiList, piiEmpty,
        payload.text || "", payload.entities_redacted || []);
    }).catch(function (err) {
      narrHost.textContent = "Error loading narrative: " + err.message;
    });
  }

  /* Build the narrative pane with inline span highlights and a
     mirroring sidebar list. Clicking either side highlights the other. */
  function renderNarrativeWithHighlights(host, list, emptyMsg, text, entities) {
    if (!entities.length) {
      host.textContent = text;
      if (list) u.clear(list);
      if (emptyMsg) u.show(emptyMsg);
      return;
    }
    if (emptyMsg) u.hide(emptyMsg);

    /* Sort entities by start_offset for sequential rendering. Some
       providers may not emit offsets — those entities only appear in
       the sidebar. */
    var withOffsets = entities.filter(function (e) {
      return typeof e.start_offset === "number" && typeof e.end_offset === "number" &&
             e.end_offset > e.start_offset && e.start_offset >= 0;
    }).slice().sort(function (a, b) { return a.start_offset - b.start_offset; });

    /* Render text with marked spans. */
    var cursor = 0;
    var entityNodes = {};
    withOffsets.forEach(function (e, idx) {
      if (e.start_offset > cursor) {
        host.appendChild(document.createTextNode(text.slice(cursor, e.start_offset)));
      }
      var span = u.el("span", {
        class: "narrative-redaction",
        text: text.slice(e.start_offset, e.end_offset),
      });
      span.dataset.idx = String(idx);
      span.title = e.entity_type + " — provider: " + (e.provider || "?");
      span.addEventListener("click", function () { focusEntity(idx); });
      host.appendChild(span);
      entityNodes[idx] = span;
      cursor = e.end_offset;
    });
    if (cursor < text.length) {
      host.appendChild(document.createTextNode(text.slice(cursor)));
    }

    /* Sidebar list mirrors the inline highlights, with a row for each
       offset-bearing entity plus tail rows for entities without
       offsets. */
    u.clear(list);
    withOffsets.forEach(function (e, idx) {
      list.appendChild(piiRow(idx, e, entityNodes));
    });
    entities.filter(function (e) {
      return !(typeof e.start_offset === "number" && typeof e.end_offset === "number" &&
               e.end_offset > e.start_offset && e.start_offset >= 0);
    }).forEach(function (e) {
      list.appendChild(piiRowNoOffset(e));
    });

    function focusEntity(idx) {
      Object.keys(entityNodes).forEach(function (k) {
        entityNodes[k].classList.toggle("is-active", String(k) === String(idx));
      });
      Array.from(list.children).forEach(function (li) {
        li.classList.toggle("is-active", li.dataset.idx === String(idx));
      });
      if (entityNodes[idx]) {
        entityNodes[idx].scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    }
  }

  function piiRow(idx, entity, entityNodes) {
    var li = u.el("li");
    li.dataset.idx = String(idx);
    li.appendChild(u.el("span", { class: "pii-type", text: entity.entity_type }));
    li.appendChild(u.el("span", {
      class: "pii-provider",
      text: entity.provider || "?",
    }));
    li.appendChild(u.el("span", {
      class: "pii-offsets",
      text: entity.start_offset + "–" + entity.end_offset,
    }));
    li.addEventListener("click", function () {
      Object.keys(entityNodes).forEach(function (k) {
        entityNodes[k].classList.toggle("is-active", String(k) === String(idx));
      });
      Array.from(li.parentNode.children).forEach(function (other) {
        other.classList.toggle("is-active", other === li);
      });
      if (entityNodes[idx]) {
        entityNodes[idx].scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    });
    return li;
  }

  function piiRowNoOffset(entity) {
    var li = u.el("li");
    li.appendChild(u.el("span", { class: "pii-type", text: entity.entity_type }));
    li.appendChild(u.el("span", {
      class: "pii-provider",
      text: entity.provider || "?",
    }));
    li.appendChild(u.el("span", {
      class: "pii-offsets",
      text: "no offsets",
    }));
    li.title = "Detected by " + (entity.provider || "?") +
      " without character offsets — only visible in the inventory.";
    return li;
  }

  /* ---- Exports view ------------------------------------------------ */

  function refreshExports() {
    var tbody = document.getElementById("exports-tbody");
    var empty = document.getElementById("exports-empty");
    var table = document.getElementById("exports-table");
    if (!tbody) return;
    api.listExports().then(function (data) {
      var rows = data.reports || [];
      u.clear(tbody);
      if (!rows.length) {
        if (empty) u.show(empty);
        if (table) u.hide(table);
        return;
      }
      if (empty) u.hide(empty);
      if (table) u.show(table);
      rows.forEach(function (r) {
        tbody.appendChild(u.el("tr", null, [
          u.el("td", null, [u.el("a", {
            href: "#review/" + r.report_id, text: u.shortId(r.report_id),
          })]),
          u.el("td", null, [u.el("span", {
            class: "muted small",
            text: (r.files || []).join(" · "),
          })]),
          u.el("td", null, [u.el("a", {
            href: "#review/" + r.report_id, text: "open report →",
          })]),
        ]));
      });
    });
  }

  /* ---- Plugins ----------------------------------------------------- */

  function refreshPlugins() {
    var host = document.getElementById("plugins-host");
    if (!host) return;
    api.plugins().then(function (data) {
      window.OCEPlugins.render(host, data, refreshPlugins);
    });
  }

  /* ---- Diagnostics ------------------------------------------------- */

  function refreshDiagnostics() {
    var box = document.getElementById("offline-detail");
    if (box) {
      api.offline().then(function (data) {
        box.textContent = JSON.stringify(data, null, 2);
        setHealthCard(
          "health-offline",
          data.offline_guard_enabled && data.offline_config_enabled,
          data.offline_guard_enabled && data.offline_config_enabled
            ? "Offline guard active. No outbound network."
            : "Offline guard is off — review settings before processing."
        );
      });
    }
    api.plugins().then(function (data) {
      var sections = [data.ocr, data.document_ai, data.pii];
      var totalActive = 0;
      var unhealthy = 0;
      sections.forEach(function (sec) {
        (sec && sec.providers || []).forEach(function (p) {
          if (p.enabled && p.in_active_chain) {
            totalActive++;
            if (p.model_files_present === false) unhealthy++;
          }
        });
      });
      var ok = totalActive > 0 && unhealthy === 0;
      var msg;
      if (totalActive === 0) {
        msg = "No active plugins in any chain. Enable an OCR or PII " +
              "provider on the Plugins page.";
      } else if (unhealthy > 0) {
        msg = unhealthy + " active plugin(s) have missing model files.";
      } else {
        msg = totalActive + " plugin(s) active across all chains; model " +
              "files look healthy.";
      }
      setHealthCard("health-plugins", ok, msg);
    }).catch(function () {
      setHealthCard("health-plugins", false, "Could not reach plugin registry.");
    });

    /* Template count via /api/config — templates_dir path stays
       server-side, we only check whether at least one is loaded by
       hitting the /api/jobs endpoint indirectly. Lacking a dedicated
       endpoint we surface a soft "Templates page" pointer instead. */
    setHealthCard(
      "health-templates",
      null,
      "Open the Template builder to author or inspect installed templates."
    );
  }

  function setHealthCard(id, ok, message) {
    var card = document.getElementById(id);
    if (!card) return;
    card.classList.remove("health-card-ok", "health-card-warn", "health-card-bad", "health-card-unknown");
    if (ok === true) card.classList.add("health-card-ok");
    else if (ok === false) card.classList.add("health-card-bad");
    else card.classList.add("health-card-unknown");
    var status = card.querySelector(".health-card-status");
    if (status) status.textContent = message;
  }

  /* ---- Settings (delegated to OCESettings) ------------------------- */

  function refreshSettings() {
    var host = document.getElementById("settings-host");
    var sourceEl = document.getElementById("settings-source");
    var lockedEl = document.getElementById("settings-locked-keys");
    var secretsEl = document.getElementById("settings-secrets");
    var restartEl = document.getElementById("settings-restart-banner");
    Promise.all([
      api.config(),
      api.configSource(),
      api.configLockedKeys(),
      api.configSchema(),
      api.secretsList(),
      api.configRestartRequired(),
    ])
      .then(function (results) {
        var cfg = results[0];
        var source = results[1];
        var locked = results[2];
        var schema = results[3];
        var secrets = results[4];
        var restart = results[5];
        if (sourceEl) {
          if (source && source.exists && source.path) {
            sourceEl.textContent = "Loaded from: " + source.path;
          } else {
            sourceEl.textContent =
              "No config file found — running with built-in defaults.";
          }
        }
        if (window.OCESettings) {
          window.OCESettings.renderRestartBanner(restartEl, restart);
          window.OCESettings.renderLockedKeys(lockedEl, locked && locked.locked_keys);
          window.OCESettings.renderSecrets(secretsEl, secrets, refreshSettings);
          window.OCESettings.render(
            host, cfg, schema, locked && locked.locked_keys, refreshSettings
          );
        }
      })
      .catch(function (err) {
        if (host) host.textContent = "Failed to load settings: " + err.message;
      });
  }

  /* ---- expose toast for other modules ------------------------------ */

  window.OCEToast = toast;

  /* ---- init -------------------------------------------------------- */

  window.addEventListener("hashchange", navigate);
  window.addEventListener("DOMContentLoaded", function () {
    bindAdvancedMenu();
    bindDrawer();
    bindReviewQueueTabs();
    bindOfflineBadgeClick();
    refreshOfflineBadge();
    setInterval(refreshOfflineBadge, 30000);
    navigate();
    /* If the landing view is Process and there are running jobs,
       start polling immediately. */
    if ((parseHash().view) === "process") startActiveJobsPolling();
  });
})();
