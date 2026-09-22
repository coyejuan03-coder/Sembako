const state = {
  report: null,
  records: [],
  filters: { search: "", area: "all", sourceType: "all", sort: "cheapest" },
};

const $ = (selector) => document.querySelector(selector);

function rupiah(value) {
  return `Rp${Math.round(Number(value) || 0).toLocaleString("id-ID")}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function areaLabel(area) {
  return area === "gresik" ? "Kabupaten Gresik" : "Kabupaten Lamongan";
}

function sourceLabel(type) {
  const labels = {
    "pasar rakyat": "Pasar rakyat",
    toko: "Toko",
    koperasi: "Koperasi",
    swalayan: "Swalayan",
  };
  return labels[type] || type || "Sumber";
}

function productName(record) {
  return record.productName || record.commodity || record.commodityKey;
}

function productMeta(record) {
  const parts = [record.brand, record.size || record.unit].filter(
    (part) => part && part !== "Komoditas pasar",
  );
  return parts.join(" · ") || "Komoditas pasar";
}

function productGroup(record) {
  return [
    record.commodityKey,
    record.brand || "Komoditas pasar",
    record.productName || record.commodity || "",
    record.size || record.unit || "",
  ].join("|");
}

function normalizedText(record) {
  return [
    record.commodity,
    record.productName,
    record.brand,
    record.location,
    record.address,
    areaLabel(record.area),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function freshness(record) {
  return Date.parse(record.observedAt || record.date || "") || 0;
}

function mapLink(record) {
  if (record.address && record.sourceType !== "pasar rakyat") {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(record.address)}`;
  }
  return record.sourceUrl || "";
}

function filteredRecords() {
  const { search, area, sourceType } = state.filters;
  return state.records.filter((record) => {
    const areaMatch = area === "all" || record.area === area;
    const sourceMatch = sourceType === "all" || record.sourceType === sourceType;
    const searchMatch = !search || normalizedText(record).includes(search);
    return areaMatch && sourceMatch && searchMatch;
  });
}

function cheapestRecords(records) {
  const groups = new Map();
  records.forEach((record) => {
    const key = productGroup(record);
    const current = groups.get(key);
    if (!current || Number(record.price) < Number(current.price)) groups.set(key, record);
  });
  return [...groups.values()].sort((a, b) => Number(a.price) - Number(b.price));
}

function statusChip(record) {
  const label = record.priceType === "promo" ? "Promo" : sourceLabel(record.sourceType);
  const className = record.priceType === "promo" ? "chip promo" : record.confidence === "input-manual" ? "chip manual" : "chip";
  return `<span class="${className}">${escapeHtml(label)}</span>`;
}

function renderStats(records, cheapest, trends) {
  $("#stat-cheapest").textContent = cheapest.length;
  $("#stat-warnings").textContent = trends.filter((trend) => trend.signal === "WASPADA NAIK").length;
  $("#stat-locations").textContent = new Set(records.map((record) => `${record.area}|${record.location}`)).size;
  const manual = records.filter((record) => record.confidence === "input-manual").length;
  $("#stat-confidence").textContent = manual ? `${records.length - manual}/${records.length}` : "Resmi";
}

function renderCheapest(records) {
  const container = $("#cheapest-grid");
  if (!records.length) {
    container.innerHTML = '<div class="empty">Belum ada data yang cocok dengan filter ini.</div>';
    return;
  }
  container.innerHTML = records.slice(0, 20).map((record) => {
    const href = mapLink(record);
    const location = href
      ? `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(record.location)}</a>`
      : escapeHtml(record.location);
    return `
      <article class="price-card">
        <div>
          ${statusChip(record)}
          <h3>${escapeHtml(productName(record))}</h3>
          <div class="product-meta">${escapeHtml(productMeta(record))}</div>
        </div>
        <div>
          <div class="price">${rupiah(record.price)} <small>/ ${escapeHtml(record.unit || "unit")}</small></div>
          <div class="location">${location} · ${escapeHtml(areaLabel(record.area))}</div>
        </div>
      </article>
    `;
  }).join("");
}

