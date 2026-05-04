function operationsPerformancePage(config) {
  const REQUIRED_IMPORT_COLUMNS = ["employee_id", "score_target", "kgh_target", "period"];

  return {
    rows: Array.isArray(config.rows) ? config.rows : [],
    costCenterOptions: Array.isArray(config.costCenterOptions) ? config.costCenterOptions : ["Todos"],
    filters: { ...(config.filters || {}) },
    periodRangeLabel: config.periodRangeLabel || "",
    periodContextLabel: config.periodContextLabel || "",
    teamStats: config.teamStats || {},
    badges: config.badges || {},

    searchInput: "",
    searchTerm: "",
    searchDebounceId: null,
    quickFilter: "all",
    page: 1,
    pageSize: 20,
    selectedIds: [],

    state: "loading",
    stateMessage: "",

    modals: { details: false, edit: false, import: false, batch: false },
    detailsLoading: false,
    detailsError: "",
    detailsData: null,
    currentEditId: null,
    importMessage: "",
    importError: false,
    form: { note: "", batchNote: "" },
    notesById: {},

    init() {
      this.normalizeRows();
      this.refreshState();
    },

    normalizeRows() {
      this.rows = this.rows.map((row) => ({
        id: Number(row.id || 0),
        name: String(row.name || "Sem nome"),
        score: Number(row.score || 0),
        avg_kgh: Number(row.avg_kgh || 0),
        total_tonnage: Number(row.total_tonnage || 0),
        regularity_adjusted: Number(row.regularity_adjusted || 0),
        badge: String(row.badge || "").trim(),
        top_client: String(row.top_client || ""),
      }));
    },

    queueSearch() {
      clearTimeout(this.searchDebounceId);
      this.searchDebounceId = setTimeout(() => {
        this.searchTerm = this.searchInput.trim().toLowerCase();
        this.page = 1;
        this.refreshState();
      }, 250);
    },

    get filteredRows() {
      let out = this.rows;

      if (this.filters.cost_center && this.filters.cost_center !== "Todos") {
        const cc = this.filters.cost_center.toLowerCase();
        out = out.filter((r) => (String(r.cost_center || "").toLowerCase().includes(cc)));
      }

      if (this.quickFilter !== "all") {
        const badgeMap = {
          reference: "referência",
          evolving: "em evolução",
          potential: "potencial",
          attention: "atenção",
        };
        const expected = badgeMap[this.quickFilter] || "";
        out = out.filter((r) => String(r.badge || "").toLowerCase() === expected);
      }

      if (this.searchTerm) {
        out = out.filter((r) => {
          const haystack = `${r.name} ${r.id} ${r.top_client} ${r.badge}`.toLowerCase();
          return haystack.includes(this.searchTerm);
        });
      }

      return out;
    },

    get totalPages() {
      const pages = Math.ceil(this.filteredRows.length / this.pageSize);
      return Math.max(1, pages);
    },

    get paginatedRows() {
      const start = (this.page - 1) * this.pageSize;
      return this.filteredRows.slice(start, start + this.pageSize);
    },

    get paginationLabel() {
      if (!this.filteredRows.length) return "0 resultados";
      const start = (this.page - 1) * this.pageSize + 1;
      const end = Math.min(this.page * this.pageSize, this.filteredRows.length);
      return `${start}-${end} de ${this.filteredRows.length} resultados`;
    },

    get summary() {
      return {
        totalRows: this.rows.length,
        reference: Number(this.badges.reference || 0),
        evolving: Number(this.badges.evolving || 0),
        potential: Number(this.badges.potential || 0),
        attention: Number(this.badges.attention || 0),
      };
    },

    get allVisibleSelected() {
      if (!this.paginatedRows.length) return false;
      const selected = new Set(this.selectedIds);
      return this.paginatedRows.every((r) => selected.has(r.id));
    },

    refreshState() {
      if (!this.rows.length) {
        this.state = "empty";
        this.stateMessage = "Nenhum colaborador elegível no período.";
        return;
      }
      if (!this.filteredRows.length) {
        this.state = "no-results";
        this.stateMessage = "Refine os filtros ou limpe a busca.";
        return;
      }
      if (this.page > this.totalPages) this.page = this.totalPages;
      this.state = "ready";
      this.stateMessage = `${this.filteredRows.length} colaborador(es) no recorte atual.`;
    },

    setQuickFilter(key) {
      this.quickFilter = key;
      this.page = 1;
      this.refreshState();
    },

    resetFilters() {
      this.filters.cost_center = "Todos";
      this.filters.period = "daily";
      this.filters.date = new Date().toISOString().slice(0, 10);
      this.quickFilter = "all";
      this.searchInput = "";
      this.searchTerm = "";
      this.page = 1;
      this.refreshState();
    },

    applyServerFilters() {
      const params = new URLSearchParams(window.location.search);
      params.set("date", this.filters.date || "");
      params.set("period", this.filters.period || "daily");
      params.set("cost_center", this.filters.cost_center || "Todos");
      window.location.href = `/operations/performance?${params.toString()}`;
    },

    prevPage() {
      if (this.page > 1) this.page -= 1;
      this.refreshState();
    },

    nextPage() {
      if (this.page < this.totalPages) this.page += 1;
      this.refreshState();
    },

    toggleSelected(id) {
      const set = new Set(this.selectedIds);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      this.selectedIds = Array.from(set);
    },

    toggleSelectAll(checked) {
      const visible = this.paginatedRows.map((r) => r.id);
      const set = new Set(this.selectedIds);
      visible.forEach((id) => {
        if (checked) set.add(id);
        else set.delete(id);
      });
      this.selectedIds = Array.from(set);
    },

    openDetailsModal(employeeId) {
      this.modals.details = true;
      this.detailsLoading = true;
      this.detailsError = "";
      this.detailsData = null;

      const params = new URLSearchParams({
        date: this.filters.date || "",
        period: this.filters.period || "daily",
        cost_center: this.filters.cost_center || "Todos",
        route_band: this.filters.route_band || "Todos",
        tenure_band: this.filters.tenure_band || "Todos",
      });

      fetch(`/api/rankings/employee/${employeeId}/details?${params.toString()}`)
        .then((res) => {
          if (!res.ok) throw new Error("Falha ao consultar detalhes.");
          return res.json();
        })
        .then((payload) => {
          this.detailsData = payload || {};
        })
        .catch(() => {
          this.detailsError = "Nao foi possivel carregar os detalhes deste colaborador.";
        })
        .finally(() => {
          this.detailsLoading = false;
        });
    },

    openEditModal(employeeId) {
      this.currentEditId = employeeId;
      this.form.note = this.notesById[employeeId] || "";
      this.modals.edit = true;
    },

    saveNote() {
      if (!this.currentEditId) return;
      this.notesById[this.currentEditId] = this.form.note.trim();
      this.closeModal("edit");
    },

    openImportModal() {
      this.importError = false;
      this.importMessage = "";
      this.modals.import = true;
    },

    handleImportFile(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = () => {
        try {
          const text = String(reader.result || "");
          const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
          if (lines.length < 2) throw new Error("Arquivo vazio ou sem linhas validas.");

          const header = lines[0].split(",").map((h) => h.trim().toLowerCase());
          const missing = REQUIRED_IMPORT_COLUMNS.filter((col) => !header.includes(col));
          if (missing.length) throw new Error(`Colunas obrigatorias ausentes: ${missing.join(", ")}`);

          const idIndex = header.indexOf("employee_id");
          const periodIndex = header.indexOf("period");
          const ids = new Set();

          for (let i = 1; i < lines.length; i += 1) {
            const cols = lines[i].split(",").map((c) => c.trim());
            if (cols.every((c) => !c)) throw new Error(`Linha ${i + 1} vazia.`);
            const idRaw = cols[idIndex];
            if (!idRaw || Number.isNaN(Number(idRaw))) throw new Error(`Linha ${i + 1} com employee_id invalido.`);
            if (ids.has(idRaw)) throw new Error(`Registro duplicado para employee_id ${idRaw}.`);
            ids.add(idRaw);
            if (!cols[periodIndex]) throw new Error(`Linha ${i + 1} sem periodo.`);
          }

          this.importError = false;
          this.importMessage = `Importacao validada com sucesso (${lines.length - 1} linhas).`;
        } catch (err) {
          this.importError = true;
          this.importMessage = err.message || "Falha ao validar importacao.";
        }
      };
      reader.readAsText(file);
    },

    openBatchModal() {
      if (!this.selectedIds.length) {
        this.importError = true;
        this.importMessage = "Selecione pelo menos um colaborador para a operacao em lote.";
        this.modals.import = true;
        return;
      }
      this.form.batchNote = "";
      this.modals.batch = true;
    },

    confirmBatch() {
      const note = (this.form.batchNote || "").trim();
      if (!note) return;
      this.selectedIds.forEach((id) => {
        this.notesById[id] = note;
      });
      this.closeModal("batch");
    },

    closeModal(key) {
      this.modals[key] = false;
      if (key === "details") {
        this.detailsData = null;
        this.detailsError = "";
      }
    },

    exportVisibleCsv() {
      const headers = ["id", "nome", "score", "kgh", "volume_kg", "regularidade", "status"];
      const lines = [headers.join(",")];
      this.filteredRows.forEach((r) => {
        lines.push([
          r.id,
          `"${String(r.name).replace(/"/g, '""')}"`,
          r.score.toFixed(2),
          r.avg_kgh.toFixed(0),
          r.total_tonnage.toFixed(0),
          r.regularity_adjusted.toFixed(2),
          `"${String(r.badge).replace(/"/g, '""')}"`,
        ].join(","));
      });
      const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "performance_operacional.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },

    badgeClass(badge) {
      const normalized = String(badge || "").toLowerCase();
      if (normalized === "referência") return "sys-badge--ok";
      if (normalized === "atenção") return "sys-badge--critical";
      if (normalized === "potencial") return "sys-badge--alert";
      if (normalized === "em evolução") return "sys-badge--alert";
      return "";
    },

    formatNumber(value, decimals) {
      return new Intl.NumberFormat("pt-BR", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }).format(Number(value || 0));
    },

    formatPercent(value) {
      return `${this.formatNumber((Number(value || 0) * 100), 1)}%`;
    },

    formatTons(kg) {
      const tons = Number(kg || 0) / 1000;
      return `${this.formatNumber(tons, 1)} t`;
    },
  };
}
