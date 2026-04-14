/**
 * Painel TV Gestão Avista — HTML da lista "Devoluções hoje".
 * Uso no fetchTvData (substitua o bloco que monta devBody):
 *
 *   devBody.innerHTML = window.tvDevolucoesHtmlFromPayload(dev, escTv);
 *
 * escTv = mesma função já definida no script inline (escape HTML).
 */
(function (global) {
  function flattenFromItemsByDriver(itemsByDriver) {
    var rows = [];
    (itemsByDriver || []).forEach(function (grp) {
      (grp.clients || []).forEach(function (c) {
        rows.push({ client_name: c, driver_name: grp.driver_name });
      });
    });
    return rows;
  }

  function groupDevolucoesByDriver(dev) {
    var groups = dev && dev.items_by_driver;
    if (groups && groups.length) return groups;
    var items = (dev.items_list && dev.items_list.length) ? dev.items_list : flattenFromItemsByDriver(dev.items_by_driver);
    var map = {};
    var order = [];
    items.forEach(function (item) {
      var d = String(item.driver_name != null ? item.driver_name : "").trim() || "—";
      if (!map[d]) {
        map[d] = { driver_name: d, clients: [] };
        order.push(map[d]);
      }
      map[d].clients.push(item.client_name || "");
    });
    return order;
  }

  global.tvDevolucoesHtmlFromPayload = function (dev, escTv) {
    var esc = typeof escTv === "function" ? escTv : function (s) { return String(s == null ? "" : s); };
    var devCount = dev && dev.count != null ? dev.count : 0;
    if (!devCount) return "";

    var grouped = groupDevolucoesByDriver(dev);
    var html = "";
    grouped.forEach(function (grp) {
      var clients = grp.clients || [];
      var driverRaw = grp.driver_name || "";
      var titleRaw = clients.join(", ") + " · " + driverRaw;
      html += '<div class="tv-parado-entry tv-devolucao-entry" title="' + esc(titleRaw) + '">';
      clients.forEach(function (cn) {
        html += '<span class="tv-parado-client" title="' + esc(cn) + '">' + esc(cn) + "</span>";
      });
      html +=
        '<span class="tv-devolucao-driver tabular-nums" title="' + esc(driverRaw) + '">' + esc(driverRaw) + "</span>" +
        "</div>";
    });
    return html;
  };
})(typeof window !== "undefined" ? window : globalThis);
