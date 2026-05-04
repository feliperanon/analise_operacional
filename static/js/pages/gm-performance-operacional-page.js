(function () {
  "use strict";

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function () {
        fn.apply(ctx, args);
      }, ms);
    };
  }

  document.addEventListener("alpine:init", function () {
    Alpine.data("gmPerformancePage", function () {
      return {
        loading: true,
        error: null,
        date: "",
        q: "",
        qDebounced: "",
        view: "all",
        shift: "",
        page: 1,
        perPage: 25,
        data: null,
        selected: {},
        detailRow: null,
        detailOpen: false,
        _debouncedFetch: null,

        init: function () {
          var tzToday = this._todaySp();
          this.date = tzToday;
          this._debouncedFetch = debounce(this._fetchInternal.bind(this), 320);
          this.fetchData(true);
        },

        _todaySp: function () {
          try {
            var s = new Date().toLocaleString("en-CA", {
              timeZone: "America/Sao_Paulo",
              year: "numeric",
              month: "2-digit",
              day: "2-digit",
            });
            return s.slice(0, 10);
          } catch (e) {
            return new Date().toISOString().split("T")[0];
          }
        },

        setToday: function () {
          this.date = this._todaySp();
          this.page = 1;
          this.fetchData(true);
        },

        onSearchInput: function () {
          this.page = 1;
          this._debouncedFetch();
        },

        setView: function (v) {
          this.view = v;
          this.page = 1;
          this.fetchData(true);
        },

        clearFilters: function () {
          this.q = "";
          this.qDebounced = "";
          this.view = "all";
          this.shift = "";
          this.page = 1;
          this.selected = {};
          this.fetchData(true);
        },

        goPage: function (p) {
          var tp = this.data && this.data.routes ? this.data.routes.total_pages : 1;
          if (p < 1 || p > tp) return;
          this.page = p;
          this.fetchData(true);
        },

        fetchData: function (immediate) {
          if (immediate) {
            this._fetchInternal();
          } else {
            this._debouncedFetch();
          }
        },

        _fetchInternal: function () {
          var self = this;
          this.qDebounced = (this.q || "").trim();
          this.loading = true;
          this.error = null;
          var params = new URLSearchParams();
          params.set("date", this.date || "");
          if (this.qDebounced) params.set("q", this.qDebounced);
          if (this.view && this.view !== "all") params.set("view", this.view);
          if (this.shift) params.set("shift", this.shift);
          params.set("page", String(this.page));
          params.set("per_page", String(this.perPage));

          fetch("/api/gm/performance-operacional-data?" + params.toString(), {
            credentials: "same-origin",
            headers: { Accept: "application/json" },
          })
            .then(function (res) {
              if (!res.ok) throw new Error("Falha ao carregar");
              return res.json();
            })
            .then(function (json) {
              self.data = json;
              self._pruneSelection();
            })
            .catch(function () {
              self.error =
                "Não foi possível carregar os dados. Verifique sua conexão ou tente outra data.";
              self.data = null;
            })
            .finally(function () {
              self.loading = false;
            });
        },

        _pruneSelection: function () {
          if (!this.data || !this.data.routes || !this.data.routes.items) return;
          var ids = {};
          this.data.routes.items.forEach(function (r) {
            ids[r.id] = true;
          });
          var next = {};
          Object.keys(this.selected).forEach(function (k) {
            if (ids[Number(k)]) next[k] = true;
          });
          this.selected = next;
        },

        toggleRow: function (id) {
          var k = String(id);
          if (this.selected[k]) delete this.selected[k];
          else this.selected[k] = true;
        },

        toggleAllPage: function (ev) {
          var on = ev.target.checked;
          if (!this.data || !this.data.routes || !this.data.routes.items) return;
          var self = this;
          this.data.routes.items.forEach(function (r) {
            if (on) self.selected[String(r.id)] = true;
            else delete self.selected[String(r.id)];
          });
        },

        allPageSelected: function () {
          if (!this.data || !this.data.routes || !this.data.routes.items.length) {
            return false;
          }
          var self = this;
          return this.data.routes.items.every(function (r) {
            return self.selected[String(r.id)];
          });
        },

        selectedCount: function () {
          return Object.keys(this.selected).length;
        },

        openDetail: function (row) {
          this.detailRow = row;
          this.detailOpen = true;
        },

        closeDetail: function () {
          this.detailOpen = false;
          this.detailRow = null;
        },

        separacaoUrl: function () {
          var d = (this.data && this.data.date) || this.date || "";
          return (
            "/separacao?date=" +
            encodeURIComponent(d) +
            "&date_from=" +
            encodeURIComponent(d) +
            "&date_to=" +
            encodeURIComponent(d) +
            "&shift=" +
            encodeURIComponent(this.shift || "Manhã")
          );
        },

        formatNumber: function (v) {
          return new Intl.NumberFormat("pt-BR", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 2,
          }).format(v == null ? 0 : v);
        },

        formatCurrency: function (v) {
          return new Intl.NumberFormat("pt-BR", {
            style: "currency",
            currency: "BRL",
          }).format(v == null ? 0 : v);
        },

        badgeClass: function (badge) {
          if (badge === "ok") return "sys-badge sys-badge--ok";
          if (badge === "critical") return "sys-badge sys-badge--critical";
          if (badge === "alert") return "sys-badge sys-badge--alert";
          return "sys-badge sys-badge--neutral";
        },

        exportSelectedCsv: function () {
          if (!this.data || !this.data.routes) return;
          var want = this.selected;
          var rows = this.data.routes.items.filter(function (r) {
            return want[String(r.id)];
          });
          if (!rows.length) return;
          var headers = [
            "id",
            "turno",
            "motorista",
            "cliente",
            "placa",
            "status",
            "pedido",
            "peso_kg",
            "valor_rs",
            "bairro",
            "cidade",
          ];
          var lines = [headers.join(";")];
          rows.forEach(function (r) {
            var line = [
              r.id,
              r.shift,
              r.driver_name,
              r.client_name,
              r.plate,
              r.status_label,
              r.order,
              String(r.tonnage).replace(".", ","),
              String(r.valor).replace(".", ","),
              r.bairro,
              r.cidade,
            ]
              .map(function (cell) {
                var s = String(cell == null ? "" : cell);
                if (/[;"\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
                return s;
              })
              .join(";");
            lines.push(line);
          });
          var blob = new Blob(["\ufeff" + lines.join("\n")], {
            type: "text/csv;charset=utf-8",
          });
          var a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = "performance-operacional-recorte.csv";
          a.click();
          URL.revokeObjectURL(a.href);
        },
      };
    });
  });
})();