function renderTrends() {
  const trends = (state.report?.trends || []).filter((trend) => {
    return state.filters.area === "all" || trend.area === state.filters.area;
  });
  const container = $("#trend-list");
  if (!trends.length) {
    container.innerHTML = '<div class="empty">Belum ada riwayat tren untuk wilayah ini.</div>';
    return;
  }
  const important = trends
    .filter((trend) => trend.signal !== "NORMAL")
    .sort((a, b) => (a.signal === "WASPADA NAIK" ? -1 : 1));
  const list = important.length ? important : trends.slice(0, 6);
  container.innerHTML = list.slice(0, 8).map((trend) => {
    const badgeClass = trend.signal === "WASPADA NAIK" ? "trend-badge warning" : trend.signal === "BASELINE" ? "trend-badge baseline" : "trend-badge";
    const change = trend.changePercent == null ? "menunggu riwayat" : `${trend.changePercent >= 0 ? "+" : ""}${trend.changePercent.toFixed(1)}%`;
    return `
      <div class="trend-row">
        <div class="trend-copy">
          <strong>${escapeHtml(trend.commodity)} · ${escapeHtml(areaLabel(trend.area))}</strong>
          <span>${escapeHtml(trend.reason)} · ${escapeHtml(change)}</span>
        </div>
        <span class="${badgeClass}">${escapeHtml(trend.signal)}</span>
      </div>
    `;
  }).join("");
}

function renderTable(records) {
  const sorted = [...records].sort((a, b) => {
    if (state.filters.sort === "product") return productName(a).localeCompare(productName(b));
    if (state.filters.sort === "freshness") return freshness(b) - freshness(a);
    return Number(a.price) - Number(b.price);
  });
  $("#result-count").textContent = `${sorted.length} harga`;
  $("#price-table").innerHTML = sorted.slice(0, 100).map((record) => {
    const href = mapLink(record);
    const location = href
      ? `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(record.location)}</a>`
      : escapeHtml(record.location);
    return `
      <tr>
        <td><div class="table-product"><strong>${escapeHtml(productName(record))}</strong><span>${escapeHtml(productMeta(record))}</span></div></td>
        <td><strong>${rupiah(record.price)}</strong><br /><small>/${escapeHtml(record.unit || "unit")}</small></td>
        <td>${location}<br /><small>${escapeHtml(areaLabel(record.area))}</small></td>
        <td>${statusChip(record)}<br /><small>${escapeHtml(record.stockStatus || "status tidak dicatat")}</small></td>
        <td><small>${escapeHtml(record.observedAt || record.date || "—")}</small></td>
      </tr>
    `;
  }).join("") || '<tr><td colspan="5"><div class="empty">Belum ada data.</div></td></tr>';
}

function render() {
  const records = filteredRecords();
  const cheapest = cheapestRecords(records);
  renderStats(records, cheapest, state.report?.trends || []);
  renderCheapest(cheapest);
  renderTrends();
  renderTable(records);
}

function connectFilters() {
  $("#search").addEventListener("input", (event) => {
    state.filters.search = event.target.value.trim().toLowerCase();
    render();
  });
  $("#area").addEventListener("change", (event) => {
    state.filters.area = event.target.value;
    render();
  });
  $("#source-type").addEventListener("change", (event) => {
    state.filters.sourceType = event.target.value;
    render();
  });
  $("#sort").addEventListener("change", (event) => {
    state.filters.sort = event.target.value;
    render();
  });
}

async function loadReport() {
  try {
    const response = await fetch(`data/latest-price-report.json?ts=${Date.now()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.report = await response.json();
    state.records = state.report.records || [];
    $("#source-status").textContent = `${state.records.length} harga terpantau`;
    $("#updated-status").textContent = `Data ${state.report.date || "terbaru"}`;
    $("#footer-source").textContent = state.report.source || "Sumber data tercatat di laporan";
    const retailCount = state.report.retailCoverage?.records || state.records.filter((record) => record.sourceType !== "pasar rakyat").length;
    if (retailCount > 0) {
      $("#retail-panel").hidden = false;
      $("#retail-message").textContent = `${retailCount} harga retail ikut dibandingkan. Cek status promo dan stok sebelum membeli.`;
    }
    render();
  } catch (error) {
    $("#source-status").textContent = "Laporan belum tersedia";
    $("#updated-status").textContent = "Jalankan bot Python terlebih dahulu";
    $("#cheapest-grid").innerHTML = '<div class="empty">Data belum dapat dimuat. Jalankan <code>python track_prices.py</code>, lalu muat ulang halaman.</div>';
    $("#price-table").innerHTML = '<tr><td colspan="5"><div class="empty">Laporan JSON belum tersedia.</div></td></tr>';
    console.error(error);
  }
}

connectFilters();
loadReport();