"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const state = {hours: 24, dimension: "product", offset: 0, alertOffset: 0, controller: null, hasData: false, chartData: null};
  const money = value => value === null ? "—" : new Intl.NumberFormat("en-IN", {style: "currency", currency: "INR", maximumFractionDigits: 2}).format(Number(value));
  const integer = value => new Intl.NumberFormat("en-IN").format(value);
  const percent = value => value === null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
  const clock = date => new Intl.DateTimeFormat("en-IN", {hour: "2-digit", minute: "2-digit", hour12: false}).format(date);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  $("today").textContent = new Intl.DateTimeFormat("en-IN", {day: "numeric", month: "short", year: "numeric"}).format(new Date());
  $("timezone").textContent = zone;

  async function get(path, params, signal) {
    const response = await fetch(`${path}?${new URLSearchParams(params)}`, {signal, cache: "no-store"});
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
  }

  async function getWindows(params, signal) {
    const rows = [];
    // A 24-hour view can have 1,440 minute rows. Read every page, not just the first 500.
    for (let offset = 0; offset <= 1500; offset += 500) {
      const page = await get("/api/v1/metrics/windows", {...params, dimension: "all", limit: 500, offset}, signal);
      rows.push(...page.items);
      if (!page.has_more) return rows;
    }
    throw new Error("Unexpected number of minute rows");
  }

  function status(kind, message) {
    $("connection").className = `connection ${kind}`;
    $("connection-text").textContent = message;
  }

  function drawChart(rows, start, end) {
    const container = $("revenue-chart");
    container.replaceChildren();
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "chart-empty";
      empty.textContent = "No order activity in this period";
      container.append(empty);
      container.setAttribute("aria-label", empty.textContent);
      $("chart-note").textContent = "Select a wider range or start the event generator";
      return;
    }
    const hours = (end - start) / 3600000;
    const count = hours === 1 ? 60 : hours === 6 ? 72 : 96;
    const step = (end - start) / count;
    const bins = Array(count).fill(0);
    rows.forEach(row => {
      const index = Math.floor((Date.parse(row.window_start) - start) / step);
      if (index >= 0 && index < count) bins[index] += Math.round(Number(row.completed_revenue) * 100);
    });
    const max = Math.max(...bins, 100) / 100;
    const width = Math.max(300, container.clientWidth), height = 205, left = 51, right = 17, top = 12, bottom = 30;
    const x = i => left + i * (width - left - right) / (count - 1);
    const y = amount => height - bottom - amount / max * (height - top - bottom);
    const points = bins.map((amount, i) => `${x(i).toFixed(2)},${y(amount / 100).toFixed(2)}`);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Revenue chart. Peak ${money(max)} per ${step / 60000}-minute interval.`);
    // Only numeric coordinates and locale-formatted numeric labels enter SVG markup.
    let markup = '<defs><linearGradient id="revenue-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#58a581" stop-opacity=".22"/><stop offset="100%" stop-color="#58a581" stop-opacity=".01"/></linearGradient></defs>';
    for (let i = 0; i <= 3; i++) {
      const amount = max * i / 3, yy = y(amount);
      const label = new Intl.NumberFormat("en-IN", {notation: "compact", maximumFractionDigits: 1}).format(amount);
      markup += `<line x1="${left}" y1="${yy}" x2="${width-right}" y2="${yy}" stroke="#ecf0ed" stroke-dasharray="3 4"/><text x="${left-10}" y="${yy+3}" text-anchor="end">₹${label}</text>`;
    }
    markup += `<path d="M ${left},${height-bottom} L ${points.join(" L ")} L ${width-right},${height-bottom} Z" fill="url(#revenue-fill)"/><polyline points="${points.join(" ")}" fill="none" stroke="#26835f" stroke-width="2.3" stroke-linejoin="round"/>`;
    for (let i = 0; i <= 4; i++) {
      const position = Math.round(i * (count - 1) / 4);
      markup += `<text x="${x(position)}" y="${height-7}" text-anchor="${i === 0 ? "start" : i === 4 ? "end" : "middle"}">${clock(new Date(start + position * step))}</text>`;
    }
    svg.innerHTML = markup;
    bins.forEach((amount, i) => {
      if (!amount) return;
      const circle = document.createElementNS(svg.namespaceURI, "circle");
      circle.setAttribute("cx", x(i)); circle.setAttribute("cy", y(amount / 100));
      circle.setAttribute("r", "3.5"); circle.setAttribute("fill", "#26835f");
      circle.setAttribute("tabindex", "0");
      const description = `${clock(new Date(start + i * step))}: ${money(amount / 100)}`;
      circle.setAttribute("aria-label", description);
      const title = document.createElementNS(svg.namespaceURI, "title");
      title.textContent = description; circle.append(title); svg.append(circle);
    });
    container.setAttribute("aria-label", "Completed revenue by event time");
    container.append(svg);
    $("chart-note").textContent = `${step / 60000}-minute intervals · Minutes without recorded orders shown as zero`;
  }

  function render(summary, rows, breakdown, start, end) {
    $("revenue").textContent = money(summary.completed_revenue);
    $("orders").textContent = integer(summary.order_count);
    $("aov").textContent = money(summary.average_order_value);
    $("failure").textContent = percent(summary.failed_order_rate);
    $("completed-detail").textContent = `${integer(summary.completed_order_count)} completed orders`;
    $("failed-detail").textContent = `${integer(summary.failed_order_count)} failed of ${integer(summary.order_count)} orders`;
    $("chart-total").textContent = money(summary.completed_revenue);
    $("chart-period").textContent = `over the last ${state.hours} ${state.hours === 1 ? "hour" : "hours"}`;
    const total = summary.order_count, completed = summary.completed_order_count, failed = summary.failed_order_count;
    const pending = Math.max(0, total - completed - failed);
    $("donut-total").textContent = integer(total);
    $("outcome-completed").textContent = integer(completed);
    $("outcome-pending").textContent = integer(pending);
    $("outcome-failed").textContent = integer(failed);
    const completeAngle = total ? completed / total * 360 : 0;
    const pendingAngle = total ? (completed + pending) / total * 360 : 0;
    $("outcome-donut").style.background = total ? `conic-gradient(#23845f 0deg ${completeAngle}deg, #e2c47d ${completeAngle}deg ${pendingAngle}deg, #db8a77 ${pendingAngle}deg 360deg)` : "#edf1ee";
    state.chartData = [rows, start, end];
    drawChart(...state.chartData);
    const body = $("performance-body"); body.replaceChildren();
    $("dimension-title").textContent = state.dimension === "product" ? "Product" : "Category";
    breakdown.items.forEach((item, index) => {
      const row = document.createElement("tr");
      const nameCell = document.createElement("td");
      const wrapper = document.createElement("div"); wrapper.className = "product-cell";
      const rank = document.createElement("span"); rank.className = "product-rank"; rank.textContent = String(state.offset + index + 1).padStart(2, "0");
      const name = document.createElement("span"); name.className = "product-name";
      name.textContent = item.dimension_value; name.title = item.dimension_value;
      wrapper.append(rank, name); nameCell.append(wrapper); row.append(nameCell);
      [integer(item.order_count), money(item.completed_revenue), money(item.average_order_value)].forEach(value => {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      });
      const failureCell = document.createElement("td"), pill = document.createElement("span");
      pill.className = `failure-pill${Number(item.failed_order_rate) > 0 ? " warning" : ""}`;
      pill.textContent = percent(item.failed_order_rate); failureCell.append(pill); row.append(failureCell); body.append(row);
    });
    if (!breakdown.items.length) {
      const row = document.createElement("tr"), cell = document.createElement("td");
      cell.colSpan = 5; cell.className = "empty-cell"; cell.textContent = "No results for this period or page.";
      row.append(cell); body.append(row);
    }
    $("previous").disabled = state.offset === 0;
    $("next").disabled = !breakdown.has_more;
    $("page-label").textContent = breakdown.items.length ? `Showing ${state.offset + 1}–${state.offset + breakdown.items.length} · Ranked by completed revenue` : "No results";
    const updated = summary.last_updated ? new Date(summary.last_updated) : null;
    if (!updated) status("stale", "No data in range");
    else if (Date.now() - updated.getTime() > 120000) status("stale", "No recent aggregate updates");
    else status("fresh", "Recent aggregate update");
    $("freshness").textContent = `Refreshed ${clock(new Date())}${updated ? ` · Last aggregate update ${updated.toLocaleString("en-IN")}` : " · No aggregate updates in range"}`;
  }

  function renderAnomalies(page) {
    $("anomaly-items").replaceChildren();
    $("alerts-previous").disabled = state.alertOffset === 0;
    $("alerts-next").disabled = !page || !page.has_more;
    if (!page) {
      $("anomaly-status").textContent = "Detector unavailable. Commerce metrics remain available; no claim can be made about anomalies.";
      $("anomaly-note").textContent = "Start or check the detector service.";
      return;
    }
    const stale = !page.last_successful_run || Date.now() - Date.parse(page.last_successful_run) > 90000;
    const eligible = page.checked_count - page.insufficient_count;
    let message = !page.checked_count ? "No eligible minute windows have been checked in this period yet." :
      !eligible ? "Building a baseline. There is not enough order activity to assess anomalies yet." :
      page.flagged_count ? `${page.flagged_count} signals to investigate in this period.` : "No spikes flagged among assessed checks in this period.";
    if (stale) message = "Detector updates are stale. These are historical results. " + message;
    $("anomaly-status").textContent = message;
    $("anomaly-note").textContent = `${eligible} assessed checks · ${page.insufficient_count} checks need more data · Late arrivals may revise results`;
    page.items.forEach(item => {
      const card = document.createElement("article"); card.className = "signal-card";
      const title = document.createElement("h3");
      title.textContent = `${item.detector === "failure_rate_spike" ? "Order failure-rate spike" : "Completed revenue spike"} · ${new Date(item.window_start).toLocaleString("en-IN")}`;
      const evidence = document.createElement("p"); evidence.className = "signal-evidence";
      const format = item.unit === "fraction" ? percent : money;
      evidence.textContent = `Observed ${format(item.observed_value)} · Threshold ${format(item.threshold)} · Baseline ${format(item.baseline_value)}`;
      const detail = document.createElement("p"); detail.textContent = item.explanation;
      const sample = document.createElement("p"); sample.textContent = `${item.current_orders} current orders compared with ${item.baseline_orders} orders across ${item.baseline_windows} historical minutes.`;
      card.append(title, evidence, detail, sample); $("anomaly-items").append(card);
    });
  }

  async function refresh() {
    if (state.controller) state.controller.abort();
    const controller = new AbortController(); state.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 15000);
    $("metrics").setAttribute("aria-busy", "true");
    $("refresh").disabled = true; $("previous").disabled = true; $("next").disabled = true;
    $("alerts-previous").disabled = true; $("alerts-next").disabled = true;
    const end = (Math.floor(Date.now() / 60000) + 1) * 60000;
    const start = end - state.hours * 3600000;
    const params = {start: new Date(start).toISOString(), end: new Date(end).toISOString()};
    try {
      const [summary, rows, breakdown, anomalies] = await Promise.all([
        get("/api/v1/metrics/summary", params, controller.signal),
        getWindows(params, controller.signal),
        get("/api/v1/metrics/breakdown", {...params, dimension: state.dimension, limit: 5, offset: state.offset}, controller.signal),
        get("/api/v1/anomalies", {...params, limit: 5, offset: state.alertOffset}, controller.signal).catch(() => null),
      ]);
      if (controller !== state.controller) return;
      render(summary, rows, breakdown, start, end);
      renderAnomalies(anomalies);
      state.hasData = true; $("error").hidden = true;
    } catch (error) {
      if (controller !== state.controller) return;
      status("offline", "Refresh unavailable");
      $("anomaly-status").textContent = "Not refreshed. Any signals below belong to the last successful view.";
      $("error").textContent = `Unable to refresh analytics. ${state.hasData ? "The values below are from the last successful view and may use earlier filters." : "No analytics have loaded yet."} Check the services and try Refresh.`;
      $("error").hidden = false;
      if (!state.hasData) {
        $("revenue-chart").textContent = "Analytics unavailable";
        $("revenue-chart").setAttribute("aria-label", "Analytics unavailable");
        $("performance-body").replaceChildren();
        const row = document.createElement("tr"), cell = document.createElement("td");
        cell.colSpan = 5; cell.className = "empty-cell"; cell.textContent = "Analytics unavailable";
        row.append(cell); $("performance-body").append(row);
      }
      $("previous").disabled = state.offset === 0;
    } finally {
      clearTimeout(timeout);
      if (controller === state.controller) {
        state.controller = null; $("refresh").disabled = false;
        $("metrics").setAttribute("aria-busy", "false");
      }
    }
  }
  document.querySelectorAll("[data-hours]").forEach(button => button.addEventListener("click", () => {
    state.hours = Number(button.dataset.hours); state.offset = 0; state.alertOffset = 0;
    document.querySelectorAll("[data-hours]").forEach(item => {
      const selected = item === button; item.classList.toggle("selected", selected); item.setAttribute("aria-pressed", selected);
    });
    refresh();
  }));
  document.querySelectorAll("[data-dimension]").forEach(button => button.addEventListener("click", () => {
    state.dimension = button.dataset.dimension; state.offset = 0;
    document.querySelectorAll("[data-dimension]").forEach(item => {
      const selected = item === button; item.classList.toggle("selected", selected); item.setAttribute("aria-pressed", selected);
    });
    refresh();
  }));
  $("previous").addEventListener("click", () => {state.offset = Math.max(0, state.offset - 5); refresh();});
  $("next").addEventListener("click", () => {state.offset += 5; refresh();});
  $("refresh").addEventListener("click", refresh);
  $("alerts-previous").addEventListener("click", () => {state.alertOffset = Math.max(0, state.alertOffset - 5); refresh();});
  $("alerts-next").addEventListener("click", () => {state.alertOffset += 5; refresh();});
  new ResizeObserver(() => {if (state.chartData) drawChart(...state.chartData);}).observe($("revenue-chart"));
  setInterval(() => {if ($("auto-refresh").checked && !document.hidden && !state.controller) refresh();}, 15000);
  refresh();
})();
