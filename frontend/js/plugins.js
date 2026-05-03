/* Plugins view — read-only inventory + per-row Enable / Disable
   toggle (Phase 13.4) + within-chain reorder.

   Toggle behaviour (unchanged):
   - Enable: set providers.<name>.enabled=true AND append <name> to
     provider_chain when not already present. Pre-flighted via
     POST /api/config/validate so policy violations and Pydantic
     errors surface inline before the PATCH.
   - Disable: set enabled=false AND remove <name> from
     provider_chain. Always allowed.

   Reorder behaviour (new):
   - Each in-chain provider gets up / down arrow buttons. A click
     sends a tiny patch swapping the provider with its neighbour,
     pre-flighted through the same /api/config/validate gate as
     enable / disable. Boundaries (first / last) disable the
     respective arrow.
   - Order semantics differ per section. The Plugins page surfaces
     this with section-specific help copy and (for OCR) explicit
     Primary / Fallback role labels:
       * OCR        — strict fallback. First non-failing provider
                      wins; later ones are skipped. Position 0 is the
                      "primary" extractor.
       * PII        — every provider runs; results merge. Order only
                      affects attribution / evidence ordering on
                      entities multiple detectors flag.
       * document_ai — every VLM runs; outputs become alternative
                      sources on each base word. Order = order of
                      alternative_sources entries in the manifest.
                      Image redaction never depends on VLM order.
   - Detection completeness, confidence, and the fail-closed gate
     are independent of within-chain order; this is documented in
     the per-section help. */

