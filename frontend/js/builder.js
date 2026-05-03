/* Template builder — Phase 8.

   Loads a server-side PDF, renders pages to PNG via the backend, and
   lets the operator click anchor words and drag region rectangles.
   Local assets only; every fetch hits /api/template-builder/*.
*/

(function (global) {
  "use strict";

  var u = global.OCEUtils;
  var api = global.OCEApi;

  var state = {
    token: null,
    pages: [],          /* [{index, width, height, image_url, words}] */
    pageIndex: 0,
    mode: "anchor",     /* "anchor" | "diagram" | "narrative" */
    anchors: [],
    diagram: null,      /* { page, bbox_norm: [x0,y0,x1,y1] } */
    narrative: null,
    selectedDiagramPages: new Set(),
    selectedNarrativePages: new Set(),
    pickTarget: null,   /* "narr-start" | "narr-end" | null — when set,
                           the next word click fills the named input
                           instead of toggling an identifier. */
    suggestions: [],    /* AI/heuristic region proposals, never auto-applied */
    suggestionsBackend: null, /* "layoutlm" | "heuristic" | null */
    suggestionFlags: [],
  };

  /* DOM ids for each pick target. Kept here so the pick-button binder
     and the word-click handler share a single source of truth. */
  var PICK_TARGETS = {
    "narr-start": "builder-narr-start",
    "narr-end": "builder-narr-end",
  };

  /* ---- normalization helper (mirrors backend normalize_anchor) ----- */

  /* Keep this in sync with care/extraction/anchor_match.py
     normalize_anchor: NFC + casefold + collapse whitespace + strip
     outer punctuation. The frontend uses this to count occurrences and
     colour-code anchor confidence; the backend re-normalizes on its
     own when matching, so the two paths stay independent. */
  function normalizeAnchor(value) {
    if (typeof value !== "string") return "";
    var nfc = value.normalize ? value.normalize("NFC") : value;
    var lower = nfc.toLowerCase();
    var collapsed = lower.replace(/\s+/g, " ").trim();
    return collapsed.replace(/^[\s\W_]+|[\s\W_]+$/g, "");
  }

  function countOccurrences(anchor, page) {
    var norm = normalizeAnchor(anchor);
    if (!norm || !page || !page.words) return 0;
    var n = 0;
    for (var i = 0; i < page.words.length; i++) {
      if (normalizeAnchor(page.words[i].text) === norm) n++;
    }
    return n;
  }

  function anchorQualityClass(occurrences) {
    if (occurrences === 0) return "anchor-quality-miss";
    if (occurrences === 1) return "anchor-quality-good";
    if (occurrences <= 4) return "anchor-quality-warn";
    return "anchor-quality-bad";
  }

  /* ---- coord helpers ------------------------------------------------ */

  function pixelBboxToNorm(bbox, w, h) {
    if (w <= 0 || h <= 0) throw new Error("page dimensions must be positive");
    var x0 = bbox[0], y0 = bbox[1], x1 = bbox[2], y1 = bbox[3];
    if (x1 < x0) { var tx = x0; x0 = x1; x1 = tx; }
    if (y1 < y0) { var ty = y0; y0 = y1; y1 = ty; }
    function clamp(v) { return Math.max(0, Math.min(1, v)); }
    return [clamp(x0 / w), clamp(y0 / h), clamp(x1 / w), clamp(y1 / h)];
  }

  function eventToImagePixels(event, img) {
    var rect = img.getBoundingClientRect();
    var displayedX = event.clientX - rect.left;
    var displayedY = event.clientY - rect.top;
    var scaleX = img.naturalWidth / Math.max(rect.width, 1);
    var scaleY = img.naturalHeight / Math.max(rect.height, 1);
    return [displayedX * scaleX, displayedY * scaleY];
  }

  /* ---- session lifecycle ------------------------------------------- */

  function loadSource(path) {
    var status = document.getElementById("builder-source-status");
    status.textContent = "loading " + path + " …";
    return api.builderCreateSource(path).then(function (session) {
      state.token = session.token;
      state.pages = session.pages || [];
      state.pageIndex = 0;
      state.anchors = [];
      state.diagram = null;
      state.narrative = null;
      state.selectedDiagramPages = new Set([0]);
      state.selectedNarrativePages = new Set([0]);
      state.suggestions = [];
      state.suggestionsBackend = null;
      state.suggestionFlags = [];
      status.textContent =
        "session " + session.token +
        " — " + session.page_count + " page(s) — work_dir/template-builder/" + session.token + "/";
      document.getElementById("builder-release-btn").disabled = false;
      u.show(document.getElementById("builder-canvas-card"));
      u.show(document.getElementById("builder-meta-card"));
      u.show(document.getElementById("builder-regions-card"));
      u.show(document.getElementById("builder-action-card"));
      renderPage();
      renderPagePicker();
      return session;
    }).catch(function (err) {
      status.textContent = "error: " + err.message;
    });
  }

  function releaseSession() {
    if (!state.token) return;
    var token = state.token;
    return api.builderDeleteSource(token).catch(function () {}).then(function () {
      state.token = null;
      document.getElementById("builder-source-status").textContent =
        "released session " + token;
      document.getElementById("builder-release-btn").disabled = true;
      u.hide(document.getElementById("builder-canvas-card"));
      u.hide(document.getElementById("builder-meta-card"));
      u.hide(document.getElementById("builder-regions-card"));
      u.hide(document.getElementById("builder-action-card"));
    });
  }

  /* ---- page nav + rendering ---------------------------------------- */

  function renderPage() {
    var page = state.pages[state.pageIndex];
    if (!page) return;
    var img = document.getElementById("builder-page-img");
    img.src = page.image_url;
    img.onload = function () { redrawOverlay(); };
    document.getElementById("builder-page-status").textContent =
      "page " + (state.pageIndex + 1) + " / " + state.pages.length;
    /* Anchor occurrence counts depend on the visible page — refresh
       the chip strip so colour-coding reflects the new page. */
    renderAnchorList();
  }

  function renderPagePicker() {
    /* Build chip sets [0][1]…[any] for diagram and narrative pages. */
    function build(target, selected) {
      u.clear(target);
      state.pages.forEach(function (p) {
        var chip = u.el("button", {
          type: "button",
          class: "page-chip" + (selected.has(p.index) ? " active" : ""),
          text: String(p.index),
        });
        chip.addEventListener("click", function () {
          if (selected.has(p.index)) selected.delete(p.index);
          else selected.add(p.index);
          chip.classList.toggle("active");
        });
        target.appendChild(chip);
      });
      var anyChip = u.el("button", {
        type: "button",
        class: "page-chip",
        text: "any",
      });
      anyChip.addEventListener("click", function () {
        selected.clear();
        selected.add("any");
        target.querySelectorAll("button").forEach(function (b) {
          b.classList.toggle("active", b === anyChip);
        });
      });
      target.appendChild(anyChip);
    }
    build(document.getElementById("builder-diagram-pages"), state.selectedDiagramPages);
    build(document.getElementById("builder-narrative-pages"), state.selectedNarrativePages);
  }

  /* ---- overlay (words + regions) ----------------------------------- */

  function redrawOverlay() {
    var page = state.pages[state.pageIndex];
    var overlay = document.getElementById("builder-overlay");
    var img = document.getElementById("builder-page-img");
    if (!page || !overlay || !img) return;
    u.clear(overlay);

    /* Word click targets — only render in anchor mode for clarity. */
    if (state.mode === "anchor") {
      var anchored = new Set(state.anchors);
      (page.words || []).forEach(function (w, idx) {
        if (!w.bbox) return;
        var node = wordOverlayNode(w, page, img);
        if (anchored.has(w.text)) {
          /* Multi-instance highlight: every word whose text matches an
             active anchor lights up, so the user sees what's locked in
             even when the same anchor appears multiple times. */
          node.classList.add("is-anchor");
        }
        node.addEventListener("click", function (e) {
          e.stopPropagation();
          if (state.pickTarget) {
            fillPickTarget(w.text);
          } else {
            toggleAnchor(w.text);
          }
        });
        overlay.appendChild(node);
      });
      updateEmptyPageNotice(page);
    } else {
      hideEmptyPageNotice();
    }

    /* Region overlays. */
    if (state.diagram && state.diagram.page === state.pageIndex) {
      overlay.appendChild(regionOverlayNode("diagram", state.diagram.bbox_norm, img));
    }
    if (state.narrative && state.narrative.page === state.pageIndex) {
      overlay.appendChild(regionOverlayNode("narrative", state.narrative.bbox_norm, img));
    }

    /* AI/heuristic suggestion overlays — visually distinct (dashed,
       purple-tinted) from manually drawn regions so the operator
       always sees which boxes came from a model and which came from
       their own click-and-drag. */
    state.suggestions.forEach(function (sug) {
      if (sug.page_index !== state.pageIndex) return;
      overlay.appendChild(suggestionOverlayNode(sug, img));
    });
  }

  function updateEmptyPageNotice(page) {
    var notice = document.getElementById("builder-empty-page-notice");
    if (!notice) return;
    var hasWords = (page.words || []).some(function (w) { return !!w.bbox; });
    if (hasWords) {
      u.hide(notice);
    } else {
      u.show(notice);
    }
  }

  function hideEmptyPageNotice() {
    u.hide(document.getElementById("builder-empty-page-notice"));
  }

  function wordOverlayNode(word, page, img) {
    /* word.bbox is image-space pixels at the rendered DPI. Convert to
       displayed coordinates via the image's scaling factor. */
    var rect = img.getBoundingClientRect();
    var scaleX = rect.width / Math.max(img.naturalWidth, 1);
    var scaleY = rect.height / Math.max(img.naturalHeight, 1);
    var node = u.el("div", { class: "builder-word" });
    node.style.left = (word.bbox[0] * scaleX) + "px";
    node.style.top = (word.bbox[1] * scaleY) + "px";
    node.style.width = ((word.bbox[2] - word.bbox[0]) * scaleX) + "px";
    node.style.height = ((word.bbox[3] - word.bbox[1]) * scaleY) + "px";
    node.title = word.text;
    return node;
  }

  function regionOverlayNode(label, bboxNorm, img) {
    var rect = img.getBoundingClientRect();
    var node = u.el("div", { class: "builder-region builder-region-" + label });
    node.style.left = (bboxNorm[0] * rect.width) + "px";
    node.style.top = (bboxNorm[1] * rect.height) + "px";
    node.style.width = ((bboxNorm[2] - bboxNorm[0]) * rect.width) + "px";
    node.style.height = ((bboxNorm[3] - bboxNorm[1]) * rect.height) + "px";
    node.appendChild(u.el("span", { class: "builder-region-label", text: label }));
    return node;
  }

  function suggestionOverlayNode(sug, img) {
    var rect = img.getBoundingClientRect();
    var node = u.el("div", {
      class:
        "builder-suggestion builder-suggestion-" +
        (sug.label === "diagram" || sug.label === "narrative" ? sug.label : "other"),
    });
    node.style.left = (sug.bbox_norm[0] * rect.width) + "px";
    node.style.top = (sug.bbox_norm[1] * rect.height) + "px";
    node.style.width = ((sug.bbox_norm[2] - sug.bbox_norm[0]) * rect.width) + "px";
    node.style.height = ((sug.bbox_norm[3] - sug.bbox_norm[1]) * rect.height) + "px";
    var labelText = "AI: " + sug.label + " (" + sug.source + ", " +
      Math.round((sug.confidence || 0) * 100) + "%)";
    node.appendChild(u.el("span", {
      class: "builder-region-label builder-suggestion-label",
      text: labelText,
    }));
    return node;
  }

  /* ---- anchors ----------------------------------------------------- */

  function toggleAnchor(text) {
    if (!text) return;
    var idx = state.anchors.indexOf(text);
    var added;
    if (idx >= 0) {
      state.anchors.splice(idx, 1);
      added = false;
    } else {
      state.anchors.push(text);
      added = true;
    }
    renderAnchorList();
    flashAnchorStatus(text, added);
    if (state.mode === "anchor") redrawOverlay();
  }

  function flashAnchorStatus(text, added) {
    var status = document.getElementById("builder-anchor-status");
    if (!status) return;
    status.textContent =
      (added ? "✓ added" : "✕ removed") +
      " anchor: " + JSON.stringify(text);
    status.classList.remove("flash");
    /* Force reflow so the animation restarts on every click. */
    void status.offsetWidth;
    status.classList.add("flash");
  }

  function renderAnchorList() {
    var hosts = [
      document.getElementById("builder-anchors"),
      document.getElementById("builder-canvas-anchors"),
    ];
    var page = state.pages[state.pageIndex];
    hosts.forEach(function (host) {
      if (!host) return;
      u.clear(host);
      if (state.anchors.length === 0) {
        host.appendChild(u.el("li", {
          class: "muted small",
          text: "(no identifiers yet — click words on the page or type below)",
        }));
        return;
      }
      state.anchors.forEach(function (a) {
        var occurrences = countOccurrences(a, page);
        var qualityClass = anchorQualityClass(occurrences);
        var li = u.el("li", { class: "builder-anchor-chip " + qualityClass });
        li.appendChild(u.el("span", { text: a }));
        var badge = u.el("span", {
          class: "builder-anchor-count",
          text: occurrences === 0 ? " (× ?)" : " (×" + occurrences + ")",
        });
        li.appendChild(badge);
        if (occurrences === 0) {
          li.title = "click to remove — not visible on this page (manual or OCR-only)";
        } else if (occurrences === 1) {
          li.title = "click to remove — unique on this page (strong identifier)";
        } else {
          li.title = "click to remove — appears " + occurrences +
            " times on this page; consider a more specific identifier";
        }
        li.addEventListener("click", function () { toggleAnchor(a); });
        host.appendChild(li);
      });
    });
  }

  function bindManualAnchorInput() {
    var input = document.getElementById("builder-anchor-input");
    var btn = document.getElementById("builder-anchor-add-btn");
    if (!input || !btn) return;
    function commit() {
      var raw = (input.value || "").trim();
      if (!raw) return;
      toggleAnchor(raw);
      input.value = "";
      input.focus();
    }
    btn.addEventListener("click", commit);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        commit();
      }
    });
  }

  /* ---- pick-from-page (narrative anchor_start / anchor_end) ------- */

  function setPickTarget(target) {
    state.pickTarget = target;
    document.querySelectorAll(".builder-pickbtn").forEach(function (b) {
      b.classList.toggle("active", b.dataset.pick === target);
    });
    var hint = document.getElementById("builder-mode-hint");
    if (target && hint) {
      var label = target === "narr-start" ? "narrative start" : "narrative end";
      hint.textContent = "Click a word on the page to fill the " +
        label + " anchor (Esc to cancel).";
    } else if (hint) {
      /* Restore the hint matching the active mode. */
      if (state.mode === "anchor") hint.textContent = "Click a word to add it as a form identifier.";
      else if (state.mode === "diagram") hint.textContent = "Drag a rectangle around the diagram.";
      else hint.textContent = "Drag a rectangle around the narrative.";
    }
  }

  function fillPickTarget(text) {
    if (!state.pickTarget || !text) return;
    var inputId = PICK_TARGETS[state.pickTarget];
    if (!inputId) return;
    var input = document.getElementById(inputId);
    if (input) {
      input.value = text;
      flashAnchorStatus(text, true);
    }
    setPickTarget(null);
  }

  function bindPickButtons() {
    document.querySelectorAll(".builder-pickbtn").forEach(function (b) {
      b.addEventListener("click", function () {
        /* Toggle: clicking the active button cancels. */
        if (state.pickTarget === b.dataset.pick) {
          setPickTarget(null);
        } else {
          /* Pick mode only fires word clicks, which are anchor-mode-only.
             Switch the user there so the words are visible to click. */
          setMode("anchor");
          setPickTarget(b.dataset.pick);
        }
      });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && state.pickTarget) setPickTarget(null);
    });
  }

  /* ---- region drawing (mouse marquee) ------------------------------ */

  function bindCanvasEvents() {
    var canvas = document.getElementById("builder-canvas");
    var img = document.getElementById("builder-page-img");
    var origin = null;
    var marquee = null;

    canvas.addEventListener("mousedown", function (e) {
      if (state.mode === "anchor") return;
      if (e.button !== 0) return;
      origin = eventToImagePixels(e, img);
      marquee = u.el("div", { class: "builder-marquee" });
      var rect = img.getBoundingClientRect();
      var displayedX = e.clientX - rect.left;
      var displayedY = e.clientY - rect.top;
      marquee.style.left = displayedX + "px";
      marquee.style.top = displayedY + "px";
      marquee.style.width = "0px";
      marquee.style.height = "0px";
      document.getElementById("builder-overlay").appendChild(marquee);
      e.preventDefault();
    });

    canvas.addEventListener("mousemove", function (e) {
      if (!origin || !marquee) return;
      var rect = img.getBoundingClientRect();
      var displayedX = e.clientX - rect.left;
      var displayedY = e.clientY - rect.top;
      var marqueeLeft = parseFloat(marquee.style.left);
      var marqueeTop = parseFloat(marquee.style.top);
      var w = displayedX - marqueeLeft;
      var h = displayedY - marqueeTop;
      if (w < 0) {
        marquee.style.left = displayedX + "px";
        w = -w;
      }
      if (h < 0) {
        marquee.style.top = displayedY + "px";
        h = -h;
      }
      marquee.style.width = w + "px";
      marquee.style.height = h + "px";
    });

    canvas.addEventListener("mouseup", function (e) {
      if (!origin) return;
      var end = eventToImagePixels(e, img);
      var page = state.pages[state.pageIndex];
      var bboxNorm = pixelBboxToNorm(
        [origin[0], origin[1], end[0], end[1]],
        page.width, page.height
      );
      origin = null;
      if (marquee && marquee.parentNode) marquee.parentNode.removeChild(marquee);
      marquee = null;
      /* Reject zero-area boxes */
      if (bboxNorm[2] <= bboxNorm[0] || bboxNorm[3] <= bboxNorm[1]) {
        return;
      }
      if (state.mode === "diagram") {
        state.diagram = { page: state.pageIndex, bbox_norm: bboxNorm };
        document.getElementById("builder-diagram-bbox").textContent =
          "page " + state.pageIndex + " — bbox_norm " + JSON.stringify(bboxNorm.map(round4));
        if (!state.selectedDiagramPages.has("any")) {
          state.selectedDiagramPages.add(state.pageIndex);
          renderPagePicker();
        }
      } else if (state.mode === "narrative") {
        state.narrative = { page: state.pageIndex, bbox_norm: bboxNorm };
        document.getElementById("builder-narrative-bbox").textContent =
          "page " + state.pageIndex + " — bbox_norm " + JSON.stringify(bboxNorm.map(round4));
        if (!state.selectedNarrativePages.has("any")) {
          state.selectedNarrativePages.add(state.pageIndex);
          renderPagePicker();
        }
      }
      redrawOverlay();
    });
  }

  function round4(v) { return Math.round(v * 10000) / 10000; }

  /* ---- template assembly ------------------------------------------- */

  function pagesFromSet(set_) {
    if (set_.has("any")) return "any";
    var arr = Array.from(set_).filter(function (v) { return typeof v === "number"; });
    arr.sort(function (a, b) { return a - b; });
    return arr;
  }

  function buildTemplateDict() {
    var template_id = (document.getElementById("builder-template-id").value || "").trim();
    var jurisdiction = (document.getElementById("builder-jurisdiction").value || "").trim();
    var version = (document.getElementById("builder-version").value || "").trim() || "0";
    var formRegex = (document.getElementById("builder-form-regex").value || "").trim();

    var template = {
      template_id: template_id,
      jurisdiction: jurisdiction || null,
      version: version,
      signature: {
        anchor_text: state.anchors.slice(),
        form_number_regex: formRegex || null,
      },
      regions: {},
    };

    if (state.diagram) {
      var diagPages = pagesFromSet(state.selectedDiagramPages);
      var dr = {
        page: diagPages.length === 1 && typeof diagPages[0] === "number" ? diagPages[0] : diagPages,
        bbox_norm: state.diagram.bbox_norm,
        requires_redaction: true,
      };
      if (document.getElementById("builder-dc-enabled").checked) {
        dr.diagram_continuation = {
          candidate_pages: diagPages,
          require_visual_density: document.getElementById("builder-dc-density").checked,
          max_text_density: parseFloat(document.getElementById("builder-dc-max").value) || 0.05,
        };
      }
      template.regions.diagram = dr;
    }

    if (state.narrative) {
      var narrPages = pagesFromSet(state.selectedNarrativePages);
      var nr = {
        page: narrPages.length === 1 && typeof narrPages[0] === "number" ? narrPages[0] : narrPages,
        bbox_norm: state.narrative.bbox_norm,
        anchor_start: (document.getElementById("builder-narr-start").value || "").trim() || null,
        anchor_end: (document.getElementById("builder-narr-end").value || "").trim() || null,
      };
      if (document.getElementById("builder-cont-enabled").checked) {
        var rawPages = (document.getElementById("builder-cont-pages").value || "").trim();
        var contPages;
        if (rawPages === "any" || rawPages === "") contPages = "any";
        else contPages = rawPages.split(",").map(function (s) { return parseInt(s.trim(), 10); }).filter(function (n) { return !isNaN(n); });
        var rawStop = (document.getElementById("builder-cont-stop").value || "").trim();
        var stopAt = null;
        if (rawStop) {
          var parts = rawStop.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
          stopAt = parts.length === 1 ? parts[0] : parts;
        }
        nr.continuation = {
          pages: contPages,
          anchor_end: nr.anchor_end,
          continue_until_anchor_found: true,
          max_continuation_pages: parseInt(document.getElementById("builder-cont-max").value, 10) || 3,
          stop_at_next_section_anchor: stopAt,
          require_review_if_anchor_end_missing:
            document.getElementById("builder-cont-require-end").checked,
        };
      }
      if (document.getElementById("builder-shift-enabled").checked) {
        nr.shifted_region_search = {
          enabled: true,
          search_pages: "any",
          min_primary_score: parseFloat(document.getElementById("builder-shift-min").value) || 0.5,
          require_review_on_shift:
            document.getElementById("builder-shift-review").checked,
        };
      }
      template.regions.narrative = nr;
    }

    return { template: template, jurisdiction: jurisdiction, template_id: template_id };
  }

  function previewTemplate() {
    if (!state.token) return;
    var assembled = buildTemplateDict();
    var box = document.getElementById("builder-result");
    api.builderPreview(state.token, assembled.template).then(function (out) {
      box.textContent = JSON.stringify(out, null, 2);
      u.show(box);
    }).catch(function (err) {
      box.textContent = "error: " + err.message;
      u.show(box);
    });
  }

  function saveTemplate() {
    if (!state.token) return;
    var assembled = buildTemplateDict();
    var force = document.getElementById("builder-force").checked;
    var box = document.getElementById("builder-result");
    api.builderSave(
      assembled.jurisdiction, assembled.template_id, assembled.template, force
    ).then(function (out) {
      box.textContent = "Saved: " + JSON.stringify(out, null, 2);
      u.show(box);
    }).catch(function (err) {
      box.textContent = "error: " + err.message;
      u.show(box);
    });
  }

  /* ---- mode toggle + nav ------------------------------------------- */

  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll(".builder-mode").forEach(function (b) {
      b.classList.toggle("active", b.dataset.mode === mode);
    });
    /* A pending pick only makes sense in anchor mode (words must be
       clickable). Clear it on any other mode. */
    if (mode !== "anchor" && state.pickTarget) {
      state.pickTarget = null;
      document.querySelectorAll(".builder-pickbtn").forEach(function (b) {
        b.classList.remove("active");
      });
    }
    var hint = document.getElementById("builder-mode-hint");
    if (state.pickTarget) {
      var label = state.pickTarget === "narr-start" ? "narrative start" : "narrative end";
      hint.textContent = "Click a word on the page to fill the " +
        label + " anchor (Esc to cancel).";
    } else if (mode === "anchor") hint.textContent = "Click a word to add it as a form identifier.";
    else if (mode === "diagram") hint.textContent = "Drag a rectangle around the diagram.";
    else hint.textContent = "Drag a rectangle around the narrative.";
    redrawOverlay();
  }

  function bindControls() {
    var form = document.getElementById("builder-source-form");
    if (form) form.addEventListener("submit", function (e) {
      e.preventDefault();
      var path = u.cleanPath(document.getElementById("builder-source-path").value);
      if (path) loadSource(path);
    });
    document.querySelectorAll(".builder-mode").forEach(function (b) {
      b.addEventListener("click", function () { setMode(b.dataset.mode); });
    });
    document.getElementById("builder-page-prev").addEventListener("click", function () {
      if (state.pageIndex > 0) { state.pageIndex--; renderPage(); }
    });
    document.getElementById("builder-page-next").addEventListener("click", function () {
      if (state.pageIndex < state.pages.length - 1) { state.pageIndex++; renderPage(); }
    });
    document.getElementById("builder-preview-btn").addEventListener("click", previewTemplate);
    document.getElementById("builder-save-btn").addEventListener("click", saveTemplate);
    document.getElementById("builder-release-btn").addEventListener("click", releaseSession);
    var sugBtn = document.getElementById("builder-suggest-btn");
    if (sugBtn) sugBtn.addEventListener("click", fetchSuggestions);
    bindCanvasEvents();
    bindManualAnchorInput();
    bindPickButtons();
    bindResizeHandler();
  }

  /* Re-render overlays after a debounce so mid-drag layout shifts (browser
     resize, devtools opening, etc.) keep word/region overlays aligned with
     the underlying glyphs. */
  function bindResizeHandler() {
    var pending = null;
    window.addEventListener("resize", function () {
      if (pending) clearTimeout(pending);
      pending = setTimeout(function () { redrawOverlay(); }, 80);
    });
  }

  /* ---- AI/heuristic region suggestions (Phase 11) ----------------- */

  function fetchSuggestions() {
    if (!state.token) return;
    var btn = document.getElementById("builder-suggest-btn");
    var status = document.getElementById("builder-suggest-status");
    if (btn) btn.disabled = true;
    if (status) status.textContent = "running suggester …";
    api.builderSuggestRegions(state.token, state.pageIndex)
      .then(function (out) {
        state.suggestions = (out && out.suggestions) || [];
        state.suggestionsBackend = (out && out.backend) || null;
        state.suggestionFlags = (out && out.qa_flags) || [];
        if (status) {
          var n = state.suggestions.length;
          var label = state.suggestionsBackend === "layoutlm"
            ? "LayoutLM" : "offline heuristic";
          status.textContent = n === 0
            ? "no suggestions for this page"
            : n + " suggestion(s) from " + label +
              " — review and Accept each one before it enters the template.";
        }
        renderSuggestionList();
        redrawOverlay();
      })
      .catch(function (err) {
        if (status) status.textContent = "error: " + err.message;
      })
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  function renderSuggestionList() {
    var host = document.getElementById("builder-suggestions");
    if (!host) return;
    u.clear(host);
    if (state.suggestions.length === 0) return;
    state.suggestions.forEach(function (sug) {
      var li = u.el("li", { class: "builder-suggestion-row" });
      var meta = u.el("span", {
        class: "builder-suggestion-meta",
        text:
          "page " + sug.page_index + " · " + sug.label +
          " · " + sug.source + " · " +
          Math.round((sug.confidence || 0) * 100) + "%",
      });
      li.appendChild(meta);
      var jumpBtn = u.el("button", {
        type: "button",
        class: "builder-suggestion-action",
        text: "Show",
      });
      jumpBtn.addEventListener("click", function () {
        if (sug.page_index !== state.pageIndex) {
          state.pageIndex = sug.page_index;
          renderPage();
        } else {
          redrawOverlay();
        }
      });
      var acceptBtn = u.el("button", {
        type: "button",
        class: "builder-suggestion-action builder-suggestion-accept",
        text: "Accept",
      });
      acceptBtn.addEventListener("click", function () {
        acceptSuggestion(sug);
      });
      var rejectBtn = u.el("button", {
        type: "button",
        class: "builder-suggestion-action builder-suggestion-reject",
        text: "Reject",
      });
      rejectBtn.addEventListener("click", function () {
        rejectSuggestion(sug);
      });
      li.appendChild(jumpBtn);
      li.appendChild(acceptBtn);
      li.appendChild(rejectBtn);
      host.appendChild(li);
    });
  }

  function acceptSuggestion(sug) {
    /* Acceptance converts a suggestion into a regular template region
       — same shape that draw-and-drag produces. The suggestion is
       then removed from the list so it doesn't render twice (once
       as a suggestion, once as the accepted region). */
    if (sug.label === "diagram") {
      state.diagram = {
        page: sug.page_index,
        bbox_norm: sug.bbox_norm.slice(),
      };
      var dbox = document.getElementById("builder-diagram-bbox");
      if (dbox) {
        dbox.textContent = "page " + sug.page_index +
          " — bbox_norm " + JSON.stringify(sug.bbox_norm.map(round4));
      }
      if (!state.selectedDiagramPages.has("any")) {
        state.selectedDiagramPages.add(sug.page_index);
        renderPagePicker();
      }
    } else if (sug.label === "narrative") {
      state.narrative = {
        page: sug.page_index,
        bbox_norm: sug.bbox_norm.slice(),
      };
      var nbox = document.getElementById("builder-narrative-bbox");
      if (nbox) {
        nbox.textContent = "page " + sug.page_index +
          " — bbox_norm " + JSON.stringify(sug.bbox_norm.map(round4));
      }
      if (!state.selectedNarrativePages.has("any")) {
        state.selectedNarrativePages.add(sug.page_index);
        renderPagePicker();
      }
    }
    /* Drop this suggestion from the list — accepted suggestions
       become regular regions and shouldn't continue showing as
       proposals. */
    state.suggestions = state.suggestions.filter(function (s) {
      return s.suggestion_id !== sug.suggestion_id;
    });
    renderSuggestionList();
    redrawOverlay();
  }

  function rejectSuggestion(sug) {
    state.suggestions = state.suggestions.filter(function (s) {
      return s.suggestion_id !== sug.suggestion_id;
    });
    renderSuggestionList();
    redrawOverlay();
  }

  function init() {
    bindControls();
    renderAnchorList();  /* shows the empty-state hint up front */
  }

  /* Re-bind on each view show because the view starts hidden. */
  global.OCEBuilder = {
    init: init,
    loadSource: loadSource,
    pixelBboxToNorm: pixelBboxToNorm,
  };
})(window);
