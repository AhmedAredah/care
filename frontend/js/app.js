/* care — main UI controller.
   Local-only; every fetch hits /api/* on this same origin. */

(function () {
  "use strict";

  var u = window.OCEUtils;
  var api = window.OCEApi;

  var VIEWS = ["dashboard", "jobs", "reports", "report-detail", "exports", "plugins", "offline", "settings", "template-builder"];
  var builderInited = false;

  function showView(name, params) {
    VIEWS.forEach(function (v) {
      var node = document.getElementById("view-" + v);
      if (!node) return;
      if (v === name) u.show(node); else u.hide(node);
    });
    document.querySelectorAll("nav a").forEach(function (a) {
      a.classList.toggle("active", a.dataset.view === name);
    });
    if (name === "dashboard") refreshDashboard();
    if (name === "jobs") refreshJobs();
    if (name === "reports") refreshReports();
    if (name === "report-detail") openReport(params && params.report_id);
    if (name === "exports") refreshExports();
    if (name === "plugins") refreshPlugins();
    if (name === "offline") refreshOffline();
    if (name === "settings") refreshSettings();
    if (name === "template-builder") {
      if (!builderInited && window.OCEBuilder) {
        window.OCEBuilder.init();
        builderInited = true;
      }
    }
  }

  function parseHash() {
    var hash = (window.location.hash || "").replace(/^#/, "");
    var parts = hash.split("/");
    if (parts[0] === "report" && parts[1]) {
      return { view: "report-detail", report_id: parts[1] };
    }
    return { view: parts[0] || "dashboard" };
  }

  function navigate() {
    var p = parseHash();
    showView(p.view, p);
  }

  /* ---- dashboard --------------------------------------------------- */

  function refreshDashboard() {
    Promise.all([api.listJobs(), api.listExports()]).then(function (results) {
      var jobs = results[0].jobs || [];
      var exportsList = results[1].reports || [];
      setCount("jobs", jobs.length);
      setCount("reports", exportsList.length);
    }).catch(function () { /* tolerate transient failures */ });
  }

  function setCount(name, value) {
    document.querySelectorAll('[data-count="' + name + '"]').forEach(function (n) {
      n.textContent = String(value);
    });
  }

  document.addEventListener("submit", function (event) {
    if (event.target && event.target.id === "submit-job-form") {
      event.preventDefault();
      var input = u.cleanPath(document.getElementById("input-dir").value);
      var jurisdiction = (document.getElementById("job-jurisdiction").value || "").trim();
      var rawIds = (document.getElementById("job-template-ids").value || "").trim();
      var templateIds = rawIds
        ? rawIds.split(",").map(function (s) { return s.trim(); }).filter(Boolean)
        : [];
      var resultBox = document.getElementById("submit-job-result");
      api.submitJob(input, { jurisdiction: jurisdiction, templateIds: templateIds })
        .then(function (job) {
          resultBox.textContent = JSON.stringify(job, null, 2);
          u.show(resultBox);
          refreshDashboard();
        })
        .catch(function (err) {
          resultBox.textContent = "error: " + err.message;
          u.show(resultBox);
        });
    }
  });

  /* ---- jobs ------------------------------------------------------- */

  function refreshJobs() {
    var tbody = document.getElementById("jobs-tbody");
    api.listJobs().then(function (data) {
      u.clear(tbody);
      (data.jobs || []).forEach(function (j) {
        var reportLinks = (j.report_ids || []).map(function (r) {
          return u.el("a", { href: "#report/" + r, text: r });
        });
        var row = u.el("tr", null, [
          u.el("td", { text: j.job_id }),
          u.el("td", { text: j.status }),
          u.el("td", { text: j.submitted_at }),
          u.el("td", null, reportLinks.length ? reportLinks : [document.createTextNode("—")]),
          u.el("td", null, [u.el("a", { href: "#jobs", text: "refresh" })]),
        ]);
        tbody.appendChild(row);
      });
    });
  }

  /* ---- report list ------------------------------------------------ */

  function refreshReports() {
    var tbody = document.getElementById("reports-tbody");
    api.listExports().then(function (exportsList) {
      u.clear(tbody);
      var ids = (exportsList.reports || []).map(function (r) { return r.report_id; });
      Promise.all(ids.map(function (id) {
        return api.getReport(id).catch(function () { return null; });
      })).then(function (views) {
        views.forEach(function (v) {
          if (!v) return;
          tbody.appendChild(reportRow(v));
        });
      });
    });
  }

  function reportRow(v) {
    var decisionBadge = u.el("span", {
      class: "badge " + (v.qa_export_blocked ? "badge-bad" : "badge-ok"),
      text: v.qa_decision,
    });
    var reviewBadge = u.el("span", {
      class: "badge " + (
        v.review.decision === "APPROVED" ? "badge-ok" :
        v.review.decision === "REJECTED" ? "badge-bad" : "badge-warn"
      ),
      text: v.review.decision,
    });
    var flagsCell = u.el("td", null,
      (v.qa_flags || []).slice(0, 4).map(function (f) {
        return u.el("span", { class: "badge badge-warn", text: f });
      })
    );
    return u.el("tr", null, [
      u.el("td", { text: v.report_id }),
      u.el("td", { text: v.template_id + " (" + u.fmtPct(v.template_confidence) + ")" }),
      u.el("td", null, [decisionBadge]),
      u.el("td", null, [reviewBadge]),
      flagsCell,
      u.el("td", null, [u.el("a", { href: "#report/" + v.report_id, text: "view →" })]),
    ]);
  }

  /* ---- report detail ---------------------------------------------- */

  function openReport(reportId) {
    if (!reportId || !/^[0-9a-f]{16}$/.test(reportId)) {
      document.getElementById("report-detail-title").textContent = "Invalid report id";
      return;
    }
    document.getElementById("report-detail-title").textContent = "Report " + u.shortId(reportId);
    api.getReport(reportId).then(function (v) { renderReport(reportId, v); });
  }

  function renderReport(reportId, v) {
    var meta = document.getElementById("report-meta");
    u.clear(meta);
    var rows = [
      ["Template", v.template_id],
      ["Template confidence", u.fmtPct(v.template_confidence)],
      ["Diagram confidence", u.fmtPct(v.diagram_confidence)],
      ["Narrative confidence", u.fmtPct(v.narrative_confidence)],
      ["Text source", v.text_source],
      ["OCR provider used", v.ocr_provider_used || "—"],
      ["Decision", v.qa_decision],
      ["Review", v.review.decision],
      ["PII entities", String(v.qa_pii_entity_count)],
      ["PII unmapped", String(v.qa_pii_unmapped_count)],
    ];
    rows.forEach(function (pair) {
      meta.appendChild(u.el("dt", { text: pair[0] }));
      meta.appendChild(u.el("dd", { text: pair[1] }));
    });

    var flags = document.getElementById("report-qa-flags");
    u.clear(flags);
    (v.qa_flags || []).forEach(function (f) {
      var li = u.el("li", { text: f });
      if (f === "VLM_OUTPUT_CONFLICTS_WITH_OCR" || f === "PII_UNMAPPED" || f === "TEMPLATE_UNKNOWN") {
        li.classList.add("flag-block");
      }
      flags.appendChild(li);
    });
    var blockHost = document.getElementById("report-blocking-reasons");
    u.clear(blockHost);
    if (v.qa_export_blocked) {
      blockHost.appendChild(u.el("p", { text: "Export blocked. Reasons:" }));
      var ul = u.el("ul");
      (v.qa_blocking_reasons || []).forEach(function (r) {
        ul.appendChild(u.el("li", { text: r }));
      });
      blockHost.appendChild(ul);
    }

    var diagramImg = document.getElementById("diagram-preview");
    var diagramStatus = document.getElementById("diagram-status");
    if (v.qa_export_blocked) {
      diagramImg.removeAttribute("src");
      diagramStatus.textContent = "Diagram preview unavailable — export was blocked by the QA gate.";
    } else {
      diagramImg.src = api.diagramUrl(reportId);
      diagramStatus.textContent = "Redacted page crop. Original PDFs are never served.";
    }

    var narrativeBox = document.getElementById("narrative-text");
    var piiList = document.getElementById("pii-highlights");
    u.clear(piiList);
    narrativeBox.textContent = "";
    if (v.qa_export_blocked) {
      narrativeBox.textContent = "(narrative unavailable — export blocked)";
    } else {
      api.getReportNarrative(reportId).then(function (payload) {
        narrativeBox.textContent = payload.text || "";
        (payload.entities_redacted || []).forEach(function (e) {
          piiList.appendChild(u.el("li", {
            text: e.entity_type + " — provider: " + (e.provider || "?") +
                  " — offsets: " + (e.start_offset || "?") + "..." + (e.end_offset || "?")
          }));
        });
      }).catch(function (err) {
        narrativeBox.textContent = "(error loading narrative: " + err.message + ")";
      });
    }

    var approve = document.getElementById("approve-btn");
    approve.disabled = !!v.qa_export_blocked;
    if (window.OCEReview) window.OCEReview.bind(reportId);
  }

  /* ---- exports ---------------------------------------------------- */

  function refreshExports() {
    var tbody = document.getElementById("exports-tbody");
    api.listExports().then(function (data) {
      u.clear(tbody);
      (data.reports || []).forEach(function (r) {
        tbody.appendChild(u.el("tr", null, [
          u.el("td", null, [u.el("a", { href: "#report/" + r.report_id, text: r.report_id })]),
          u.el("td", { text: (r.files || []).join(", ") }),
        ]));
      });
    });
  }

  /* ---- plugins ---------------------------------------------------- */

  function refreshPlugins() {
    var host = document.getElementById("plugins-host");
    api.plugins().then(function (data) {
      window.OCEPlugins.render(host, data, refreshPlugins);
    });
  }

  /* ---- settings (Phase 13.1 — read-only) -------------------------- */

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

  /* ---- offline ---------------------------------------------------- */

  function refreshOffline() {
    var box = document.getElementById("offline-detail");
    api.offline().then(function (data) {
      box.textContent = JSON.stringify(data, null, 2);
      var badge = document.getElementById("offline-badge");
      var ok = data.offline_guard_enabled && data.offline_config_enabled;
      u.setBadge(badge, ok ? "ok" : "warn", ok ? "offline" : "online?");
    });
  }

  /* ---- init ------------------------------------------------------- */

  window.addEventListener("hashchange", navigate);
  window.addEventListener("DOMContentLoaded", function () {
    refreshOffline();
    navigate();
  });
})();
