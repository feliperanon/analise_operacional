(function () {
  var form = document.getElementById("portariaFilterForm");
  var searchInput = document.getElementById("portariaSearchInput");
  var pageField = document.getElementById("portariaPageField");
  var checkTypeField = document.getElementById("portariaCheckTypeField");
  var searchTimer = null;

  function resetPageAndSubmit() {
    if (pageField) pageField.value = "1";
    if (form) form.requestSubmit();
  }

  if (searchInput && form) {
    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(resetPageAndSubmit, 400);
    });
    searchInput.addEventListener("search", function () {
      clearTimeout(searchTimer);
      resetPageAndSubmit();
    });
  }

  document.querySelectorAll(".portaria-quick-filter").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var v = btn.getAttribute("data-check-type") || "";
      if (checkTypeField) checkTypeField.value = v;
      document.querySelectorAll(".portaria-quick-filter").forEach(function (b) {
        b.classList.remove("filter-btn--active");
      });
      btn.classList.add("filter-btn--active");
      resetPageAndSubmit();
    });
  });

  var modal = document.getElementById("portariaDetailModal");
  var closeBtn = document.getElementById("portariaDetailClose");
  var doneBtn = document.getElementById("portariaDetailDone");

  function hideModal() {
    if (modal) {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }
  }

  function showModal() {
    if (modal) {
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    }
  }

  function fmtKm(k) {
    if (k === null || k === undefined || k === "") return "—";
    var n = Number(k);
    if (Number.isNaN(n)) return "—";
    return n.toFixed(1).replace(".", ",");
  }

  function fmtPeso(kg) {
    if (kg === null || kg === undefined || kg === "") return "—";
    var n = Number(kg);
    if (Number.isNaN(n) || n === 0) return "—";
    return Math.round(n) + " kg";
  }

  function openDetail(raw) {
    var d = typeof raw === "string" ? JSON.parse(raw) : raw;
    var el = function (id) {
      return document.getElementById(id);
    };
    if (el("pdTipo")) el("pdTipo").textContent = d.card_label || (d.check_type === "saida" ? "Saída" : "Chegada");
    if (el("pdDataHora")) el("pdDataHora").textContent = (d.date_fmt || "—") + " · " + (d.hora || "—");
    if (el("pdSessao")) el("pdSessao").textContent = d.delivery_session_id != null ? String(d.delivery_session_id) : "—";
    if (el("pdMotorista")) el("pdMotorista").textContent = d.driver_name || "—";
    if (el("pdAjudantes")) el("pdAjudantes").textContent = d.helpers_text || "—";
    if (el("pdPlaca")) el("pdPlaca").textContent = d.plate || "—";
    if (el("pdKm")) el("pdKm").textContent = fmtKm(d.km);
    if (el("pdPeso")) el("pdPeso").textContent = fmtPeso(d.peso_kg);
    if (el("pdValor")) el("pdValor").textContent = d.valor_fmt || "—";
    if (el("pdPorteiro")) el("pdPorteiro").textContent = d.porteiro_name || "—";
    showModal();
  }

  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    var btn = t.closest(".portaria-detail-btn");
    if (!btn) return;
    var raw = btn.getAttribute("data-detail");
    if (!raw) return;
    try {
      openDetail(raw);
    } catch (e) {
      console.warn("portaria detail", e);
    }
  });

  if (closeBtn) closeBtn.addEventListener("click", hideModal);
  if (doneBtn) doneBtn.addEventListener("click", hideModal);
  if (modal) {
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) hideModal();
    });
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && modal && !modal.classList.contains("hidden")) hideModal();
  });

  if (typeof lucide !== "undefined" && lucide.createIcons) {
    lucide.createIcons();
  }
})();
