/* Reviewer actions (approve / reject) for the report-detail view.

   This module only updates the in-memory review state through
   /api/reports/<id>/review/{approve,reject}. It never re-runs
   redaction, never alters the QA gate, and never unblocks a report
   the pipeline already refused. */

(function (global) {
  "use strict";

  function bind(reportId, onChanged) {
    var approveBtn = document.getElementById("approve-btn");
    var rejectBtn = document.getElementById("reject-btn");
    var toast = global.OCEToast || function () {};

    function payload() {
      return {
        reviewer:
          (document.getElementById("reviewer-name").value || "").trim() || null,
        notes:
          (document.getElementById("reviewer-notes").value || "").trim() || null,
      };
    }

    function describeError(err) {
      if (!err) return "request failed";
      if (err.message) return err.message;
      try { return JSON.stringify(err); } catch (e) { return "unknown error"; }
    }

    if (approveBtn) {
      approveBtn.onclick = function () {
        global.OCEApi.approve(reportId, payload())
          .then(function () {
            toast("Marked as approved", "ok");
            if (typeof onChanged === "function") onChanged();
          })
          .catch(function (err) {
            toast("Approve failed: " + describeError(err), "bad");
          });
      };
    }

    if (rejectBtn) {
      rejectBtn.onclick = function () {
        global.OCEApi.reject(reportId, payload())
          .then(function () {
            toast("Marked as rejected", "warn");
            if (typeof onChanged === "function") onChanged();
          })
          .catch(function (err) {
            toast("Reject failed: " + describeError(err), "bad");
          });
      };
    }
  }

  global.OCEReview = { bind: bind };
})(window);
