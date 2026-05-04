(function () {
  "use strict";

  var root = document.querySelector('[data-page="documentos"]');
  if (!root) return;

  var debounceTimer = 0;
  var openModalId = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function setBodyLock(locked) {
    document.body.classList.toggle("overflow-hidden", !!locked);
  }

  function teleportModals() {
    ["novoDocModal", "importCsvModal", "batchModal"].forEach(function (id) {
      var el = byId(id);
      if (el && el.parentElement !== document.body) {
        document.body.appendChild(el);
      }
    });
  }

  function openModal(id) {
    var modal = byId(id);
    if (!modal) return;
    document.querySelectorAll(".emp-modal-shell:not(.hidden)").forEach(function (o) {
      if (o.id && o.id !== id) {
        o.classList.add("hidden");
        o.classList.remove("flex");
      }
    });
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    openModalId = id;
    setBodyLock(true);
    if (id === "batchModal") {
      syncExportLink();
    }
  }

  function closeModal(id) {
    var modal = byId(id);
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    if (openModalId === id) openModalId = null;
    if (!document.querySelector(".emp-modal-shell:not(.hidden)")) {
      setBodyLock(false);
    }
  }

  function syncExportLink() {
    var a = byId("doc-export-link");
    if (!a) return;
    var u = new URL("/documentos/export.csv", window.location.origin);
    var cur = new URL(window.location.href);
    ["tipo", "setor", "status", "visao", "q"].forEach(function (k) {
      var v = cur.searchParams.get(k);
      if (v) u.searchParams.set(k, v);
    });
    a.setAttribute("href", u.pathname + u.search);
  }

  function queueFilterSubmit() {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(function () {
      var form = byId("documentosFilterForm");
      if (!form) return;
      var pageField = form.querySelector('[name="page"]');
      if (pageField) pageField.value = "1";
      root.classList.add("documentos-page--navigating");
      form.requestSubmit();
    }, 360);
  }

  function hidePageAlert() {
    var el = byId("page-alert");
    if (!el) return;
    el.classList.add("hidden");
    el.innerHTML = "";
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-dismiss-alert]")) {
      hidePageAlert();
      return;
    }
    var c = e.target.closest("[data-close-modal]");
    if (c) {
      closeModal(c.getAttribute("data-close-modal"));
      return;
    }
    if (e.target.classList.contains("emp-modal-shell")) {
      closeModal(e.target.id);
      return;
    }
    var o = e.target.closest("[data-open-modal]");
    if (o) {
      openModal(o.getAttribute("data-open-modal"));
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && openModalId) {
      closeModal(openModalId);
    }
  });

  document.addEventListener("input", function (e) {
    if (e.target.matches("[data-debounce-submit='true']")) {
      queueFilterSubmit();
    }
  });

  var filterForm = byId("documentosFilterForm");
  if (filterForm) {
    filterForm.addEventListener("submit", function () {
      root.classList.add("documentos-page--navigating");
    });
  }

  window.addEventListener("pageshow", function () {
    root.classList.remove("documentos-page--navigating");
  });

  var importBtn = byId("doc-import-submit");
  var importFile = byId("doc-import-file");
  var importResult = byId("doc-import-result");

  if (importBtn && importFile) {
    importBtn.addEventListener("click", async function () {
      if (!importFile.files || !importFile.files[0]) {
        if (importResult) {
          importResult.classList.remove("hidden");
          importResult.textContent = "Selecione um arquivo CSV.";
        }
        return;
      }
      importBtn.disabled = true;
      var prev = importBtn.textContent;
      importBtn.textContent = "Enviando…";
      try {
        var fd = new FormData();
        fd.append("file", importFile.files[0]);
        var res = await fetch("/api/documentos/import", { method: "POST", body: fd, credentials: "same-origin" });
        var data = await res.json().catch(function () {
          return {};
        });
        if (importResult) {
          importResult.classList.remove("hidden");
          if (!res.ok) {
            importResult.textContent = data.error || "Falha na importação.";
            importResult.className =
              "rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-200";
          } else {
            var parts = [data.message || "Concluído."];
            if (data.errors && data.errors.length) {
              parts.push(
                "Erros: " +
                  data.errors
                    .slice(0, 8)
                    .map(function (x) {
                      return "L" + x.line + " " + (x.reason || "");
                    })
                    .join("; ")
              );
            }
            importResult.textContent = parts.join(" ");
            importResult.className =
              "rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-100";
            if (data.created) {
              window.setTimeout(function () {
                window.location.href = "/documentos?message=" + encodeURIComponent(String(data.message || "Importação concluída.")) + "&level=success";
              }, 900);
            }
          }
        }
      } catch (err) {
        if (importResult) {
          importResult.classList.remove("hidden");
          importResult.textContent = err.message || "Erro de rede.";
          importResult.className =
            "rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-200";
        }
      } finally {
        importBtn.disabled = false;
        importBtn.textContent = prev;
      }
    });
  }

  teleportModals();
  syncExportLink();
})();
