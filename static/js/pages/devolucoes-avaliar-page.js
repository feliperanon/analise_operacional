(function () {
  "use strict";

  window.devolucoesAvaliarPage = function devolucoesAvaliarPage(init) {
    init = init || {};
    return {
      list: [],
      resumo: [],
      resumoAjudantes: [],
      loading: false,
      resumoLoading: false,
      errorMsg: "",
      quickView: "all",
      page: 1,
      perPage: 20,
      totalCount: 0,
      totalPagesServer: 1,
      pageStartServer: 0,
      pageEndServer: 0,
      dateFrom: init.date_from || "",
      dateTo: init.date_to || "",
      filterClienteNome: "",
      filterMotoristaIds: [],
      filterClientIds: [],
      filterAjudanteIds: [],
      selectedIds: [],
      batchModalOpen: false,
      batchResponsavelMotorista: true,
      batchResponsavelAjudante: true,
      savingBatch: false,
      editOpen: false,
      editItem: null,
      editPeso: "",
      editValor: "",
      resumoDetailOpen: false,
      resumoDetailLoading: false,
      resumoDetailList: [],
      resumoDetailTitle: "Detalhes",
      _debounceTimer: null,

      init() {
        this.loadAll();
      },

      get totalPages() {
        return Math.max(1, Number(this.totalPagesServer || 1));
      },

      get pagedList() {
        return this.list || [];
      },

      get pageStart() {
        return Number(this.pageStartServer || 0);
      },

      get pageEnd() {
        return Number(this.pageEndServer || 0);
      },

      get allVisibleSelected() {
        var ids = this.pagedList.map((x) => x.id);
        return ids.length > 0 && ids.every((id) => this.selectedIds.includes(id));
      },

      get stats() {
        var today = new Date().toISOString().slice(0, 10);
        var pendentes = 0;
        var concluidos = 0;
        var hoje = 0;
        this.list.forEach((item) => {
          if (item.edited) concluidos += 1;
          else pendentes += 1;
          if ((item.data_romaneio || "").slice(0, 10) === today) hoje += 1;
        });
        return {
          total: this.list.length,
          pendentes: pendentes,
          concluidos: concluidos,
          hoje: hoje,
        };
      },

      debouncedLoad() {
        clearTimeout(this._debounceTimer);
        this._debounceTimer = setTimeout(() => this.loadAll(), 380);
      },

      setQuickView(view) {
        this.quickView = view;
        this.page = 1;
        this.loadList();
      },

      clearFilters() {
        this.filterClienteNome = "";
        this.filterMotoristaIds = [];
        this.filterClientIds = [];
        this.filterAjudanteIds = [];
        this.quickView = "all";
        this.page = 1;
        this.loadAll();
      },

      formatValor(v) {
        if (v == null || v === "") return "0,00";
        return Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      },

      formatPeriodo(from, to) {
        if (!from || !to) return "—";
        return from.split("-").reverse().join("/") + " a " + to.split("-").reverse().join("/");
      },

      shortDisplayName(name) {
        var raw = String(name || "").trim();
        if (!raw) return "-";
        var parts = raw.split(/\s+/).filter(Boolean);
        if (!parts.length) return "-";
        if (parts.length === 1) return parts[0].toUpperCase();
        var first = parts[0].toUpperCase();
        var secondInitial = (parts[1] || "").charAt(0).toUpperCase();
        return secondInitial ? (first + " " + secondInitial + ".") : first;
      },

      async loadAll() {
        this.loading = true;
        this.errorMsg = "";
        this.page = 1;
        try {
          await Promise.all([this.loadList(), this.loadResumo()]);
        } finally {
          this.loading = false;
        }
      },

      async loadList() {
        var url = "/api/devolucoes/avaliar/list?date_from=" + encodeURIComponent(this.dateFrom) + "&date_to=" + encodeURIComponent(this.dateTo);
        if ((this.filterClienteNome || "").trim()) url += "&q=" + encodeURIComponent(this.filterClienteNome.trim());
        if (this.filterMotoristaIds.length) url += "&motorista_ids=" + this.filterMotoristaIds.join(",");
        if (this.filterClientIds.length) url += "&client_ids=" + this.filterClientIds.join(",");
        if (this.filterAjudanteIds.length) url += "&ajudante_ids=" + this.filterAjudanteIds.join(",");
        url += "&status_view=" + encodeURIComponent(this.quickView || "all");
        url += "&page=" + encodeURIComponent(String(this.page || 1));
        url += "&per_page=" + encodeURIComponent(String(this.perPage || 20));

        try {
          var response = await fetch(url, { credentials: "same-origin" });
          var payload = await response.json();
          if (!payload.ok) throw new Error(payload.error || "Falha ao carregar lista.");
          this.list = payload.data || [];
          var pg = payload.pagination || {};
          this.page = Number(pg.page || this.page || 1);
          this.totalCount = Number(pg.total_count || 0);
          this.totalPagesServer = Number(pg.total_pages || 1);
          this.pageStartServer = Number(pg.page_start || 0);
          this.pageEndServer = Number(pg.page_end || 0);
          this.selectedIds = this.selectedIds.filter((id) => this.list.some((item) => item.id === id));
        } catch (_error) {
          this.list = [];
          this.totalCount = 0;
          this.totalPagesServer = 1;
          this.pageStartServer = 0;
          this.pageEndServer = 0;
          this.errorMsg = "Erro ao carregar dados. Tente novamente.";
        }
      },

      async loadResumo() {
        this.resumoLoading = true;
        try {
          var response = await fetch("/api/devolucoes/avaliar/consolidado/resumo?date_from=" + encodeURIComponent(this.dateFrom) + "&date_to=" + encodeURIComponent(this.dateTo), { credentials: "same-origin" });
          var payload = await response.json();
          if (!payload.ok) throw new Error(payload.error || "Falha no resumo.");
          this.resumo = payload.data || [];
          this.resumoAjudantes = payload.data_ajudantes || [];
        } catch (_error) {
          this.resumo = [];
          this.resumoAjudantes = [];
        } finally {
          this.resumoLoading = false;
        }
      },

      toggleSelection(id, checked) {
        if (checked && !this.selectedIds.includes(id)) this.selectedIds.push(id);
        if (!checked) this.selectedIds = this.selectedIds.filter((x) => x !== id);
      },

      toggleSelectVisible(checked) {
        this.pagedList.forEach((item) => this.toggleSelection(item.id, checked));
      },

      openBatchModal() {
        if (!this.selectedIds.length) return;
        this.batchModalOpen = true;
      },

      async saveBatchResponsavel() {
        if (!this.selectedIds.length) return;
        this.savingBatch = true;
        try {
          for (var i = 0; i < this.selectedIds.length; i += 1) {
            await this.setResponsavel(this.selectedIds[i], this.batchResponsavelMotorista, this.batchResponsavelAjudante, true);
          }
          this.batchModalOpen = false;
          this.selectedIds = [];
          await this.loadResumo();
        } finally {
          this.savingBatch = false;
        }
      },

      async setResponsavel(devolucaoId, responsavelMotorista, responsavelAjudante, silent) {
        try {
          var response = await fetch("/api/devolucoes/avaliar/consolidado", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({
              devolucao_id: devolucaoId,
              responsavel_motorista: !!responsavelMotorista,
              responsavel_ajudante: !!responsavelAjudante,
            }),
          });
          var payload = await response.json();
          if (!payload.ok) throw new Error(payload.error || "Falha ao salvar responsabilidade.");
          var sync = (arr) => {
            var item = arr.find((x) => x.id === devolucaoId);
            if (!item) return;
            item.responsavel_motorista = !!responsavelMotorista;
            item.responsavel_ajudante = !!responsavelAjudante;
            item.edited = true;
          };
          sync(this.list);
          sync(this.resumoDetailList);
          if (!silent) {
            this.loadResumo();
            this.loadList();
          }
        } catch (_error) {
          if (!silent) this.errorMsg = "Erro ao salvar ajuste de responsabilidade.";
        }
      },

      openEdit(item) {
        this.editItem = {
          id: item.id,
          motivo_id: item.motivo_id != null ? String(item.motivo_id) : "",
          motorista_id: item.motorista_id != null ? String(item.motorista_id) : "",
          ajudante_ids: Array.isArray(item.ajudante_ids) ? item.ajudante_ids.map((x) => String(x)) : [],
          observacao_gestor: item.observacao_gestor || "",
        };
        this.editPeso = item.weight_kg != null && item.weight_kg !== "" ? String(item.weight_kg) : "";
        this.editValor = this.formatValor(item.value || item.valor);
        this.editOpen = true;
      },

      closeEdit() {
        this.editOpen = false;
        this.editItem = null;
        this.editPeso = "";
        this.editValor = "";
      },

      async saveEdit() {
        if (!this.editItem) return;
        var id = this.editItem.id;
        var payload = {
          motivo_id: this.editItem.motivo_id ? Number(this.editItem.motivo_id) : null,
          motorista_id: this.editItem.motorista_id ? Number(this.editItem.motorista_id) : null,
          observacao_gestor: (this.editItem.observacao_gestor || "").trim() || null,
        };
        var valor = String(this.editValor || "").replace(/\./g, "").replace(",", ".");
        if (valor && !isNaN(Number(valor))) payload.valor = Number(valor);
        if (this.editPeso !== "" && !isNaN(Number(this.editPeso))) payload.peso_kg = Number(this.editPeso);

        try {
          var response = await fetch("/api/devolucoes/" + encodeURIComponent(id), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(payload),
          });
          var data = await response.json();
          if (!data.ok) throw new Error(data.error || "Erro ao salvar.");
          var patch = (arr) => {
            var idx = arr.findIndex((x) => x.id === id);
            if (idx >= 0) {
              arr[idx] = Object.assign({}, data.data || {}, { edited: true });
            }
          };
          patch(this.list);
          patch(this.resumoDetailList);
          this.closeEdit();
          await this.loadList();
          await this.loadResumo();
        } catch (_error) {
          this.errorMsg = "Erro de validação ao salvar edição.";
        }
      },

      async openResumoMotorista(row) {
        if (!row || row.motorista_id == null) return;
        this.resumoDetailTitle = "Devoluções do motorista · " + this.shortDisplayName(row.motorista_name);
        await this.openResumoDetalhe("motorista_ids", row.motorista_id);
      },

      async openResumoAjudante(row) {
        if (!row || row.ajudante_id == null) return;
        this.resumoDetailTitle = "Devoluções do ajudante · " + this.shortDisplayName(row.ajudante_name);
        await this.openResumoDetalhe("ajudante_ids", row.ajudante_id);
      },

      async openResumoFromItem(item) {
        if (!item || item.motorista_id == null) return;
        this.resumoDetailTitle = "Devoluções do motorista · " + this.shortDisplayName(item.motorista_name);
        await this.openResumoDetalhe("motorista_ids", item.motorista_id);
      },

      async openResumoDetalhe(paramName, paramValue) {
        this.resumoDetailOpen = true;
        this.resumoDetailLoading = true;
        this.resumoDetailList = [];
        try {
          var url = "/api/devolucoes/avaliar/list?date_from=" + encodeURIComponent(this.dateFrom) + "&date_to=" + encodeURIComponent(this.dateTo) + "&" + paramName + "=" + encodeURIComponent(String(paramValue));
          url += "&page=1&per_page=200";
          var response = await fetch(url, { credentials: "same-origin" });
          var payload = await response.json();
          if (!payload.ok) throw new Error(payload.error || "Erro ao carregar detalhes.");
          this.resumoDetailList = payload.data || [];
        } catch (_error) {
          this.resumoDetailList = [];
        } finally {
          this.resumoDetailLoading = false;
        }
      },

      fecharResumoMotorista() {
        this.resumoDetailOpen = false;
        this.resumoDetailLoading = false;
        this.resumoDetailList = [];
      },
    };
  };
})();
