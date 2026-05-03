/* Settings view — editable forms (Phase 13.5) on top of the
   read-only renderer first introduced in 13.1.

   Layout: one collapsible <details> per top-level section. Inside
   each, every leaf is rendered as a labelled input. A "Save section"
   button collects the diff (only inputs whose value differs from
   their original), runs POST /api/config/validate, and on ok runs
   PATCH /api/config. Validation errors render inline next to the
   button.

   Provider-shaped sections (ocr / pii / document_ai / llm) use a
   nested "Configure" expandable per provider so the operator can
   reach model_dir / min_confidence / endpoint_url etc. without
   touching config.yaml. Per-provider chain order is best edited via
   the Plugins page Enable/Disable toggle (Phase 13.4); this view
   shows the current chain for context but does not duplicate the
   reorder UI.

   Locked paths render as disabled inputs with a "locked" badge and
   the reason as a tooltip — visible but uneditable. */

(function (global) {
  "use strict";

  /* ---------- helpers ---------------------------------------------------- */

  function isPlainObject(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v);
  }

  function joinPath(parts) { return parts.filter(Boolean).join("."); }

  function setNestedPath(obj, dotted, value) {
    var parts = dotted.split(".");
    var node = obj;
    for (var i = 0; i < parts.length - 1; i++) {
      var key = parts[i];
      if (!isPlainObject(node[key])) node[key] = {};
      node = node[key];
    }
    node[parts[parts.length - 1]] = value;
  }

  function lockedRuleFor(path, lockedKeys) {
    if (!lockedKeys) return null;
    for (var i = 0; i < lockedKeys.length; i++) {
      if (lockedKeys[i].path === path) return lockedKeys[i];
    }
    return null;
  }

  /* Resolve a Pydantic $ref like "#/$defs/OfflineConfig" against the
     full schema. Returns the resolved schema fragment, or null. The
     leading "#" + separator are stripped via .substring rather than
     a regex literal — the frontend asset scanner forbids protocol-
     relative URL sequences in source files. */
  function resolveRef(rootSchema, fragment) {
    if (!fragment || typeof fragment !== "object") return fragment;
    if (!fragment.$ref || !rootSchema) return fragment;
    var ref = fragment.$ref;
    if (ref.charAt(0) === "#" && ref.charAt(1) === "/") ref = ref.substring(2);
    var parts = ref.split("/");
    var node = rootSchema;
    for (var i = 0; i < parts.length; i++) {
      if (!node || typeof node !== "object") return null;
      node = node[parts[i]];
    }
    return node;
  }

  /* ---------- input builders ------------------------------------------- */

  function makeInput(value, leafSchema) {
    var u = global.OCEUtils;
    var input;
    if (typeof value === "boolean") {
      input = u.el("input", { type: "checkbox" });
      if (value) input.checked = true;
    } else if (typeof value === "number") {
      input = u.el("input", { type: "number", step: "any" });
      input.value = String(value);
    } else if (Array.isArray(value)) {
      input = u.el("input", { type: "text" });
      input.value = value.join(", ");
      input.dataset.kind = "csv-list";
    } else if (value === null || value === undefined) {
      input = u.el("input", { type: "text" });
      input.value = "";
      if (leafSchema && leafSchema.type === "boolean") {
        input = u.el("input", { type: "checkbox" });
      } else if (leafSchema && (leafSchema.type === "number" || leafSchema.type === "integer")) {
        input = u.el("input", { type: "number", step: "any" });
      }
    } else {
      input = u.el("input", { type: "text" });
      input.value = String(value);
    }
    return input;
  }

  function readInput(input) {
    if (input.type === "checkbox") return !!input.checked;
    var raw = input.value;
    if (input.dataset && input.dataset.kind === "csv-list") {
      if (!raw.trim()) return [];
      return raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    }
    if (input.type === "number") {
      if (raw === "" || raw === null) return null;
      var n = Number(raw);
      return isNaN(n) ? raw : n;
    }
    return raw;
  }

  /* ---------- form rendering ------------------------------------------- */

  function renderLeafRow(host, leafKey, value, dottedPath, leafSchema, lockedKeys) {
    var u = global.OCEUtils;
    var row = u.el("div", { class: "settings-field" });
    var label = u.el("label", { class: "settings-field-label" });
    label.appendChild(u.el("code", { text: leafKey }));
    var lock = lockedRuleFor(dottedPath, lockedKeys);

    var input = makeInput(value, leafSchema);
    input.dataset.configPath = dottedPath;
    input.dataset.original = JSON.stringify(value);

    if (lock) {
      input.disabled = true;
      input.title = lock.reason;
      label.appendChild(u.el("span", {
        class: "badge badge-warn settings-locked-badge",
        text: "locked",
      }));
    }

    row.appendChild(label);
    row.appendChild(input);
    if (lock) {
      row.appendChild(u.el("p", {
        class: "settings-locked-reason small muted",
        text: lock.reason,
      }));
    }
    host.appendChild(row);
  }

  function renderObjectAsForm(host, obj, basePath, sectionSchema, lockedKeys, rootSchema) {
    var u = global.OCEUtils;
    if (!isPlainObject(obj)) return;
    var props = (sectionSchema && sectionSchema.properties) || {};
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      var path = joinPath([basePath, k]);
      var leafSchema = resolveRef(rootSchema, props[k]);
      if (Array.isArray(v) || !isPlainObject(v)) {
        renderLeafRow(host, k, v, path, leafSchema, lockedKeys);
      } else {
        /* Nested dict — render as an indented sub-form. */
        var sub = u.el("div", { class: "settings-subform" });
        sub.appendChild(u.el("h5", { text: k }));
        renderObjectAsForm(sub, v, path, leafSchema, lockedKeys, rootSchema);
        host.appendChild(sub);
      }
    });
  }

  /* ---------- save handler --------------------------------------------- */

  function collectDiff(formNode) {
    var inputs = formNode.querySelectorAll("input[data-config-path]");
    var patch = {};
    var anyChanged = false;
    inputs.forEach(function (input) {
      if (input.disabled) return;
      var current = readInput(input);
      var original;
      try {
        original = JSON.parse(input.dataset.original || "null");
      } catch (e) {
        original = null;
      }
      if (JSON.stringify(current) !== JSON.stringify(original)) {
        setNestedPath(patch, input.dataset.configPath, current);
        anyChanged = true;
      }
    });
    return anyChanged ? patch : null;
  }

  function describeError(err) {
    if (!err) return "request failed";
    if (err.message) return err.message;
    return JSON.stringify(err);
  }

  function applyPatch(form, statusEl, refresh) {
    var api = global.OCEApi;
    var patch = collectDiff(form);
    if (!patch) {
      statusEl.textContent = "Nothing to save in this section.";
      statusEl.className = "small muted settings-save-status";
      return;
    }
    statusEl.textContent = "validating…";
    statusEl.className = "small muted settings-save-status";
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
        statusEl.textContent = "saving…";
        return api.configPatch(patch);
      })
      .then(function (response) {
        statusEl.textContent =
          "saved (backup: " + (response.backup_path || "—") + ")";
        statusEl.className = "small settings-save-status settings-save-ok";
        if (typeof refresh === "function") refresh();
      })
      .catch(function (err) {
        statusEl.textContent = "error: " + describeError(err);
        statusEl.className = "small settings-save-status settings-save-err";
      });
  }

  /* ---------- per-section rendering ------------------------------------ */

  function renderSimpleSection(
    host, sectionKey, sectionData, sectionSchema, lockedKeys, rootSchema, refresh
  ) {
    var u = global.OCEUtils;
    var details = u.el("details", { class: "settings-section" });
    if (sectionKey === "offline" || sectionKey === "paths") details.open = true;
    var summary = u.el("summary");
    summary.appendChild(u.el("strong", { text: sectionKey.replace(/_/g, " ") }));
    summary.appendChild(u.el("span", {
      class: "muted small settings-section-key",
      text: " — " + sectionKey,
    }));
    details.appendChild(summary);

    var form = u.el("form", { class: "settings-form", autocomplete: "off" });
    form.addEventListener("submit", function (ev) { ev.preventDefault(); });

    renderObjectAsForm(form, sectionData, sectionKey, sectionSchema, lockedKeys, rootSchema);

    var btnRow = u.el("div", { class: "settings-btn-row" });
    var saveBtn = u.el("button", { type: "button", text: "Save changes in this section" });
    var status = u.el("span", { class: "small muted settings-save-status" });
    saveBtn.addEventListener("click", function () {
      applyPatch(form, status, refresh);
    });
    btnRow.appendChild(saveBtn);
    btnRow.appendChild(status);
    form.appendChild(btnRow);

    details.appendChild(form);
    host.appendChild(details);
  }

  function renderProviderSection(
    host, sectionKey, sectionData, sectionSchema, lockedKeys, rootSchema, refresh
  ) {
    var u = global.OCEUtils;
    var details = u.el("details", { class: "settings-section settings-providers" });
    var summary = u.el("summary");
    summary.appendChild(u.el("strong", { text: sectionKey.replace(/_/g, " ") }));
    summary.appendChild(u.el("span", {
      class: "muted small settings-section-key",
      text: " — " + sectionKey,
    }));
    details.appendChild(summary);

    var note = u.el("p", { class: "small muted" });
    note.textContent =
      "Enable / disable + chain order are best edited from the Plugins page. " +
      "This panel exposes per-provider config (model_dir, min_confidence, " +
      "endpoint_url, etc.). Each provider has its own Save button.";
    details.appendChild(note);

    if ("provider_chain" in sectionData) {
      var chainBlock = u.el("p", { class: "small" });
      chainBlock.appendChild(u.el("strong", { text: "Active chain: " }));
      chainBlock.appendChild(u.el("code", {
        text: (sectionData.provider_chain || []).join(" → ") || "(empty)",
      }));
      details.appendChild(chainBlock);
    }

    var providers = sectionData.providers || {};
    var providerSchema = (
      sectionSchema && sectionSchema.properties &&
      sectionSchema.properties.providers
    ) || null;
    Object.keys(providers).forEach(function (pname) {
      var providerCfg = providers[pname] || {};
      var pdetails = u.el("details", { class: "settings-provider" });
      var psummary = u.el("summary");
      psummary.appendChild(u.el("code", { text: pname }));
      var enabledChip = u.el("span", {
        class: "badge " + (providerCfg.enabled ? "badge-ok" : "badge-bad"),
        text: providerCfg.enabled ? "enabled" : "disabled",
      });
      psummary.appendChild(enabledChip);
      pdetails.appendChild(psummary);

      var pform = u.el("form", { class: "settings-form", autocomplete: "off" });
      pform.addEventListener("submit", function (ev) { ev.preventDefault(); });
      var basePath = sectionKey + ".providers." + pname;
      renderObjectAsForm(pform, providerCfg, basePath, null, lockedKeys, rootSchema);

      var btnRow = u.el("div", { class: "settings-btn-row" });
      var saveBtn = u.el("button", {
        type: "button",
        text: "Save " + pname + " config",
      });
      var status = u.el("span", { class: "small muted settings-save-status" });
      saveBtn.addEventListener("click", function () {
        applyPatch(pform, status, refresh);
      });
      btnRow.appendChild(saveBtn);
      btnRow.appendChild(status);
      pform.appendChild(btnRow);

      pdetails.appendChild(pform);
      details.appendChild(pdetails);
    });

    host.appendChild(details);
  }

  /* ---------- top-level renderer --------------------------------------- */

  var SIMPLE_SECTIONS = [
    "offline", "server", "paths",
    "template_detection", "extraction", "review",
    "export", "logging",
  ];
  var PROVIDER_SECTIONS = ["ocr", "document_ai", "pii", "llm"];

  function pathIsLocked(path, lockedKeys) {
    return lockedRuleFor(path, lockedKeys);
  }

  function renderLockedKeys(host, lockedKeys) {
    var u = global.OCEUtils;
    if (!host) return;
    u.clear(host);
    if (!lockedKeys || !lockedKeys.length) return;
    var box = u.el("div", { class: "locked-keys-box" });
    box.appendChild(u.el("h3", { text: "Locked settings" }));
    box.appendChild(u.el("p", {
      class: "small muted",
      text:
        "These keys cannot be changed from the GUI, the CLI, or even " +
        "by hand-editing config.yaml — they reflect non-negotiable " +
        "privacy and offline guarantees. The matching fields below " +
        "are disabled.",
    }));
    var ul = u.el("ul", { class: "locked-keys-list" });
    lockedKeys.forEach(function (rule) {
      var li = u.el("li");
      li.appendChild(u.el("code", { text: rule.path }));
      li.appendChild(u.el("span", {
        text: " must never be " + JSON.stringify(rule.forbidden_value) + ". ",
      }));
      li.appendChild(u.el("span", { class: "muted small", text: rule.reason }));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    host.appendChild(box);
  }

  function render(host, config, schema, lockedKeys, refresh) {
    var u = global.OCEUtils;
    if (!host) return;
    u.clear(host);
    if (!config || typeof config !== "object") {
      host.textContent = "No configuration to display.";
      return;
    }
    var rootSchema = schema || {};
    var sectionDefs = (rootSchema.properties) || {};

    var rendered = {};
    SIMPLE_SECTIONS.forEach(function (k) {
      if (k in config) {
        var sectionSchema = resolveRef(rootSchema, sectionDefs[k]);
        renderSimpleSection(
          host, k, config[k], sectionSchema, lockedKeys, rootSchema, refresh
        );
        rendered[k] = true;
      }
    });
    PROVIDER_SECTIONS.forEach(function (k) {
      if (k in config) {
        var sectionSchema = resolveRef(rootSchema, sectionDefs[k]);
        renderProviderSection(
          host, k, config[k], sectionSchema, lockedKeys, rootSchema, refresh
        );
        rendered[k] = true;
      }
    });
    Object.keys(config).forEach(function (k) {
      if (!rendered[k]) {
        var sectionSchema = resolveRef(rootSchema, sectionDefs[k]);
        renderSimpleSection(
          host, k, config[k], sectionSchema, lockedKeys, rootSchema, refresh
        );
      }
    });
  }

  /* ---------- secrets panel (Phase 13.6) ----------------------------- */

  function renderSecrets(host, payload, refresh) {
    var u = global.OCEUtils;
    var api = global.OCEApi;
    if (!host) return;
    u.clear(host);
    if (!payload) return;

    var details = u.el("details", { class: "settings-section settings-secrets-box" });
    details.open = true;
    var summary = u.el("summary");
    summary.appendChild(u.el("strong", { text: "Secrets" }));
    summary.appendChild(u.el("span", {
      class: "muted small settings-section-key",
      text: " — sidecar (chmod 600, never committed)",
    }));
    details.appendChild(summary);

    details.appendChild(u.el("p", {
      class: "small muted",
      text:
        "Cloud-LLM API keys live in " + (payload.secrets_path || "secrets.yaml") +
        ". The sidecar is read at startup; reference any stored " +
        "secret from a config field with the placeholder shown next " +
        "to its name.",
    }));

    var names = payload.names || [];
    if (!names.length) {
      details.appendChild(u.el("p", {
        class: "small muted",
        text: "No secrets stored yet.",
      }));
    } else {
      var ul = u.el("ul", { class: "settings-secrets-list" });
      names.forEach(function (name) {
        var li = u.el("li");
        li.appendChild(u.el("code", { text: name }));
        li.appendChild(u.el("span", {
          class: "muted small",
          text: "  →  ${secret:" + name + "}",
        }));
        var del = u.el("button", {
          type: "button",
          class: "plugin-toggle-btn plugin-toggle-disable",
          text: "Delete",
        });
        del.style.marginLeft = "0.5rem";
        del.addEventListener("click", function () {
          if (!global.confirm("Delete secret " + name + "?")) return;
          del.disabled = true;
          api.secretsDelete(name)
            .then(function () { if (typeof refresh === "function") refresh(); })
            .catch(function (err) {
              del.disabled = false;
              global.alert("Delete failed: " + err.message);
            });
        });
        li.appendChild(del);
        ul.appendChild(li);
      });
      details.appendChild(ul);
    }

    /* Add-secret form */
    var form = u.el("form", { class: "settings-form", autocomplete: "off" });
    form.addEventListener("submit", function (ev) { ev.preventDefault(); });
    var nameRow = u.el("div", { class: "settings-field" });
    nameRow.appendChild(u.el("label", { class: "settings-field-label", text: "name" }));
    var nameInput = u.el("input", {
      type: "text", placeholder: "e.g. OPENAI_API_KEY",
    });
    nameRow.appendChild(nameInput);
    form.appendChild(nameRow);

    var valRow = u.el("div", { class: "settings-field" });
    valRow.appendChild(u.el("label", { class: "settings-field-label", text: "value" }));
    var valInput = u.el("input", {
      type: "password", placeholder: "secret value",
    });
    valRow.appendChild(valInput);
    form.appendChild(valRow);

    var btnRow = u.el("div", { class: "settings-btn-row" });
    var setBtn = u.el("button", { type: "button", text: "Save secret" });
    var statusEl = u.el("span", { class: "small muted settings-save-status" });
    setBtn.addEventListener("click", function () {
      var name = (nameInput.value || "").trim();
      var value = valInput.value || "";
      if (!name || !value) {
        statusEl.textContent = "name and value are required";
        statusEl.className = "small settings-save-status settings-save-err";
        return;
      }
      setBtn.disabled = true;
      statusEl.textContent = "saving…";
      statusEl.className = "small muted settings-save-status";
      api.secretsSet(name, value)
        .then(function () {
          statusEl.textContent =
            "saved — placeholder ${secret:" + name + "} now resolves at startup";
          statusEl.className = "small settings-save-status settings-save-ok";
          nameInput.value = "";
          valInput.value = "";
          if (typeof refresh === "function") refresh();
        })
        .catch(function (err) {
          statusEl.textContent = "error: " + err.message;
          statusEl.className = "small settings-save-status settings-save-err";
          setBtn.disabled = false;
        });
    });
    btnRow.appendChild(setBtn);
    btnRow.appendChild(statusEl);
    form.appendChild(btnRow);

    details.appendChild(form);
    host.appendChild(details);
  }

  /* ---------- restart banner (Phase 13.7) ---------------------------- */

  function renderRestartBanner(host, payload) {
    var u = global.OCEUtils;
    if (!host) return;
    u.clear(host);
    if (!payload) return;

    if (payload.pending_restart === null) {
      var unknown = u.el("p", { class: "small muted" });
      unknown.textContent =
        "Boot binding unknown — server was started outside the CLI " +
        "(e.g., from a hand-rolled uvicorn invocation or a test).";
      host.appendChild(unknown);
      return;
    }
    if (!payload.pending_restart) return;

    var box = u.el("div", { class: "restart-banner" });
    box.appendChild(u.el("h3", { text: "Restart required" }));
    var paths = (payload.pending_changes || []).map(function (c) {
      return c.path;
    }).join(", ");
    box.appendChild(u.el("p", {
      class: "small",
      text:
        "The server is still bound to its boot values for: " + paths +
        ". Saved changes are on disk and will take effect the next " +
        "time you re-launch the CLI's serve command.",
    }));
    var ul = u.el("ul", { class: "restart-banner-list" });
    (payload.pending_changes || []).forEach(function (c) {
      var li = u.el("li");
      li.appendChild(u.el("code", { text: c.path }));
      li.appendChild(u.el("span", {
        text: ": booted as " + JSON.stringify(c.boot_value) +
          ", saved as " + JSON.stringify(c.current_value),
      }));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    host.appendChild(box);
  }

  global.OCESettings = {
    render: render,
    renderLockedKeys: renderLockedKeys,
    renderSecrets: renderSecrets,
    renderRestartBanner: renderRestartBanner,
    pathIsLocked: pathIsLocked,
  };
})(window);
