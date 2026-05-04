(function () {
  "use strict";

  function debounce(fn, ms) {
    var t;
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function () {
        fn.apply(ctx, args);
      }, ms);
    };
  }

  function parseJsonAttr(el, name) {
    var raw = el.getAttribute(name);
    if (!raw) return [];
    try {
      return JSON.parse(raw);
    } catch (e) {
      return [];
    }
  }

  function formatDayLabel(iso) {
    if (!iso || typeof iso !== "string") return iso;
    var p = iso.split("-");
    if (p.length !== 3) return iso;
    return p[2] + "/" + p[1];
  }

  function renderDetailBody(missing, noApp, justified) {
    var h = "";
    h += '<div class="space-y-4">';
    h += '<div><p class="sys-section__label sys-section__label--field mb-2">Falta (sem rota)</p>';
    if (missing.length) {
      h += '<div class="flex flex-wrap gap-1">';
      missing.forEach(function (d) {
        h += '<span class="rr-chip rr-chip--missing">' + formatDayLabel(d) + "</span>";
      });
      h += "</div>";
    } else {
      h += '<p class="text-slate-500 dark:text-slate-400">Nenhum</p>';
    }
    h += "</div>";

    h += '<div><p class="sys-section__label sys-section__label--field mb-2">Não abriu app</p>';
    if (noApp.length) {
      h += '<div class="flex flex-wrap gap-1">';
      noApp.forEach(function (d) {
        h += '<span class="rr-chip rr-chip--noapp">' + formatDayLabel(d) + "</span>";
      });
      h += "</div>";
    } else {
      h += '<p class="text-slate-500 dark:text-slate-400">Nenhum</p>';
    }
    h += "</div>";

    h += '<div><p class="sys-section__label sys-section__label--field mb-2">Justificados</p>';
    if (justified.length) {
      h += '<ul class="list-disc space-y-1 pl-5 text-slate-700 dark:text-slate-300">';
      justified.forEach(function (j) {
        var day = j && j.date ? formatDayLabel(j.date) : "—";
        var reason = j && j.reason ? String(j.reason) : "";
        h += "<li><span class=\"font-medium\">" + day + "</span>";
        if (reason) h += " — " + reason;
        h += "</li>";
      });
      h += "</ul>";
    } else {
      h += '<p class="text-slate-500 dark:text-slate-400">Nenhum</p>';
    }
    h += "</div>";
    h += "</div>";
    return h;
  }

  function initModal() {
    var modal = document.getElementById("rr-detail-modal");
    if (!modal) return;
    var titleSub = document.getElementById("rr-detail-sub");
    var body = document.getElementById("rr-detail-body");

    function close() {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    }

    function open(name, row) {
      var missing = parseJsonAttr(row, "data-rr-missing");
      var noApp = parseJsonAttr(row, "data-rr-noapp");
      var justified = parseJsonAttr(row, "data-rr-just");
      if (titleSub) titleSub.textContent = name || "";
      if (body) body.innerHTML = renderDetailBody(missing, noApp, justified);
      modal.classList.remove("hidden");
      modal.classList.add("flex");
    }

    modal.querySelectorAll("[data-rr-modal-close]").forEach(function (el) {
      el.addEventListener("click", close);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) close();
    });

    document.querySelectorAll(".rr-detail-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var row = btn.closest("tr");
        if (!row) return;
        var name = btn.getAttribute("data-name") || "";
        open(name, row);
      });
    });
  }

  function initSearchDebounce() {
    var input = document.getElementById("rr-search-input");
    var form = document.getElementById("rr-filter-form");
    var pageInput = document.getElementById("rr-input-page");
    if (!form) return;

    function resetPage() {
      if (pageInput) pageInput.value = "1";
    }

    if (input) {
      var submitDebounced = debounce(function () {
        resetPage();
        form.submit();
      }, 380);
      input.addEventListener("input", function () {
        submitDebounced();
      });
    }

    form.querySelectorAll('input[name="start_date"], input[name="end_date"], select[name="shift"], select[name="per_page"]').forEach(function (el) {
      el.addEventListener("change", resetPage);
    });
  }

  function initPrint() {
    var b = document.getElementById("rr-btn-print");
    if (b) b.addEventListener("click", function () {
      window.print();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initModal();
      initSearchDebounce();
      initPrint();
    });
  } else {
    initModal();
    initSearchDebounce();
    initPrint();
  }
})();
