/**
 * Painel TV Gestão Avista — HTML da lista "Devoluções hoje".
 * Uso no fetchTvData (substitua o bloco que monta devBody):
 *
 *   devBody.innerHTML = window.tvDevolucoesHtmlFromPayload(dev, escTv, driverNameShort);
 *
 * escTv / driverNameShort = mesmas funções já definidas no seu script inline.
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

  global.tvDevolucoesHtmlFromPayload = function (dev, escTv, shortDriver) {
    var esc = typeof escTv === "function" ? escTv : function (s) { return String(s == null ? "" : s); };
    var shortD = typeof shortDriver === "function" ? shortDriver : function (s) { return String(s || ""); };
    var devCount = dev && dev.count != null ? dev.count : 0;
    if (!devCount) return "";

    var items = (dev.items_list && dev.items_list.length) ? dev.items_list : flattenFromItemsByDriver(dev.items_by_driver);
    var html = "";
    items.forEach(function (item) {
      var cn = item.client_name || "";
      var dn = item.driver_name || "";
      var title = esc(cn + " · " + dn);
      html +=
        '<div class="tv-alto-entry tv-devolucao-stack-entry" title="' + title + '">' +
        '<span class="tv-alto-client">' + esc(cn) + "</span>" +
        '<span class="tv-alto-driver">' + esc(shortD(dn)) + "</span>" +
        "</div>";
    });
    return html;
  };
})(typeof window !== "undefined" ? window : globalThis);
