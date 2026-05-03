/* Review actions (approve/reject) for the report-detail view. */

(function (global) {
  "use strict";

  function bind(reportId) {
    var approve = document.getElementById("approve-btn");
    var rejectBtn = document.getElementById("reject-btn");
    var resultBox = document.getElementById("review-result");
    var u = global.OCEUtils;

    function payload() {
      return {
        reviewer: (document.getElementById("reviewer").value || "").trim() || null,
        notes: (document.getElementById("review-notes").value || "").trim() || null,
      };
    }

    function show(out) {
      resultBox.textContent = JSON.stringify(out, null, 2);
      u.show(resultBox);
    }
    function showErr(err) {
      resultBox.textContent = "error: " + err.message;
      u.show(resultBox);
    }

    approve.onclick = function () {
      global.OCEApi.approve(reportId, payload()).then(show).catch(showErr);
    };
    rejectBtn.onclick = function () {
      global.OCEApi.reject(reportId, payload()).then(show).catch(showErr);
    };
  }

  global.OCEReview = { bind: bind };
})(window);
