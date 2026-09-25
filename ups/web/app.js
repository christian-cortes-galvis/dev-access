/* UPS dashboard: live state, animated battery, history charts and events. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const LIVE_RANGES = new Set(["1h", "6h", "24h"]);
  const MAX_POINTS = 900;
  const DEFAULT_METRICS = ["battery_charge", "battery_runtime", "ups_load", "input_voltage", "battery_voltage"];
  const FALLBACK_COLORS = {
    battery_charge: "#34d399",
    battery_runtime: "#60a5fa",
    ups_load: "#fbbf24",
    input_voltage: "#a78bfa",
    battery_voltage: "#22d3ee",
  };
  const FALLBACK_RANGES = ["1h", "6h", "24h", "7d", "30d"];

  const state = {
    meta: null,
    summary: null,
    range: "24h",
    charts: {},
    nominalPower: 900,
    wsConnected: false,
    view: "dashboard",
    theme: localStorage.getItem("nut-theme") || "dark",
    metricKeys: DEFAULT_METRICS,
    colors: Object.assign({}, FALLBACK_COLORS),
  };

  function statusFromTokens(status) {
    const s = (status || "").toUpperCase();
    if (!s) return { label: "DESCONOCIDO", className: "muted" };
    const tokens = new Set(s.split());
    if (tokens.has("OB") || tokens.has("DISCHRG")) return { label: "EN BATERÍA", className: "warn" };
    if (tokens.has("LB")) return { label: "BATERÍA BAJA", className: "bad" };
    if (tokens.has("OFF") || tokens.has("FSD") || tokens.has("OL") === false && tokens.has("CHRG") === false && tokens.size === 0) return { label: "SIN CONEXIÓN", className: "bad" };
    if (tokens.has("OVER") || tokens.has("ALARM")) return { label: "CRÍTICO", className: "bad" };
    if (tokens.has("BOOST") || tokens.has("TRIM") || tokens.has("BYPASS")) return { label: "ADVERTENCIA", className: "warn" };
    return { label: "EN LÍNEA", className: "ok" };
  }

  function fmtTime(ts, range) {
    const d = new Date(ts * 1000);
    if (range === "1h") return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    if (range === "6h" || range === "24h") return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  const fmtFull = (ts) => new Date(ts * 1000).toLocaleString();
  function relTime(ts) {
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 5) return "ahora";
    if (s < 60) return `hace ${s} s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `hace ${m} min`;
    const h = Math.floor(m / 60);
    if (h < 24) return `hace ${h} h`;
    return `hace ${Math.floor(h / 24)} d`;
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("nut-theme", theme);
    state.theme = theme;
    Object.values(state.charts).forEach((c) => {
      if (!c || !c.options) return;
      c.options.scales.x.ticks.color = cssVar("--muted");
      c.options.scales.y.ticks.color = cssVar("--muted");
      c.options.scales.x.grid.color = cssVar("--line");
      c.options.scales.y.grid.color = cssVar("--line");
      c.options.plugins.legend.labels.color = cssVar("--muted");
      c.update("none");
    });
  }

  function updateBattery(s) {
    const charge = Number(s.battery_charge);
    const fill = $("battFill");
    if (Number.isFinite(charge)) {
      const low = s.charge_low ?? 10;
      const warn = s.charge_warning ?? 50;
      fill.style.height = clamp(charge, 0, 100) + "%";
      fill.classList.toggle("bad", charge <= low);
      fill.classList.toggle("warn", charge > low && charge <= warn);
      fill.classList.toggle("ok", charge > warn);
      $("battPct").textContent = Math.round(charge) + "%";
    }
    const onBattery = (s.status || "").includes("OB") || (s.status || "").includes("LB");
    $("batt").classList.toggle("pulse", onBattery || s.status_class === "bad");
    $("runtime").textContent = s.runtime_human || "--:--:--";
    $("runtimeSub").textContent = s.watts_est ? `Basado en consumo actual de ${Math.round(s.watts_est)} W` : "Basado en consumo actual.";
    $("heroStatus").textContent = s.status_label || "—";
    $("inputVoltage").textContent = s.input_voltage != null ? `${Number(s.input_voltage).toFixed(0)} V` : "—";
    $("loadValue").textContent = s.load != null ? `${Number(s.load).toFixed(0)}%` : "—";
  }

  function renderMarks(s) {
    const marks = $("battMarks");
    marks.innerHTML = "";
    const thresholds = [
      [s.charge_low ?? 10, "baja"],
      [s.charge_warning ?? 50, "alerta"],
    ];
    thresholds.forEach(([value, label]) => {
      const el = document.createElement("div");
      el.className = "mark";
      const span = document.createElement("span");
      span.textContent = label;
      el.appendChild(span);
      el.style.bottom = clamp(value, 0, 100) + "%";
      marks.appendChild(el);
    });
  }

  const KPI_DEFS = [
    { key: "battery_charge", label: "Batería", unit: "%", decimals: 0, bar: "floor", accent: "battery_charge", sub: (s) => (s.battery_charge != null ? `${s.battery_charge.toFixed(0)}% disponible` : "Estado de batería") },
    { key: "load", label: "Carga", unit: "%", decimals: 0, bar: "ceil", barWarn: 70, barBad: 90, accent: "ups_load", sub: (s) => (s.load != null ? `${s.load.toFixed(0)}% de capacidad` : "Carga actual") },
    { key: "watts_est", label: "Potencia", unit: "W", decimals: 0, accent: "ups_load", sub: (s) => (s.realpower_nominal ? `${s.realpower_nominal} W nominal` : "Consumo") },
    { key: "input_voltage", label: "Entrada", unit: "V", decimals: 1, accent: "input_voltage", sub: (s) => (s.transfer_low && s.transfer_high ? `${s.transfer_low}–${s.transfer_high} V de rango` : "Voltaje de entrada") },
  ];

  function valueFor(def, s) {
    if (def.key === "load") return s.load;
    return s[def.key];
  }

  function renderKpis() {
    const host = $("kpis");
    host.innerHTML = "";
    KPI_DEFS.forEach((def, i) => {
      const card = document.createElement("div");
      card.className = "k";
      card.id = `kpi-${def.key}`;
      card.style.animationDelay = `${i * 35}ms`;

      const label = document.createElement("span");
      label.className = "k-label";
      if (def.accent) {
        const dot = document.createElement("i");
        dot.className = "dot";
        dot.style.background = state.colors[def.accent] || cssVar("--accent");
        label.appendChild(dot);
      }
      label.appendChild(document.createTextNode(def.label));

      const wrap = document.createElement("div");
      wrap.className = "k-value-wrap";
      const val = document.createElement("span");
      val.dataset.val = "";
      val.textContent = "—";
      wrap.appendChild(val);
      if (def.unit) {
        const unit = document.createElement("span");
        unit.className = "k-unit";
        unit.textContent = def.unit;
        wrap.appendChild(unit);
      }

      const sub = document.createElement("span");
      sub.className = "k-sub";
      sub.dataset.sub = "";

      card.append(label, wrap, sub);
      if (def.bar) {
        const bar = document.createElement("div");
        bar.className = "bar";
        const fill = document.createElement("span");
        fill.dataset.bar = "";
        bar.appendChild(fill);
        card.appendChild(bar);
      }
      host.appendChild(card);
    });
  }

  function setNumber(el, value, decimals) {
    if (typeof value !== "number" || !isFinite(value)) return;
    const from = typeof el._val === "number" ? el._val : 0;
    const to = value;
    el._val = to;
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - start) / 650);
      el.textContent = (from + (to - from) * p).toFixed(decimals || 0);
      if (p < 1) requestAnimationFrame(tick);
    };
    tick(start);
  }

  function updateKpis(s) {
    KPI_DEFS.forEach((def) => {
      const card = $("kpi-" + def.key);
      if (!card) return;
      const value = valueFor(def, s);
      const valEl = card.querySelector("[data-val]");
      if (typeof value === "number") setNumber(valEl, value, def.decimals);
      else valEl.textContent = "—";

      const subEl = card.querySelector("[data-sub]");
      if (subEl) subEl.textContent = typeof def.sub === "function" ? def.sub(s) : "";

      if (def.bar) {
        const fill = card.querySelector("[data-bar]");
        const pct = clamp(Number(value) || 0, 0, 100);
        let cls = "ok";
        if (pct >= (def.barBad ?? 90)) cls = "bad";
        else if (pct >= (def.barWarn ?? 70)) cls = "warn";
        fill.classList.remove("ok", "warn", "bad");
        fill.classList.add(cls);
        requestAnimationFrame(() => { fill.style.width = pct + "%"; });
      }
    });
  }

  function updateHeader(s) {
    $("model").textContent = s.model || "UPS";
    const bits = [s.mfr, s.firmware ? `fw ${s.firmware}` : null, s.serial].filter(Boolean);
    $("sub").textContent = bits.join(" · ") || "UPS";

    const status = statusFromTokens(s.status || s.status_label);
    const badge = $("statusBadge");
    badge.dataset.class = status.className;
    $("statusText").textContent = status.label;
    document.body.dataset.status = status.className;
    $("statusLabel").textContent = status.label;
    $("powerFlowState").textContent = status.label;
    $("lastSeen").textContent = s.ts ? relTime(s.ts) : "—";
    $("footMeta").textContent = s.model ? `${s.model} · ${status.label}` : "—";

    const usbState = s.ts && !s.stale ? "Conectado" : "Desconectado";
    $("usbState").textContent = usbState;
    $("nutState").textContent = s.ts && !s.stale ? "En marcha" : "Desconectado";
    $("pveState").textContent = "No monitoreado";
  }

  function updatePowerFlow(s) {
    const status = statusFromTokens(s.status || s.status_label);
    const gridValue = s.input_voltage != null ? `${Number(s.input_voltage).toFixed(0)} V` : "—";
    const batteryValue = s.battery_charge != null ? `${Number(s.battery_charge).toFixed(0)}%` : "—";
    const loadValue = s.watts_est != null ? `${Math.round(s.watts_est)} W` : (s.load != null ? `${Number(s.load).toFixed(0)}%` : "—");

    $("flowGrid").textContent = gridValue;
    $("flowBattery").textContent = batteryValue;
    $("flowLoad").textContent = loadValue;

    $("powerFlow").dataset.mode = status.className;
    const powerFlowState = $("powerFlowState");
    powerFlowState.textContent = status.label;
    powerFlowState.style.color = status.className === "bad" ? cssVar("--bad") : status.className === "warn" ? cssVar("--warn") : cssVar("--ok");
  }

  function renderSystemStatus(s) {
    const status = statusFromTokens(s.status || s.status_label);
    const items = [
      ["UPS", status.label],
      ["NUT", s.ts && !s.stale ? "En marcha" : "Desconectado"],
      ["PVE", "No monitoreado"],
      ["PBS", "No monitoreado"],
      ["Almacenamiento", "No monitoreado"],
    ];

    const host = $("systemStatus");
    host.innerHTML = items.map(([name, value]) => {
      const cls = value === "En marcha" || value === "En línea" || value === "Conectado" ? "state" : value === "Desconectado" ? "state bad" : "state muted";
      return `<li><span>${name}</span><span class="${cls}">${value}</span></li>`;
    }).join("");
  }

  function renderHealth(s) {
    const status = statusFromTokens(s.status || s.status_label);
    const wrap = $("healthState");
    wrap.classList.remove("warning", "bad");
    const summary = $("healthSummary");
    if (status.className === "warn") {
      wrap.classList.add("warning");
      $("healthState").querySelector(".health-pill").textContent = "ADVERTENCIA";
      summary.textContent = "La UPS opera con batería o con carga elevada.";
    } else if (status.className === "bad") {
      wrap.classList.add("bad");
      $("healthState").querySelector(".health-pill").textContent = "CRÍTICO";
      summary.textContent = "La autonomía es limitada o la UPS está degradada.";
    } else {
      $("healthState").querySelector(".health-pill").textContent = "SALUDABLE";
      summary.textContent = "La UPS funciona con normalidad.";
    }
  }

  function renderDiagnostics(s) {
    const host = $("diagnostics");
    const rows = [
      ["Modelo", s.model || "—"],
      ["Fabricante", s.mfr || "—"],
      ["N.º de serie", s.serial || "—"],
      ["Firmware", s.firmware || "—"],
      ["Voltaje de batería", s.battery_voltage != null ? `${Number(s.battery_voltage).toFixed(1)} V` : "—"],
      ["Voltaje nominal", s.input_voltage_nominal ? `${Number(s.input_voltage_nominal).toFixed(0)} V` : "—"],
      ["Voltaje de entrada", s.input_voltage != null ? `${Number(s.input_voltage).toFixed(0)} V` : "—"],
      ["Transferencia baja", s.transfer_low != null ? `${Number(s.transfer_low).toFixed(0)} V` : "—"],
      ["Transferencia alta", s.transfer_high != null ? `${Number(s.transfer_high).toFixed(0)} V` : "—"],
      ["Potencia nominal", s.realpower_nominal ? `${s.realpower_nominal} W` : "—"],
      ["Estado", s.status_label || "Desconocido"],
    ];
    host.innerHTML = rows.map(([label, value]) => `
      <div class="diag-item">
        <span>${label}</span>
        <strong>${value}</strong>
      </div>
    `).join("");
  }

  function updateSummary(s) {
    state.summary = s;
    state.nominalPower = s.realpower_nominal || state.nominalPower;
    updateHeader(s);
    updateBattery(s);
    renderMarks(s);
    updateKpis(s);
    updatePowerFlow(s);
    renderSystemStatus(s);
    renderHealth(s);
    renderDiagnostics(s);

    const banner = $("banner");
    if (s.stale) {
      banner.className = "banner";
      banner.textContent = `Sin datos recientes${s.last_seen ? ` · última lectura ${fmtFull(s.last_seen)}` : ""}.`;
    } else if (s.error && s.error.message) {
      banner.className = "banner error";
      banner.textContent = `Error al leer la UPS: ${s.error.message}`;
    } else {
      banner.className = "banner hidden";
    }
  }

  const thresholdPlugin = {
    id: "thresholds",
    afterDatasetsDraw(chart, _args, opts) {
      const { ctx, chartArea, scales } = chart;
      [[opts.low, cssVar("--bad")], [opts.warn, cssVar("--warn")]].forEach(([value, color]) => {
        if (value == null || !scales.y) return;
        const y = scales.y.getPixelForValue(value);
        if (y < chartArea.top || y > chartArea.bottom) return;
        ctx.save();
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(chartArea.left, y);
        ctx.lineTo(chartArea.right, y);
        ctx.stroke();
        ctx.restore();
      });
    },
  };
  Chart.register(thresholdPlugin);

  function baseOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 650, easing: "easeOutQuart" },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: cssVar("--muted"), boxWidth: 12, boxHeight: 12, usePointStyle: true } },
        tooltip: {
          backgroundColor: cssVar("--panel-strong"),
          borderColor: cssVar("--line"),
          borderWidth: 1,
          titleColor: cssVar("--txt"),
          bodyColor: cssVar("--txt"),
          padding: 10,
          cornerRadius: 8,
        },
        thresholds: { low: null, warn: null },
      },
      scales: {
        x: { ticks: { color: cssVar("--muted"), maxTicksLimit: 6, autoSkip: true }, grid: { color: cssVar("--line") }, border: { display: false } },
        y: { ticks: { color: cssVar("--muted") }, grid: { color: cssVar("--line") }, border: { display: false }, beginAtZero: false },
      },
    };
  }

  function makeChart(id, datasets) {
    return new Chart($(id).getContext("2d"), {
      type: "line",
      data: { labels: [], datasets },
      options: baseOptions(),
    });
  }

  function ds(label, color) {
    return { label, data: [], borderColor: color, backgroundColor: color + "26", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2, spanGaps: true };
  }

  function buildCharts() {
    const c = state.colors;
    state.charts.charge = makeChart("chartCharge", [ds("Batería", c.battery_charge)]);
    state.charts.runtime = makeChart("chartRuntime", [ds("Autonomía", c.battery_runtime)]);
    state.charts.load = makeChart("chartLoad", [ds("Consumo", c.ups_load)]);
    state.charts.volt = makeChart("chartVolt", [ds("Entrada", c.input_voltage), ds("Batería", c.battery_voltage)]);
  }

  function align(times, points, transform) {
    const map = new Map((points || []).map((p) => [p[0], p[1]]));
    return times.map((t) => {
      if (!map.has(t)) return null;
      const v = map.get(t);
      return transform ? transform(v) : v;
    });
  }

  function downsample(times, series, max) {
    const n = times.length;
    if (n <= max) return { times, series };
    const step = Math.ceil(n / max);
    const idx = [];
    for (let i = 0; i < n; i += step) idx.push(i);
    const out = {};
    Object.keys(series).forEach((k) => (out[k] = idx.map((i) => series[k][i])));
    return { times: idx.map((i) => times[i]), series: out };
  }

  async function loadHistory() {
    const range = state.range;
    const keys = state.metricKeys;
    const results = await Promise.all(
      keys.map((m) => fetch(`/api/history?metric=${m}&range=${range}`).then((r) => r.json()).catch(() => ({ points: [] })))
    );
    const data = {};
    keys.forEach((m, i) => (data[m] = (results[i] && results[i].points) || []));
    const base = keys.reduce((a, m) => (data[m].length > data[a].length ? m : a), keys[0]);
    const times = (data[base] || []).map((p) => p[0]);
    const power = state.nominalPower;
    const raw = {
      battery_charge: align(times, data.battery_charge),
      battery_runtime: align(times, data.battery_runtime, (v) => v / 60),
      ups_load: align(times, data.ups_load, (v) => (v * power) / 100),
      input_voltage: align(times, data.input_voltage),
      battery_voltage: align(times, data.battery_voltage),
    };
    const picked = downsample(times, raw, MAX_POINTS);
    const labels = picked.times.map((t) => fmtTime(t, range));
    const C = state.charts;

    C.charge.data.labels = labels.slice();
    C.charge.data.datasets[0].data = picked.series.battery_charge;
    C.charge.options.plugins.thresholds = {
      low: state.summary?.charge_low ?? state.meta?.thresholds?.charge_low ?? 10,
      warn: state.summary?.charge_warning ?? state.meta?.thresholds?.charge_warning ?? 50,
    };

    C.runtime.data.labels = labels.slice();
    C.runtime.data.datasets[0].data = picked.series.battery_runtime;

    C.load.data.labels = labels.slice();
    C.load.data.datasets[0].data = picked.series.ups_load;

    C.volt.data.labels = labels.slice();
    C.volt.data.datasets[0].data = picked.series.input_voltage;
    C.volt.data.datasets[1].data = picked.series.battery_voltage;

    Object.values(C).forEach((c) => c && c.update());
    const total = picked.times.length;
    const resolution = results[0] && results[0].resolution === "hourly" ? "por hora" : "brutos";
    $("chartHint").textContent = total ? `${total} puntos · datos ${resolution}` : "Recopilando datos…";
  }

  function pushLive(s) {
    if (!LIVE_RANGES.has(state.range) || !state.charts.charge) return;
    const label = fmtTime(s.ts, state.range);
    const power = state.nominalPower;
    const series = [
      [state.charts.charge, [s.battery_charge]],
      [state.charts.runtime, [typeof s.runtime_s === "number" ? s.runtime_s / 60 : null]],
      [state.charts.load, [typeof s.load === "number" ? (s.load * power) / 100 : null]],
      [state.charts.volt, [s.input_voltage, s.battery_voltage]],
    ];
    series.forEach(([chart, vals]) => {
      const labels = chart.data.labels;
      if (labels[labels.length - 1] === label) return;
      labels.push(label);
      chart.data.datasets.forEach((d, i) => d.data.push(vals[i]));
      while (labels.length > MAX_POINTS) {
        labels.shift();
        chart.data.datasets.forEach((d) => d.data.shift());
      }
      chart.update();
    });
  }

  const classColor = (cls) => cssVar(cls === "bad" ? "--bad" : cls === "warn" ? "--warn" : "--ok");

  function renderEvents(rows) {
    const host = $("events");
    host.textContent = "";
    if (!rows || !rows.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Sin eventos en este periodo.";
      host.appendChild(empty);
      return;
    }

    rows.forEach((e) => {
      const row = document.createElement("div");
      row.className = "event";
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.style.background = classColor(e.to_class || "ok");
      const stateText = document.createElement("strong");
      stateText.textContent = e.to_status || "—";
      const time = document.createElement("time");
      time.textContent = fmtFull(e.ts);
      row.append(chip, stateText, time);
      host.appendChild(row);
    });
  }

  async function loadEvents() {
    try {
      const res = await fetch(`/api/events?range=${state.range}`).then((r) => r.json());
      renderEvents(res.events);
    } catch (_) {
      renderEvents([]);
    }
  }

  function renderRanges() {
    const host = $("ranges");
    host.textContent = "";
    (state.meta?.ranges || FALLBACK_RANGES).forEach((r) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = r;
      b.className = r === state.range ? "active" : "";
      b.addEventListener("click", () => {
        state.range = r;
        [...host.children].forEach((c) => c.classList.toggle("active", c.textContent === r));
        loadHistory();
        loadEvents();
      });
      host.appendChild(b);
    });
  }

  function showView(view) {
    state.view = view;
    document.querySelectorAll("main [data-view]").forEach((el) => {
      el.classList.toggle("hidden", el.dataset.view !== view);
    });
    document.querySelectorAll(".nav-link").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === view);
    });
    if (view === "history") {
      loadHistory().then(() => Object.values(state.charts).forEach((c) => c && c.resize()));
    } else if (view === "events") {
      loadEvents();
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    let ws;
    try {
      ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    } catch (_) {
      return;
    }
    ws.onopen = () => { state.wsConnected = true; $("nutState").textContent = "En marcha"; };
    ws.onmessage = (ev) => {
      try {
        const s = JSON.parse(ev.data);
        updateSummary(s);
        pushLive(s);
      } catch (_) {}
    };
    ws.onclose = () => {
      state.wsConnected = false;
      $("nutState").textContent = "Desconectado";
      setTimeout(connect, 5000);
    };
    ws.onerror = () => ws.close();
  }

  async function refreshSummary() {
    try {
      const s = await fetch("/api/summary").then((r) => r.json());
      if (s && s.ts) updateSummary(s);
      else {
        const b = $("banner");
        b.className = "banner";
        b.textContent = "Conectando con la UPS… esperando la primera lectura.";
      }
    } catch (_) {}
  }

  function tickLastSeen() {
    const seen = $("lastSeen");
    if (!state.summary || !state.summary.ts) return;
    seen.textContent = relTime(state.summary.ts);
  }

  async function init() {
    applyTheme(state.theme);
    try {
      state.meta = await fetch("/api/meta").then((r) => r.json());
    } catch (_) {
      state.meta = null;
    }
    if (state.meta?.metrics?.length) {
      state.metricKeys = state.meta.metrics.map((m) => m.key);
      state.meta.metrics.forEach((m) => {
        if (m.color) state.colors[m.key] = m.color;
      });
    } else {
      state.metricKeys = DEFAULT_METRICS;
    }

    renderKpis();
    buildCharts();
    renderRanges();
    document.querySelectorAll(".nav-link").forEach((b) => {
      b.addEventListener("click", () => showView(b.dataset.view));
    });
    showView("dashboard");
    await Promise.all([refreshSummary(), loadHistory(), loadEvents()]);
    connect();
    setInterval(() => { if (!state.wsConnected) refreshSummary(); }, 30000);
    setInterval(() => { loadHistory(); loadEvents(); }, 300000);
    setInterval(tickLastSeen, 1000);
  }

  $("themeBtn").addEventListener("click", () => applyTheme(state.theme === "dark" ? "light" : "dark"));
  document.addEventListener("DOMContentLoaded", init);
})();