(function (global) {
  "use strict";

  /* ---------- generic cells ---------------------------------------------- */

  function statusCell(value) {
    var u = global.OCEUtils;
    if (value === true) {
      return u.el("td", null, [u.el("span", { class: "badge badge-ok", text: "yes" })]);
    }
    if (value === false) {
      return u.el("td", null, [u.el("span", { class: "badge badge-bad", text: "no" })]);
    }
    return u.el("td", null, [u.el("span", { class: "muted small", text: "n/a" })]);
  }

  function licenseCell(value) {
    var u = global.OCEUtils;
    if (value) {
      return u.el("td", null, [
        u.el("span", {
          class: "badge badge-warn",
          text: "review required",
        }),
      ]);
    }
    return u.el("td", null, [u.el("span", { class: "muted small", text: "—" })]);
  }

  /* Accuracy cell — headline number + tier badge. The tier badge is
     load-bearing: ranking is only meaningful within the same tier, so
     the UI must always show it next to the number. Per-entity
     breakdown surfaces as a tooltip. */
  function formatHeadline(metric, value) {
    if (value === null || value === undefined) return "—";
    if (typeof value !== "number" || isNaN(value)) return String(value);
    /* CER / WER are error rates: lower is better, render as percent.
       F1 / accuracy: 0–1 scale, render to 2 dp. */
    if (metric === "cer" || metric === "wer") {
      return (value * 100).toFixed(1) + "% " + metric.toUpperCase();
    }
    return value.toFixed(2);
  }

  function accuracyTooltip(a) {
    var lines = [];
    if (a.benchmark) {
      lines.push("Benchmark: " + a.benchmark +
        (a.benchmark_version ? " (" + a.benchmark_version + ")" : ""));
    }
    if (a.metric_name) lines.push("Metric: " + a.metric_name);
    if (a.per_entity && typeof a.per_entity === "object") {
      var keys = Object.keys(a.per_entity);
      if (keys.length) {
        lines.push("Per entity:");
        keys.forEach(function (k) {
          lines.push("  " + k + ": " + a.per_entity[k]);
        });
      }
    }
    if (a.notes) lines.push("Notes: " + a.notes);
    return lines.join("\n");
  }

  function accuracyCell(a) {
    var u = global.OCEUtils;
    var td = u.el("td", { class: "plugin-accuracy-cell" });
    if (!a || !a.tier) {
      td.appendChild(u.el("span", { class: "muted small", text: "—" }));
      return td;
    }
    td.appendChild(u.el("span", {
      class: "plugin-accuracy-headline",
      text: formatHeadline(a.metric_name, a.headline),
    }));
    var tierClass = "badge-tier-" + String(a.tier).toLowerCase();
    td.appendChild(u.el("span", {
      class: "badge " + tierClass,
      text: "Tier " + a.tier,
    }));
    var tip = accuracyTooltip(a);
    if (tip) td.title = tip;
    return td;
  }

  /* ---------- per-section copy ------------------------------------------ */

  /* Differentiated role label per section. OCR's chain order is a hard
     priority (first success wins), so the labels are meaningful. PII /
     VLM order is positional only — we surface a number, not a role. */
  function chainRoleLabel(sectionKey, position) {
    if (sectionKey === "ocr") {
      if (position === 0) return "Primary";
      return "Fallback " + position;
    }
    return "#" + (position + 1);
  }

  function chainRoleClass(sectionKey, position) {
    if (sectionKey === "ocr" && position === 0) return "badge-ok";
    if (sectionKey === "ocr") return "badge-warn";
    return "badge-ok";
  }

  function orderHelpFor(sectionKey) {
    if (sectionKey === "ocr") {
      return (
        "Order matters here. The pipeline tries providers top-to-bottom; " +
        "the first one whose extraction succeeds is the one CARE uses, " +
        "and later providers are skipped. The first row is the " +
        "\"Primary\" extractor; the rest are fallbacks for hard exceptions. " +
        "Order changes do not require a server restart — every new " +
        "processing run reads the chain fresh."
      );
    }
    if (sectionKey === "pii") {
      return (
        "All enabled detectors run on every page and the narrative; " +
        "results are merged. Reordering does NOT change detection " +
        "completeness or confidence — those are order-independent. It " +
        "does change which provider is credited as the primary source " +
        "on entities multiple detectors flag, and the order of evidence " +
        "in the manifest's \"sources\" list. Order changes do not " +
        "require a server restart."
      );
    }
    if (sectionKey === "document_ai") {
      return (
        "All enabled VLM / document-AI providers run; each one's output " +
        "becomes an alternative source on each base word. Reordering " +
        "changes the order of \"alternative_sources\" entries in the " +
        "report manifest. It does not affect image redaction — the " +
        "redactor only uses base (non-generative) word bboxes, never " +
        "VLM-only text. Order changes do not require a server restart."
      );
    }
    return "";
  }

  /* ---------- enable / disable (unchanged behaviour) -------------------- */

  function enableGuardReason(p) {
    if (p.model_files_present === false) {
      return "Model files missing — fill in model_dir on the Settings page first.";
    }
    if (p.requires_network) {
      return "Network-requiring provider — adjust offline / egress settings first.";
    }
    return null;
  }

  function buildEnablePatch(sectionKey, providerName, enabled, currentChain) {
    var nextChain = (currentChain || []).slice();
    if (enabled) {
      if (nextChain.indexOf(providerName) === -1) nextChain.push(providerName);
    } else {
      nextChain = nextChain.filter(function (n) { return n !== providerName; });
    }
    var patch = {};
    patch[sectionKey] = {
      provider_chain: nextChain,
      providers: {},
    };
    patch[sectionKey].providers[providerName] = { enabled: enabled };
    return patch;
  }

  function buildReorderPatch(sectionKey, currentChain, fromIdx, toIdx) {
    var nextChain = (currentChain || []).slice();
    if (toIdx < 0 || toIdx >= nextChain.length) return null;
    if (fromIdx === toIdx) return null;
    var moved = nextChain.splice(fromIdx, 1)[0];
    nextChain.splice(toIdx, 0, moved);
    var patch = {};
    patch[sectionKey] = { provider_chain: nextChain };
    return patch;
  }

  function describeError(err) {
    if (!err) return "request failed";
    if (typeof err === "string") return err;
    if (err.message) return err.message;
    return JSON.stringify(err);
  }

  /* Single point of validate-then-PATCH for both enable/disable AND
     reorder, so error handling stays consistent. */
  function applyPatch(opts) {
    var api = global.OCEApi;
    var btn = opts.btn;
    var statusEl = opts.statusEl;
    var refresh = opts.refresh;
    var statusBefore = opts.statusBefore || "saving";
    var statusAfter = opts.statusAfter || "saved";

    if (btn) btn.disabled = true;
    if (statusEl) {
      statusEl.textContent = statusBefore + "…";
      statusEl.className = "small muted plugin-toggle-status";
    }

    api.configValidate(opts.patch)
      .then(function (validation) {
        if (!validation.ok) {
          var msgs = []
            .concat(validation.governance_errors || [])
            .concat((validation.pydantic_errors || []).map(function (e) {
              return e.loc.join(".") + ": " + e.msg;
            }));
          throw new Error(msgs.join(" | ") || "validation failed");
        }
        return api.configPatch(opts.patch);
      })
      .then(function () {
        if (statusEl) {
          statusEl.textContent = statusAfter;
          statusEl.className = "small plugin-toggle-status plugin-toggle-ok";
        }
        if (typeof refresh === "function") refresh();
      })
      .catch(function (err) {
        if (statusEl) {
          statusEl.textContent = "error: " + describeError(err);
          statusEl.className = "small plugin-toggle-status plugin-toggle-err";
        }
        if (btn) btn.disabled = false;
      });
  }

  function toggleCell(p, sectionKey, chain, refresh) {
    var u = global.OCEUtils;
    var td = u.el("td", { class: "plugin-toggle-cell" });
    var statusEl = u.el("span", { class: "small muted plugin-toggle-status" });

    var btn;
    if (p.enabled) {
      btn = u.el("button", {
        type: "button",
        class: "plugin-toggle-btn plugin-toggle-disable",
        text: "Disable",
      });
      btn.addEventListener("click", function () {
        applyPatch({
          patch: buildEnablePatch(sectionKey, p.name, false, chain),
          btn: btn,
          statusEl: statusEl,
          refresh: refresh,
          statusBefore: "disabling " + p.name,
          statusAfter: "disabled",
        });
      });
    } else {
      var reason = enableGuardReason(p);
      btn = u.el("button", {
        type: "button",
        class: "plugin-toggle-btn plugin-toggle-enable",
        text: "Enable",
      });
      if (reason) {
        btn.disabled = true;
        btn.title = reason;
      }
      btn.addEventListener("click", function () {
        applyPatch({
          patch: buildEnablePatch(sectionKey, p.name, true, chain),
          btn: btn,
          statusEl: statusEl,
          refresh: refresh,
          statusBefore: "enabling " + p.name,
          statusAfter: "enabled",
        });
      });
    }
    td.appendChild(btn);
    td.appendChild(statusEl);
    return td;
  }

  /* ---------- chain order cell ----------------------------------------- */

  function chainOrderCell(p, sectionKey, chain, refresh) {
    var u = global.OCEUtils;
    var td = u.el("td", { class: "plugin-order-cell" });
    if (!p.in_active_chain) {
      td.appendChild(u.el("span", { class: "muted small", text: "—" }));
      return td;
    }

    var idx = (chain || []).indexOf(p.name);
    var label = chainRoleLabel(sectionKey, idx);
    var badge = u.el("span", {
      class: "badge " + chainRoleClass(sectionKey, idx),
      text: label,
    });
    td.appendChild(badge);

    var arrowGroup = u.el("span", { class: "plugin-order-arrows" });
    var statusEl = u.el("span", { class: "small muted plugin-order-status" });

    var upBtn = u.el("button", {
      type: "button",
      class: "plugin-order-btn",
      "aria-label": "Move " + p.name + " up",
      text: "▲",
    });
    var downBtn = u.el("button", {
      type: "button",
      class: "plugin-order-btn",
      "aria-label": "Move " + p.name + " down",
      text: "▼",
    });

    if (idx === 0) {
      upBtn.disabled = true;
      upBtn.title = "Already at the top of the chain.";
    } else {
      upBtn.title = "Move " + p.name + " up — becomes step " + idx +
        (sectionKey === "ocr" && idx === 1 ? " (Primary)." : ".");
    }

    if (idx === (chain || []).length - 1) {
      downBtn.disabled = true;
      downBtn.title = "Already at the bottom of the chain.";
    } else {
      downBtn.title = "Move " + p.name + " down — becomes step " + (idx + 2) + ".";
    }

    upBtn.addEventListener("click", function () {
      var patch = buildReorderPatch(sectionKey, chain, idx, idx - 1);
      if (!patch) return;
      applyPatch({
        patch: patch,
        btn: upBtn,
        statusEl: statusEl,
        refresh: refresh,
        statusBefore: "moving " + p.name + " up",
        statusAfter: "moved",
      });
    });

    downBtn.addEventListener("click", function () {
      var patch = buildReorderPatch(sectionKey, chain, idx, idx + 1);
      if (!patch) return;
      applyPatch({
        patch: patch,
        btn: downBtn,
        statusEl: statusEl,
        refresh: refresh,
        statusBefore: "moving " + p.name + " down",
        statusAfter: "moved",
      });
    });

    arrowGroup.appendChild(upBtn);
    arrowGroup.appendChild(downBtn);
    td.appendChild(arrowGroup);
    td.appendChild(statusEl);
    return td;
  }

  /* ---------- table render --------------------------------------------- */

  function renderTable(host, title, payload, sectionKey, refresh) {
    var u = global.OCEUtils;
    var chain = payload.active_chain || [];
    var head = u.el("thead", null, [
      u.el("tr", null, [
        u.el("th", { text: "Provider" }),
        u.el("th", { text: "Type" }),
        u.el("th", { text: "Default" }),
        u.el("th", { text: "Accuracy", title: "Hover the cell for benchmark, metric, and per-entity breakdown. Tier A = project-run benchmark, B = published in-domain, C = vendor / unverified. Rankings are only meaningful within the same tier." }),
        u.el("th", { text: "Enabled" }),
        u.el("th", { text: "Position / order" }),
        u.el("th", { text: "Model files" }),
        u.el("th", { text: "License" }),
        u.el("th", { text: "Network" }),
        u.el("th", { text: "Generative" }),
        u.el("th", { text: "Action" }),
      ]),
    ]);

    var tbody = u.el("tbody");
    payload.providers.forEach(function (p) {
      var nameCell = u.el("td", null, [u.el("code", { text: p.name })]);
      if (/^mock_/i.test(p.name)) {
        nameCell.appendChild(u.el("span", {
          class: "badge badge-warn plugin-mock-badge",
          text: "mock",
        }));
      }
      tbody.appendChild(u.el("tr", null, [
        nameCell,
        u.el("td", { text: p.provider_type }),
        u.el("td", { text: p.enabled_by_default ? "yes" : "no" }),
        accuracyCell(p.accuracy),
        statusCell(!!p.enabled),
        chainOrderCell(p, sectionKey, chain, refresh),
        statusCell(p.model_files_present),
        licenseCell(!!p.license_review_required),
        u.el("td", { text: p.requires_network ? "yes" : "no" }),
        u.el("td", { text: p.generative_model ? "yes" : "no" }),
        toggleCell(p, sectionKey, chain, refresh),
      ]));
    });
    var table = u.el("table", { class: "data-table plugin-table" });
    table.appendChild(head);
    table.appendChild(tbody);

    /* Pretty chain summary at the top, with role labels for OCR. */
    var chainPieces = chain.map(function (n, i) {
      return n + " (" + chainRoleLabel(sectionKey, i) + ")";
    });
    var chainText = (chainPieces.length ? chainPieces.join(" → ") : "(empty)") +
      (payload.enabled === false ? " (section disabled)" : "");

    var help = u.el("details", { class: "plugins-help" }, [
      u.el("summary", { text: "What does Enable / Disable do?" }),
      u.el("p", {
        class: "small muted",
        text:
          "Enable sets providers." + sectionKey +
          ".<name>.enabled=true and appends the name to " + sectionKey +
          ".provider_chain. Disable does the inverse. Both are " +
          "validated server-side first, so a locked-setting flip or " +
          "a missing model file is rejected before any write. " +
          "config.yaml is updated in place with comments preserved.",
      }),
    ]);

    var orderHelp = u.el("details", { class: "plugins-help" }, [
      u.el("summary", { text: "What does the chain order mean here?" }),
      u.el("p", { class: "small muted", text: orderHelpFor(sectionKey) }),
    ]);

    var section = u.el("section", { class: "plugins-section" }, [
      u.el("h3", { text: title }),
      u.el("p", {
        class: "muted small",
        text: "Active chain: " + chainText,
      }),
      table,
      help,
      orderHelp,
    ]);
    host.appendChild(section);
  }

  function render(host, payload, refresh) {
    var u = global.OCEUtils;
    u.clear(host);

    var legend = u.el("p", { class: "small muted plugins-legend" }, [
      u.el("span", { text: "Legend — " }),
      u.el("span", { class: "badge badge-ok", text: "yes" }),
      u.el("span", { text: " configured / installed,  " }),
      u.el("span", { class: "badge badge-bad", text: "no" }),
      u.el("span", { text: " missing,  " }),
      u.el("span", { class: "muted small", text: "n/a" }),
      u.el("span", { text: " not applicable. " }),
      u.el("span", { class: "badge badge-ok", text: "Primary" }),
      u.el("span", {
        text: " / ",
      }),
      u.el("span", { class: "badge badge-warn", text: "Fallback N" }),
      u.el("span", {
        text:
          " mark OCR chain priority; for PII and document_ai the " +
          "position number (#1, #2, …) is positional only. ",
      }),
      u.el("span", { class: "badge badge-tier-a", text: "Tier A" }),
      u.el("span", { text: " project benchmark, " }),
      u.el("span", { class: "badge badge-tier-b", text: "Tier B" }),
      u.el("span", { text: " published in-domain, " }),
      u.el("span", { class: "badge badge-tier-c", text: "Tier C" }),
      u.el("span", {
        text:
          " vendor / unverified — rankings only meaningful within the " +
          "same tier. Hover the Accuracy cell for per-entity numbers.",
      }),
    ]);
    host.appendChild(legend);

    renderTable(host, "OCR providers", payload.ocr, "ocr", refresh);
    renderTable(host, "Document-AI / VLM providers", payload.document_ai, "document_ai", refresh);
    renderTable(host, "PII providers", payload.pii, "pii", refresh);
  }

  global.OCEPlugins = { render: render };
})(window);
