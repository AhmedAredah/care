/* Plugins view rendering — read-only inventory + per-row enable
   toggle (Phase 13.4).

   Toggle behaviour:
   - Enable: set providers.<name>.enabled=true AND append <name> to
     provider_chain when not already present. Pre-flighted via
     POST /api/config/validate so policy violations and Pydantic
     errors surface inline before the PATCH.
   - Disable: set enabled=false AND remove <name> from
     provider_chain. Always allowed.
   - The button is disabled when a guard would refuse the enable —
     missing model files, or a network-requiring provider with the
     offline guard on. The tooltip explains why.

   This page never edits the per-provider config dict beyond the two
   fields above; deeper edits (model_dir, label_map, api_key) belong
   to the Settings form in Phase 13.5. */

(function (global) {
  "use strict";

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

  function chainPositionCell(name, chain, inChain) {
    var u = global.OCEUtils;
    if (!inChain) {
      return u.el("td", null, [u.el("span", { class: "muted small", text: "—" })]);
    }
    var idx = (chain || []).indexOf(name);
    var label = idx >= 0 ? "step " + (idx + 1) : "yes";
    return u.el("td", null, [
      u.el("span", { class: "badge badge-ok", text: label }),
    ]);
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

  /* Decide whether enabling this provider is safe to attempt without
     a deeper config edit. Returns null when OK, otherwise a short
     human-readable reason. */
  function enableGuardReason(p) {
    if (p.model_files_present === false) {
      return "Model files missing — fill in model_dir on the Settings page first.";
    }
    if (p.requires_network) {
      return "Network-requiring provider — adjust offline / egress settings first.";
    }
    return null;
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
        applyToggle({
          sectionKey: sectionKey,
          providerName: p.name,
          enabled: false,
          chain: chain,
          btn: btn,
          statusEl: statusEl,
          refresh: refresh,
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
        applyToggle({
          sectionKey: sectionKey,
          providerName: p.name,
          enabled: true,
          chain: chain,
          btn: btn,
          statusEl: statusEl,
          refresh: refresh,
        });
      });
    }
    td.appendChild(btn);
    td.appendChild(statusEl);
    return td;
  }

  function buildPatch(sectionKey, providerName, enabled, currentChain) {
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

  function describeError(err) {
    if (!err) return "request failed";
    if (typeof err === "string") return err;
    if (err.message) return err.message;
    return JSON.stringify(err);
  }

  function applyToggle(opts) {
    var u = global.OCEUtils;
    var api = global.OCEApi;
    var btn = opts.btn;
    var statusEl = opts.statusEl;
    var patch = buildPatch(
      opts.sectionKey, opts.providerName, opts.enabled, opts.chain
    );

    btn.disabled = true;
    statusEl.textContent =
      (opts.enabled ? "enabling " : "disabling ") + opts.providerName + "…";
    statusEl.className = "small muted plugin-toggle-status";

    api.configValidate(patch)
      .then(function (validation) {
        if (!validation.ok) {
          var msgs = []
            .concat(validation.governance_errors || [])
            .concat((validation.pydantic_errors || []).map(function (e) {
              return e.loc.join(".") + ": " + e.msg;
            }));
          throw new Error(msgs.join(" | ") || "validation failed");
        }
        return api.configPatch(patch);
      })
      .then(function () {
        statusEl.textContent =
          opts.enabled ? "enabled" : "disabled";
        statusEl.className = "small plugin-toggle-status plugin-toggle-ok";
        if (typeof opts.refresh === "function") opts.refresh();
      })
      .catch(function (err) {
        statusEl.textContent = "error: " + describeError(err);
        statusEl.className = "small plugin-toggle-status plugin-toggle-err";
        btn.disabled = false;
      });
  }

  function renderTable(host, title, payload, sectionKey, refresh) {
    var u = global.OCEUtils;
    var chain = payload.active_chain || [];
    var head = u.el("thead", null, [
      u.el("tr", null, [
        u.el("th", { text: "Provider" }),
        u.el("th", { text: "Type" }),
        u.el("th", { text: "Default" }),
        u.el("th", { text: "Enabled" }),
        u.el("th", { text: "In chain" }),
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
        statusCell(!!p.enabled),
        chainPositionCell(p.name, chain, !!p.in_active_chain),
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

    var chainText = (chain.length ? chain.join(" → ") : "(empty)") +
      (payload.enabled === false ? " (section disabled)" : "");

    var details = u.el("details", { class: "plugins-help" }, [
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

    var section = u.el("section", { class: "plugins-section" }, [
      u.el("h3", { text: title }),
      u.el("p", {
        class: "muted small",
        text: "Active chain: " + chainText,
      }),
      table,
      details,
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
      u.el("span", { text: " not applicable." }),
    ]);
    host.appendChild(legend);

    renderTable(host, "OCR providers", payload.ocr, "ocr", refresh);
    renderTable(host, "Document-AI / VLM providers", payload.document_ai, "document_ai", refresh);
    renderTable(host, "PII providers", payload.pii, "pii", refresh);
  }

  global.OCEPlugins = { render: render };
})(window);
