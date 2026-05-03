/* API client — local-only. Never targets a non-loopback host. */

(function (global) {
  "use strict";

  var BASE = "/api";

  function reject(message) {
    return Promise.reject(new Error(message));
  }

  function jsonOrThrow(response) {
    if (!response.ok) {
      return response.text().then(function (body) {
        throw new Error(
          "HTTP " + response.status + ": " + (body || response.statusText)
        );
      });
    }
    return response.json();
  }

  function safeReportId(reportId) {
    if (!/^[0-9a-f]{16}$/.test(String(reportId))) {
      return null;
    }
    return reportId;
  }

  var API = {
    health: function () {
      return fetch(BASE + "/health").then(jsonOrThrow);
    },
    offline: function () {
      return fetch(BASE + "/offline/status").then(jsonOrThrow);
    },
    plugins: function () {
      return fetch(BASE + "/plugins").then(jsonOrThrow);
    },
    config: function () {
      return fetch(BASE + "/config").then(jsonOrThrow);
    },
    configSchema: function () {
      return fetch(BASE + "/config/schema").then(jsonOrThrow);
    },
    configSource: function () {
      return fetch(BASE + "/config/source").then(jsonOrThrow);
    },
    configLockedKeys: function () {
      return fetch(BASE + "/config/locked-keys").then(jsonOrThrow);
    },
    configValidate: function (patch) {
      return fetch(BASE + "/config/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch || {}),
      }).then(jsonOrThrow);
    },
    configPatch: function (patch) {
      return fetch(BASE + "/config", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch || {}),
      }).then(jsonOrThrow);
    },
    secretsList: function () {
      return fetch(BASE + "/config/secrets").then(jsonOrThrow);
    },
    secretsSet: function (name, value) {
      return fetch(BASE + "/config/secrets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, value: value }),
      }).then(jsonOrThrow);
    },
    secretsDelete: function (name) {
      return fetch(
        BASE + "/config/secrets/" + encodeURIComponent(name),
        { method: "DELETE" }
      ).then(function (response) {
        if (!response.ok) {
          return response.text().then(function (body) {
            throw new Error("HTTP " + response.status + ": " + body);
          });
        }
        return { ok: true };
      });
    },
    secretsDeriveName: function (path) {
      var url = BASE + "/config/secrets/derive-name?path=" +
        encodeURIComponent(path);
      return fetch(url).then(jsonOrThrow);
    },
    configRestartRequired: function () {
      return fetch(BASE + "/config/restart-required").then(jsonOrThrow);
    },
    submitJob: function (inputDir, options) {
      var payload = { input_dir: inputDir };
      var opts = options || {};
      if (opts.jurisdiction) payload.jurisdiction = opts.jurisdiction;
      if (opts.templateIds && opts.templateIds.length) payload.template_ids = opts.templateIds;
      return fetch(BASE + "/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(jsonOrThrow);
    },
    listJobs: function () {
      return fetch(BASE + "/jobs").then(jsonOrThrow);
    },
    getJob: function (jobId) {
      return fetch(BASE + "/jobs/" + encodeURIComponent(jobId)).then(jsonOrThrow);
    },
    getReport: function (reportId) {
      var id = safeReportId(reportId);
      if (!id) return reject("invalid report id");
      return fetch(BASE + "/reports/" + id).then(jsonOrThrow);
    },
    getReportQa: function (reportId) {
      var id = safeReportId(reportId);
      if (!id) return reject("invalid report id");
      return fetch(BASE + "/reports/" + id + "/qa").then(jsonOrThrow);
    },
    getReportManifest: function (reportId) {
      var id = safeReportId(reportId);
      if (!id) return reject("invalid report id");
      return fetch(BASE + "/reports/" + id + "/manifest").then(jsonOrThrow);
    },
    getReportNarrative: function (reportId) {
      var id = safeReportId(reportId);
      if (!id) return reject("invalid report id");
      return fetch(BASE + "/reports/" + id + "/narrative").then(jsonOrThrow);
    },
    diagramUrl: function (reportId) {
      var id = safeReportId(reportId);
      if (!id) return null;
      return BASE + "/reports/" + id + "/diagram";
    },
    approve: function (reportId, body) {
      var id = safeReportId(reportId);
      if (!id) return reject("invalid report id");
      return fetch(BASE + "/reports/" + id + "/review/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      }).then(jsonOrThrow);
    },
    reject: function (reportId, body) {
      var id = safeReportId(reportId);
      if (!id) return reject("invalid report id");
      return fetch(BASE + "/reports/" + id + "/review/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      }).then(jsonOrThrow);
    },
    listExports: function () {
      return fetch(BASE + "/exports").then(jsonOrThrow);
    },
    /* ---- template builder (Phase 8) ---- */
    builderCreateSource: function (path, dpi) {
      return fetch(BASE + "/template-builder/source", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path, dpi: dpi || 200 }),
      }).then(jsonOrThrow);
    },
    builderGetSource: function (token) {
      if (!/^[0-9a-f]{16}$/.test(String(token))) return reject("invalid token");
      return fetch(BASE + "/template-builder/source/" + token).then(jsonOrThrow);
    },
    builderPageUrl: function (token, pageIndex) {
      if (!/^[0-9a-f]{16}$/.test(String(token))) return null;
      return BASE + "/template-builder/source/" + token + "/page/" + pageIndex;
    },
    builderPreview: function (token, template) {
      if (!/^[0-9a-f]{16}$/.test(String(token))) return reject("invalid token");
      return fetch(BASE + "/template-builder/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token, template: template }),
      }).then(jsonOrThrow);
    },
    builderSave: function (jurisdiction, templateId, template, force) {
      return fetch(BASE + "/template-builder/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jurisdiction: jurisdiction,
          template_id: templateId,
          template: template,
          force: !!force,
        }),
      }).then(jsonOrThrow);
    },
    builderDeleteSource: function (token) {
      if (!/^[0-9a-f]{16}$/.test(String(token))) return reject("invalid token");
      return fetch(BASE + "/template-builder/source/" + token, {
        method: "DELETE",
      }).then(jsonOrThrow);
    },
    builderSuggestRegions: function (token, pageIndex) {
      if (!/^[0-9a-f]{16}$/.test(String(token))) return reject("invalid token");
      var payload = { token: token };
      if (typeof pageIndex === "number") payload.page_index = pageIndex;
      return fetch(BASE + "/template-builder/suggest-regions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(jsonOrThrow);
    },
  };

  global.OCEApi = API;
})(window);
