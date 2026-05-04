function adminGamePage() {
  return {
    loading: false,
    error: "",
    rows: [],
    filteredRows: [],
    visibleRows: [],
    pageSize: 12,
    page: 1,
    searchInput: "",
    searchTerm: "",
    searchDebounceTimer: null,
    filters: { type: "all", status: "all" },
    selected: new Set(),
    employees: [],
    stats: {
      total_pending: 0,
      pending_today: 0,
      total_bonus: 0,
      total_penalty: 0,
      critical_count: 0,
    },
    toast: { show: false, type: "success", message: "" },
    createForm: { employee_id: 0, type: "add", amount: 1, reason: "" },
    editForm: { id: 0, employee_id: 0, amount: 0, reason: "" },
    importForm: { raw: "" },
    createError: "",
    editError: "",
    importError: "",
    importSuccess: "",
    savingCreate: false,
    savingEdit: false,
    importing: false,
    confirm: { open: false, action: "", ids: [], title: "", description: "" },

    init() {
      this.rows = this.readJsonFromScript("game-pending-data", []);
      this.stats = this.readJsonFromScript("game-stats-data", this.stats);
      this.applyFiltersNow();
      this.bindTableDelegation();
      this.loadEmployees();
      if (window.lucide && typeof window.lucide.createIcons === "function") {
        window.lucide.createIcons();
      }
    },

    readJsonFromScript(id, fallback) {
      const el = document.getElementById(id);
      if (!el) return fallback;
      try {
        return JSON.parse(el.textContent || "null") || fallback;
      } catch (_e) {
        return fallback;
      }
    },

    bindTableDelegation() {
      const table = document.getElementById("gameTable");
      if (!table) return;
      table.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-action]");
        if (!trigger) return;
        const id = Number(trigger.getAttribute("data-id") || 0);
        if (!id) return;
        const action = trigger.getAttribute("data-action");
        if (action === "approve") this.openSingleConfirm("approve", id);
        if (action === "reject") this.openSingleConfirm("reject", id);
        if (action === "edit") this.openEditModal(id);
      });
    },

    onSearchInput() {
      clearTimeout(this.searchDebounceTimer);
      this.searchDebounceTimer = setTimeout(() => {
        this.searchTerm = (this.searchInput || "").trim().toLowerCase();
        this.applyFiltersNow();
      }, 250);
    },

    isQuickActive(key) {
      if (key === "all") return this.filters.status === "all" && this.filters.type === "all";
      if (key === "today") return this.filters.status === "today";
      if (key === "critical") return this.filters.status === "critical";
      if (key === "bonus") return this.filters.type === "bonus";
      if (key === "penalty") return this.filters.type === "penalty";
      return false;
    },

    setQuickFilter(key) {
      if (key === "all") {
        this.filters = { type: "all", status: "all" };
      } else if (key === "today") {
        this.filters.status = "today";
      } else if (key === "critical") {
        this.filters.status = "critical";
      } else if (key === "bonus") {
        this.filters.type = "bonus";
      } else if (key === "penalty") {
        this.filters.type = "penalty";
      }
      this.applyFiltersNow();
    },

    applyFiltersNow() {
      const q = this.searchTerm;
      const type = this.filters.type;
      const status = this.filters.status;
      this.filteredRows = this.rows.filter((row) => {
        const text = `${row.employee_name} ${row.reason} ${row.date}`.toLowerCase();
        if (q && !text.includes(q)) return false;
        if (type === "bonus" && row.amount < 0) return false;
        if (type === "penalty" && row.amount >= 0) return false;
        if (status === "today" && !row.is_today) return false;
        if (status === "critical" && !row.is_critical) return false;
        if (status === "pending" && row.status && row.status !== "provisional") return false;
        return true;
      });
      this.page = 1;
      this.refreshVisibleRows();
      this.dropHiddenSelections();
    },

    clearFilters() {
      this.searchInput = "";
      this.searchTerm = "";
      this.filters.type = "all";
      this.filters.status = "all";
      this.applyFiltersNow();
    },

    refreshVisibleRows() {
      const end = this.page * this.pageSize;
      this.visibleRows = this.filteredRows.slice(0, end);
    },

    loadMore() {
      this.page += 1;
      this.refreshVisibleRows();
    },

    toggleSelect(id, checked) {
      if (checked) this.selected.add(id);
      else this.selected.delete(id);
    },

    toggleSelectAll(checked) {
      this.visibleRows.forEach((row) => {
        if (checked) this.selected.add(row.id);
        else this.selected.delete(row.id);
      });
    },

    isAllVisibleSelected() {
      if (!this.visibleRows.length) return false;
      return this.visibleRows.every((row) => this.selected.has(row.id));
    },

    dropHiddenSelections() {
      const visibleIds = new Set(this.filteredRows.map((r) => r.id));
      [...this.selected].forEach((id) => {
        if (!visibleIds.has(id)) this.selected.delete(id);
      });
    },

    async loadEmployees() {
      try {
        const res = await fetch("/api/employees");
        const data = await res.json();
        this.employees = data.employees || data.data || data || [];
      } catch (_e) {
        this.employees = [];
      }
    },

    openCreateModal() { this.openModal("game-create-modal"); },
    closeCreateModal() { this.closeModal("game-create-modal"); this.createError = ""; },
    openImportModal() { this.openModal("game-import-modal"); },
    closeImportModal() { this.closeModal("game-import-modal"); this.importError = ""; this.importSuccess = ""; },
    closeEditModal() { this.closeModal("game-edit-modal"); this.editError = ""; },
    closeConfirm() { this.closeModal("game-confirm-modal"); this.confirm.open = false; },

    openModal(id) { document.getElementById(id)?.classList.remove("hidden"); },
    closeModal(id) { document.getElementById(id)?.classList.add("hidden"); },

    async submitCreate() {
      this.createError = "";
      const employeeId = Number(this.createForm.employee_id || 0);
      const amountRaw = Number(this.createForm.amount || 0);
      if (employeeId <= 0) return (this.createError = "Selecione um colaborador.");
      if (!Number.isFinite(amountRaw) || amountRaw <= 0) return (this.createError = "Quantidade inválida.");
      if (!this.createForm.reason) return (this.createError = "Motivo obrigatório.");
      let amount = Math.trunc(amountRaw);
      if (this.createForm.type === "remove") amount = -Math.abs(amount);
      this.savingCreate = true;
      try {
        const res = await fetch("/api/game/manual-xp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            employee_id: employeeId,
            amount,
            reason: this.createForm.reason,
            status: "provisional",
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) throw new Error(data.error || "Falha ao salvar ajuste.");
        this.showToast("success", "Ajuste criado e enviado para aprovação.");
        window.location.reload();
      } catch (e) {
        this.createError = e.message || "Erro ao salvar ajuste.";
      } finally {
        this.savingCreate = false;
      }
    },

    openEditModal(id) {
      const row = this.rows.find((r) => r.id === id);
      if (!row) return;
      this.editForm = {
        id: row.id,
        employee_id: Number(row.employee_id || 0),
        amount: Number(row.amount || 0),
        reason: row.reason || "",
      };
      this.editError = "";
      this.openModal("game-edit-modal");
    },

    async submitEdit() {
      this.editError = "";
      const id = Number(this.editForm.id || 0);
      if (!id) return;
      if (!this.editForm.reason) return (this.editError = "Motivo obrigatório.");
      if (!Number.isFinite(Number(this.editForm.amount)) || Number(this.editForm.amount) === 0) {
        return (this.editError = "XP inválido.");
      }
      this.savingEdit = true;
      try {
        const res = await fetch(`/api/game/transaction/${id}/update`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            employee_id: Number(this.editForm.employee_id),
            amount: Math.trunc(Number(this.editForm.amount)),
            reason: this.editForm.reason,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) throw new Error(data.error || "Falha ao atualizar.");
        this.showToast("success", "Pendência atualizada com sucesso.");
        window.location.reload();
      } catch (e) {
        this.editError = e.message || "Erro ao atualizar.";
      } finally {
        this.savingEdit = false;
      }
    },

    validateImportRows() {
      const raw = (this.importForm.raw || "").trim();
      if (!raw) return { ok: false, error: "Cole o conteúdo CSV antes de importar." };
      const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      const parsed = [];
      const dedup = new Set();
      for (let i = 0; i < lines.length; i += 1) {
        const line = lines[i];
        const cols = line.split(",").map((c) => c.trim());
        if (cols.length < 3) return { ok: false, error: `Linha ${i + 1}: colunas insuficientes.` };
        const employee_id = Number(cols[0]);
        const amount = Number(cols[1]);
        const reason = cols[2];
        const status = (cols[3] || "provisional").toLowerCase();
        if (!Number.isInteger(employee_id) || employee_id <= 0) return { ok: false, error: `Linha ${i + 1}: employee_id inválido.` };
        if (!Number.isFinite(amount) || amount === 0) return { ok: false, error: `Linha ${i + 1}: amount inválido.` };
        if (!reason) return { ok: false, error: `Linha ${i + 1}: reason obrigatório.` };
        if (status !== "provisional" && status !== "confirmed") return { ok: false, error: `Linha ${i + 1}: status inválido.` };
        const key = `${employee_id}|${Math.trunc(amount)}|${reason.toLowerCase()}`;
        if (dedup.has(key)) return { ok: false, error: `Linha ${i + 1}: registro duplicado no arquivo.` };
        dedup.add(key);
        parsed.push({ employee_id, amount: Math.trunc(amount), reason, status });
      }
      return { ok: true, data: parsed };
    },

    async submitImport() {
      this.importError = "";
      this.importSuccess = "";
      const result = this.validateImportRows();
      if (!result.ok) return (this.importError = result.error);
      this.importing = true;
      let imported = 0;
      try {
        for (const row of result.data) {
          const res = await fetch("/api/game/manual-xp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(row),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok || !data.success) throw new Error(data.error || "Falha na importação.");
          imported += 1;
        }
        this.importSuccess = `${imported} registros importados com sucesso.`;
        this.showToast("success", "Importação concluída.");
        setTimeout(() => window.location.reload(), 700);
      } catch (e) {
        this.importError = e.message || "Erro ao importar.";
      } finally {
        this.importing = false;
      }
    },

    openSingleConfirm(action, id) {
      this.confirm = {
        open: true,
        action,
        ids: [id],
        title: action === "approve" ? "Confirmar aprovação" : "Confirmar rejeição",
        description: action === "approve" ? "Esta pendência será confirmada e o XP será aplicado." : "Esta pendência será rejeitada.",
      };
      this.openModal("game-confirm-modal");
    },

    openBatchConfirm(action) {
      const ids = [...this.selected];
      if (!ids.length) return this.showToast("error", "Selecione ao menos uma pendência.");
      this.confirm = {
        open: true,
        action,
        ids,
        title: action === "approve" ? "Aprovar itens selecionados" : "Rejeitar itens selecionados",
        description: `${ids.length} item(ns) serão processados.`,
      };
      this.openModal("game-confirm-modal");
    },

    async executeConfirm() {
      const action = this.confirm.action;
      const ids = this.confirm.ids || [];
      if (!ids.length) return;
      this.closeConfirm();
      try {
        for (const id of ids) {
          const res = await fetch(`/api/game/transaction/${id}/${action}`, { method: "POST" });
          const data = await res.json().catch(() => ({}));
          if (!res.ok || !data.success) throw new Error(data.error || `Falha no item ${id}.`);
        }
        this.showToast("success", "Operação concluída.");
        window.location.reload();
      } catch (e) {
        this.showToast("error", e.message || "Erro ao processar.");
      }
    },

    showToast(type, message) {
      this.toast = { show: true, type, message };
      setTimeout(() => { this.toast.show = false; }, 2600);
    },
  };
}
