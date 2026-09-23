/* Skinova simulator SPA — therapy + acoustic bowl. Labels via i18n only. */
(function () {
  const LANG_KEY = "skinova_lang";
  const THEME_KEY = "skinova_theme";
  const SETTINGS_COLLAPSE_KEY = "usim.settingsCollapsed";
  let i18n = window.__I18N__ || {};
  let lang = localStorage.getItem(LANG_KEY) || window.__LANG__ || "de";
  let programs = [];
  let socHist = [], fsmHist = [], burstHist = [];
  let therapyCharts = {};
  let bowlCharts = {};
  let bowlInited = false;
  let bowlEnergyCache = { start: null, end: null };
  let bowlEnergyPhase = "end";
  let bowlAnalyzeBusy = false;
  let bowlAbort = null;
  let bowlTempsBusy = false;
  let bowlTempsAbort = null;
  let bowlEnergyBusy = false;
  let bowlEnergyAbort = null;
  let bowlFreqCompareBusy = false;
  let bowlFreqCompareAbort = null;
  let bowlFreqCompareCache = null;

  function $(id) { return document.getElementById(id); }
  function t(key) {
    let cur = i18n;
    for (const p of key.split(".")) {
      if (!cur || typeof cur !== "object" || !(p in cur)) return key;
      cur = cur[p];
    }
    return typeof cur === "string" ? cur : key;
  }
  function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const v = t(el.getAttribute("data-i18n"));
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") el.placeholder = v;
      else el.textContent = v;
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.title = t(el.getAttribute("data-i18n-title"));
    });
    document.title = t("app.title");
    document.querySelectorAll(".lang-btn").forEach((b) => b.classList.toggle("active", b.dataset.lang === lang));
  }
  function cssVar(n, fb) {
    return getComputedStyle(document.body).getPropertyValue(n).trim() || fb;
  }
  function chartTheme() {
    Chart.defaults.color = cssVar("--text", "#e8eef7");
    Chart.defaults.borderColor = cssVar("--chart-grid", "rgba(255,255,255,0.08)");
    Chart.defaults.font.size = 12;
  }
  async function postJSON(url, body, signal) {
    const opts = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) };
    if (signal) opts.signal = signal;
    const r = await fetch(url, opts);
    return r.json();
  }
  async function getJSON(url, signal) {
    const r = await fetch(url, signal ? { signal } : undefined);
    return r.json();
  }
  function lineChart(id, label, color) {
    const el = $(id);
    if (!el) return null;
    return new Chart(el, {
      type: "line",
      data: { labels: [], datasets: [{ label, data: [], borderColor: color, backgroundColor: "transparent", borderWidth: 2.5, pointRadius: 0, tension: 0.15 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: true } },
        scales: {
          x: { title: { display: true, text: "" }, ticks: { maxTicksLimit: 8 }, grid: { color: Chart.defaults.borderColor } },
          y: { title: { display: true, text: "" }, grid: { color: Chart.defaults.borderColor } },
        },
      },
    });
  }


  function bumpChart(ch) {
    if (!ch) return;
    try {
      if (typeof ch.stop === "function") ch.stop();
      ch.update("none");
    } catch (err) { console.warn("bumpChart", err); }
  }

  function freshArray(arr) {
    if (!Array.isArray(arr)) return [];
    return arr.map((v) => (typeof v === "number" ? v : Number(v)));
  }

  /** Destroy Chart.js instance and replace the canvas node (heals intermittent freezes). */
  function recreateLineChart(canvasId, chartKey, buildFn) {
    try {
      const prev = bowlCharts[chartKey];
      if (prev) {
        try { if (typeof prev.stop === "function") prev.stop(); } catch (_) { /* ignore */ }
        try { prev.destroy(); } catch (_) { /* ignore */ }
        bowlCharts[chartKey] = null;
      }
      const old = $(canvasId);
      if (!old || !old.parentNode) return null;
      const neu = document.createElement("canvas");
      neu.id = canvasId;
      if (old.className) neu.className = old.className;
      old.parentNode.replaceChild(neu, old);
      const ch = buildFn(neu);
      bowlCharts[chartKey] = ch;
      return ch;
    } catch (err) {
      console.warn("recreateLineChart", canvasId, err);
      return bowlCharts[chartKey] || null;
    }
  }

  function buildTempsChart(canvasEl) {
    const el = canvasEl || $("chartBowlTemps");
    if (!el) return null;
    const ch = new Chart(el, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: t("bowl.legend_t_piezo") || "T_piezo", data: [], borderColor: "#e6a817", backgroundColor: "transparent", borderWidth: 2.5, pointRadius: 0, tension: 0 },
          { label: t("bowl.legend_t_glue") || "T_glue", data: [], borderColor: "#c45c26", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0, tension: 0 },
          { label: t("bowl.legend_t_ti") || "T_Ti", data: [], borderColor: "#8a9ba8", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0, tension: 0 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        animations: false,
        transitions: { active: { animation: { duration: 0 } }, resize: { animation: { duration: 0 } } },
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: true } },
        scales: {
          x: { title: { display: true, text: t("bowl.time_s") || "t (s)" }, ticks: { maxTicksLimit: 8 }, grid: { color: Chart.defaults.borderColor } },
          y: { title: { display: true, text: "T (°C)" }, grid: { color: Chart.defaults.borderColor } },
        },
      },
    });
    return ch;
  }

  function ensureTempsChartFresh() {
    return recreateLineChart("chartBowlTemps", "temps", (el) => buildTempsChart(el));
  }

  function energyChartLabels() {
    return [
      t("bowl.p_rad") || "P_ac",
      t("bowl.p_glue") || "glue",
      t("bowl.p_piezo") || "piezo",
      t("bowl.p_ti") || "Ti",
    ];
  }

  /** Horizontal bar (more reliable than doughnut under destroy/recreate races). */
  function buildEnergyChart(canvasEl, dataArr) {
    const el = canvasEl || $("chartBowlEnergy");
    if (!el) return null;
    try {
      const existing = (typeof Chart.getChart === "function") ? Chart.getChart(el) : null;
      if (existing) { try { existing.destroy(); } catch (_) { /* ignore */ } }
    } catch (_) { /* ignore */ }
    const data = Array.isArray(dataArr) ? dataArr.slice() : [0.25, 0.25, 0.25, 0.25];
    return new Chart(el, {
      type: "bar",
      data: {
        labels: energyChartLabels(),
        datasets: [{
          label: t("bowl.energy_share") || "W",
          data: data,
          backgroundColor: ["#2dd4a8", "#c45c26", "#e6a817", "#8a9ba8"],
          borderWidth: 1,
          borderColor: "#151d2c",
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        animations: false,
        transitions: { active: { animation: { duration: 0 } }, resize: { animation: { duration: 0 } } },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label(ctx) {
                const v = Number(ctx.raw) || 0;
                const sum = (ctx.dataset.data || []).reduce((a, b) => a + (Number(b) || 0), 0) || 1;
                const pct = (100 * v / sum).toFixed(1);
                return `${ctx.label}: ${v.toFixed(4)} W (${pct} %)`;
              },
            },
          },
        },
        scales: {
          x: { beginAtZero: true, title: { display: true, text: "W" }, grid: { color: Chart.defaults.borderColor } },
          y: { grid: { display: false } },
        },
      },
    });
  }

  function ensureEnergyChartFresh(dataArr) {
    return recreateLineChart("chartBowlEnergy", "energy", (el) => buildEnergyChart(el, dataArr));
  }

  function initTherapyCharts() {
    chartTheme();
    therapyCharts.ix = lineChart("chartIx", "I(x)", "#3b9eff");
    therapyCharts.tx = lineChart("chartTx", "T(x)", "#2dd4a8");
    therapyCharts.dose = lineChart("chartDose", "Dose", "#ffd866");
    therapyCharts.soc = lineChart("chartSoc", "SoC", "#7fd962");
    therapyCharts.burst = lineChart("chartBurst", "Burst", "#f07178");
    therapyCharts.fsm = lineChart("chartFsm", "FSM", "#c084fc");
    if (therapyCharts.ix) {
      therapyCharts.ix.options.scales.x.title.text = "x (mm)";
      therapyCharts.ix.options.scales.y.title.text = "I (W/cm²)";
      therapyCharts.tx.options.scales.x.title.text = "x (mm)";
      therapyCharts.tx.options.scales.y.title.text = "T (°C)";
      therapyCharts.dose.options.scales.x.title.text = "x (mm)";
    }
  }

  function settingsPayload() {
    const payload = {
      model: $("modelSelect").value,
      program_id: parseInt($("programSelect").value || "1", 10),
      duration_s: parseFloat($("durationS").value),
      mode: $("modeSelect").value,
      i_set: parseFloat($("iSata").value),
      prf_hz: parseFloat($("prfHz").value),
      duty_interpretation: $("dutyInterp").value,
      limit_domain: $("limitDomain").value,
      c0_nF: parseFloat($("c0nF").value),
      vdrive_peak_v: parseFloat($("vdrive").value),
      pcb_drive_v: parseFloat(($("pcbDriveV") || $("vdrive")).value),
      eta_elec: parseFloat($("etaElec").value),
      drive_level: parseFloat(($("driveLevel") || { value: 1 }).value),
      p_elec_max_w: parseFloat(($("pElecMax") || { value: 8 }).value),
      i_sense_window_ms: parseFloat(($("iSenseWindow") || { value: 2 }).value),
      stack_efficiency: parseFloat($("stackEff").value),
      gel_present: $("gelPresent").checked,
      force_n: parseFloat($("forceN").value),
      enable_2d: $("enable2d").checked,
      path: $("pathSelect").value,
      dt_macro_s: parseFloat($("dtMacro").value) / 1000,
      seed: parseInt($("seed").value, 10),
      t_warn_c: parseFloat($("tWarn").value),
      t_off_c: parseFloat($("tOff").value),
      motion_still_s: parseFloat($("motionStill").value),
      motion_eps: parseFloat($("motionEps").value),
      bat_capacity_wh: parseFloat($("batCap").value),
      f0_hz: parseFloat($("f0Select").value),
    };
    if ($("kEff2")) payload.k_eff2 = parseFloat($("kEff2").value);
    if ($("qMAir")) payload.q_m_air = parseFloat($("qMAir").value);
    if ($("qMGel")) payload.q_m_gel = parseFloat($("qMGel").value);
    if ($("alphaN")) payload.alpha_power_n = parseFloat($("alphaN").value);
    return payload;
  }

  async function setLang(code) {
    lang = code;
    localStorage.setItem(LANG_KEY, code);
    const keep = settingsPayload();
    i18n = await (await fetch("/api/i18n/" + code)).json();
    applyI18n();
    updateCollapseLabels(isSettingsCollapsed());
    // restore a few fields that i18n might touch
    $("modelSelect").value = keep.model;
    $("gelPresent").checked = keep.gel_present;
    $("pathSelect").value = keep.path;
    await loadPrograms();
    if (bowlInited) labelBowl();
    const url = new URL(location.href);
    url.searchParams.set("lang", code);
    history.replaceState(null, "", url);
  }

  async function loadPrograms() {
    const model = $("modelSelect").value;
    const data = await (await fetch("/api/programs?model=" + encodeURIComponent(model))).json();
    programs = data.programs || [];
    const sel = $("programSelect");
    const prev = sel.value;
    sel.innerHTML = "";
    programs.forEach((p) => {
      const o = document.createElement("option");
      o.value = p.id;
      o.textContent = p.id + ". " + p.name;
      sel.appendChild(o);
    });
    if (prev) sel.value = prev;
    onProgramChange();
  }

  function onProgramChange() {
    const id = parseInt($("programSelect").value, 10);
    const p = programs.find((x) => x.id === id);
    if (!p) return;
    $("durationS").value = p.duration_s;
    $("modeSelect").value = p.mode;
    $("iSata").value = p.i_sata_w_cm2;
    $("prfHz").value = p.prf_hz || 100;
    $("zones").value = (p.zones || []).join(", ");
  }

  function updateTherapyCharts(snap) {
    if (!snap || !therapyCharts.ix) return;
    const x = (snap.x_mm || []).map((v) => Number(v).toFixed(2));
    function put(ch, data, label, useX) {
      ch.data.labels = useX ? x : (data || []).map((_, i) => i);
      ch.data.datasets[0].data = data || [];
      ch.data.datasets[0].label = label;
      ch.update("none");
    }
    put(therapyCharts.ix, snap.i_profile, t("plots.i_x"), true);
    put(therapyCharts.tx, snap.t_profile, t("plots.t_x"), true);
    put(therapyCharts.dose, snap.dose_profile, t("plots.dose"), true);
    socHist.push(snap.soc); if (socHist.length > 160) socHist.shift();
    put(therapyCharts.soc, socHist, t("plots.soc"), false);
    burstHist.push(snap.burst_on ? 1 : 0); if (burstHist.length > 100) burstHist.shift();
    put(therapyCharts.burst, burstHist, t("plots.burst"), false);
    const fmap = { IDLE_DOCKED:0, IDLE_UNDOCKED:1, PROGRAMMED_WAIT:2, RUNNING:3, PAUSED_NO_CONTACT:4, FAULT_OVERTEMP:5, FAULT_MOTION:6, FAULT_BATTERY:7, FINISHED:8, LOCKED_NEEDS_STATION:9 };
    fsmHist.push(fmap[snap.state] ?? -1); if (fsmHist.length > 160) fsmHist.shift();
    put(therapyCharts.fsm, fsmHist, t("plots.fsm"), false);
  }

  function renderStatus(data) {
    const snap = data.snapshot;
    function set(id, v) { const el = $(id); if (el) el.textContent = v; }
    set("vState", data.state || "—");
    set("vF0", data.f0_hz ? (data.f0_hz / 1e6).toFixed(0) + " MHz" : "—");
    if (data.f0_hz && $("f0Select")) $("f0Select").value = String(Math.round(data.f0_hz));
    set("vLam", data.lambda_m ? (data.lambda_m * 1e3).toFixed(3) + " mm" : "—");
    set("vZn", data.z_n_m ? (data.z_n_m * 1e3).toFixed(1) + " mm" : "—");
    if ($("xHalf")) $("xHalf").value = data.x_half_m ? (data.x_half_m * 1e3).toFixed(2) + " mm" : "—";
    if (data.nvm) set("vTrem", (data.nvm.t_remaining_s || 0).toFixed(1) + " s");
    set("vSoc", ((data.soc || 0) * 100).toFixed(1) + " %");
    if (snap) {
      set("vR1", Number(snap.r1).toFixed(2));
      if (data.bvd) {
        set("vC1", Number(data.bvd.c1_nF).toFixed(3) + " nF");
        set("vL1", Number(data.bvd.l1_uH).toFixed(2) + " µH");
        if ($("kEff2") && data.bvd.k_eff2 != null) $("kEff2").value = data.bvd.k_eff2;
        if ($("qMAir") && data.bvd.q_m_air != null) $("qMAir").value = data.bvd.q_m_air;
        if ($("qMGel") && data.bvd.q_m_gel != null) $("qMGel").value = data.bvd.q_m_gel;
      }
      if (data.alpha_power_n != null && $("alphaN")) $("alphaN").value = data.alpha_power_n;
      set("vPac", Number(snap.p_ac).toFixed(3) + " W");
      set("vPbat", Number(snap.p_bat).toFixed(3) + " W");
      set("vContact", snap.contact ? t("yes") : t("no"));
      set("vVswr", Number(snap.vswr).toFixed(2));
      set("vTpiezo", Number(snap.t_piezo_c).toFixed(2) + " °C");
      set("vTskin", Number(snap.t_skin_surface_c).toFixed(2) + " °C");
      set("vIsata", Number(snap.i_sata).toFixed(3));
      set("vGel", (Number(snap.gel_thickness_m) * 1e3).toFixed(3) + " mm");
      updateTherapyCharts(snap);
    }
  }

  async function refresh() { renderStatus(await (await fetch("/api/status")).json()); }
  async function applySettings() { renderStatus(await postJSON("/api/settings", settingsPayload())); }

  function resizeAllCharts() {
    const all = [...Object.values(therapyCharts), ...Object.values(bowlCharts)];
    all.forEach((c) => {
      if (!c) return;
      try {
        if (typeof c.resize === "function") c.resize();
        else if (typeof c.update === "function") c.update("resize");
      } catch (_) { /* ignore */ }
    });
  }

  function switchTab(name) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    $("tab-therapy").classList.toggle("hidden", name !== "therapy");
    $("tab-bowl").classList.toggle("hidden", name !== "bowl");
    if (name === "bowl") { ensureBowl(); }
    requestAnimationFrame(() => {
      resizeAllCharts();
      requestAnimationFrame(resizeAllCharts);
      setSettingsCollapsed(document.body.classList.contains("settings-collapsed"));
    });
  }

  function mmOr(id, fallback) {
    const el = $(id);
    if (!el) return fallback;
    const v = parseFloat(el.value);
    return Number.isNaN(v) ? fallback : v;
  }

  function eraFromDiameterMm(dMm) {
    const dM = dMm * 1e-3;
    return Math.PI * (dM / 2) * (dM / 2) * 1e4;
  }

  function diameterMmFromEra(eraCm2) {
    return 2.0 * Math.sqrt((eraCm2 * 1e-4) / Math.PI) * 1e3;
  }

  function syncWallFromInnerOuter() {
    if (!$("bowlCupInnerD") || !$("bowlCupWall") || !$("bowlCupOuterD")) return;
    const outer = parseFloat($("bowlCupOuterD").value);
    const inner = parseFloat($("bowlCupInnerD").value);
    if (!Number.isNaN(inner) && !Number.isNaN(outer) && outer > inner) {
      $("bowlCupWall").value = (((outer - inner) / 2)).toFixed(2);
    } else if (!Number.isNaN(outer) && !Number.isNaN(inner) && inner >= outer) {
      const wall = Math.max(0.2, Math.min(outer * 0.08, 0.5));
      const newInner = Math.max(8, outer - 2 * wall);
      $("bowlCupInnerD").value = newInner.toFixed(2);
      $("bowlCupWall").value = (((outer - newInner) / 2)).toFixed(2);
    }
  }

  /** Link Titan-Ø ↔ cup outer; optionally refresh ERA from diameter. */
  function syncRadiatingDiameter(source) {
    const tiEl = $("bowlTiD");
    const outerEl = $("bowlCupOuterD");
    const eraEl = $("bowlEra");
    if (!tiEl) return;
    let dMm;
    if (source === "era" && eraEl) {
      const era = parseFloat(eraEl.value);
      if (Number.isNaN(era) || era <= 0) return;
      dMm = diameterMmFromEra(era);
      tiEl.value = dMm.toFixed(2);
      if (outerEl) outerEl.value = dMm.toFixed(2);
    } else if (source === "outer" && outerEl) {
      dMm = parseFloat(outerEl.value);
      if (Number.isNaN(dMm)) return;
      tiEl.value = dMm.toFixed(2);
      if (eraEl) eraEl.value = eraFromDiameterMm(dMm).toFixed(2);
    } else {
      dMm = parseFloat(tiEl.value);
      if (Number.isNaN(dMm)) return;
      if (outerEl) outerEl.value = dMm.toFixed(2);
      if (eraEl) eraEl.value = eraFromDiameterMm(dMm).toFixed(2);
    }
    syncWallFromInnerOuter();
    clampPiezoDiameter(true);
  }

  /** Piezo Ø ≤ min(inner cup, radiating Ø); show hint when clamped. */
  function clampPiezoDiameter(showHint) {
    const piezoEl = $("bowlPiezoD");
    const hint = $("bowlPiezoClampHint");
    if (!piezoEl) return;
    const piezo = parseFloat(piezoEl.value);
    const inner = mmOr("bowlCupInnerD", 18.5);
    const rad = mmOr("bowlTiD", mmOr("bowlCupOuterD", 19.54));
    const limit = Math.min(inner, rad);
    piezoEl.max = String(limit.toFixed(2));
    if (Number.isNaN(piezo)) return;
    if (piezo > limit + 1e-9) {
      piezoEl.value = limit.toFixed(1);
      if (hint && showHint) {
        hint.classList.remove("hidden");
        const tmpl = t("bowl.hint_piezo_clamp");
        hint.textContent = (tmpl && tmpl !== "bowl.hint_piezo_clamp")
          ? tmpl.replace("{limit}", limit.toFixed(1))
          : ("Piezo Ø clamped to " + limit.toFixed(1) + " mm (≤ min(inner, radiating)).");
      }
    } else if (hint && showHint !== false) {
      hint.classList.add("hidden");
    }
  }

  function syncCupRadiatorField() {
    syncRadiatingDiameter("outer");
  }

  function collectBowlParams() {
    const auto = $("bowlPiezoAuto").checked;
    const piezoH = $("bowlPiezoH").value;
    clampPiezoDiameter(false);
    const dMm = mmOr("bowlTiD", mmOr("bowlCupOuterD", 19.54));
    const era = $("bowlEra") ? mmOr("bowlEra", eraFromDiameterMm(dMm)) : eraFromDiameterMm(dMm);
    return {
      f0_hz: parseFloat($("bowlF0").value),
      drive_level: parseFloat($("bowlDrive").value),
      load: $("bowlLoad").value,
      piezo_material: $("bowlPiezoMat").value,
      glue_material: $("bowlGlueMat").value,
      face_material: $("bowlFaceMat").value,
      ti_thickness_m: parseFloat($("bowlTiH").value) * 1e-3,
      ti_bottom_thickness_m: parseFloat($("bowlTiH").value) * 1e-3,
      ti_diameter_m: dMm * 1e-3,
      cup_outer_diameter_m: dMm * 1e-3,
      cup_inner_diameter_m: mmOr("bowlCupInnerD", 18.5) * 1e-3,
      cup_wall_thickness_m: mmOr("bowlCupWall", 0.52) * 1e-3,
      cup_depth_m: mmOr("bowlCupDepth", 4) * 1e-3,
      piezo_thickness_m: auto || piezoH === "" ? null : parseFloat(piezoH) * 1e-3,
      piezo_diameter_m: parseFloat($("bowlPiezoD").value) * 1e-3,
      glue_thickness_m: parseFloat($("bowlGlueH").value) * 1e-6,
      gel_thickness_m: parseFloat($("bowlGelH").value) * 1e-3,
      matching_enabled: $("bowlMatchEn").checked,
      matching_material: $("bowlMatchMat").value,
      matching_thickness_m: parseFloat($("bowlMatchH").value) * 1e-6,
      backing: $("bowlBacking").value,
      era_cm2: era,
      kt: parseFloat($("bowlKt").value),
      spectrum_span: parseFloat($("bowlSpan").value),
      pcb_drive_v: parseFloat(($("bowlPcbV") || { value: 40 }).value),
      p_elec_max_w: parseFloat(($("bowlPElecMax") || { value: 8 }).value),
      r_wire_piezo_ohm: parseFloat(($("bowlRWire") || { value: 0.5 }).value),
      r_ti_return_ohm: parseFloat(($("bowlRTi") || { value: 0.2 }).value),
      stack_efficiency: parseFloat(($("bowlStackEff") || { value: 0.65 }).value),
      droplet_demo: !!($("bowlDroplet") && $("bowlDroplet").checked),
      t_amb_c: parseFloat(($("bowlTAmb") || { value: 25 }).value),
      t_warn_c: parseFloat(($("bowlTWarn") || { value: 55 }).value),
      t_off_c: parseFloat(($("bowlTOff") || { value: 70 }).value),
      h_conv_w_m2k: parseFloat(($("bowlHConv") || { value: 40 }).value),
      g_piezo_glue_w_k: parseFloat(($("bowlGPG") || { value: 0.35 }).value),
      g_glue_ti_w_k: parseFloat(($("bowlGGT") || { value: 0.50 }).value),
      k_glue_loss_per_c: parseFloat(($("bowlKGlueLoss") || { value: 0.025 }).value),
      k_eff_drop_per_c: parseFloat(($("bowlKEffDrop") || { value: 0.0018 }).value),
      k_kt_drop_per_c: parseFloat(($("bowlKKtDrop") || { value: 0.0006 }).value),
      derate_smooth: !!($("bowlDerateSmooth") && $("bowlDerateSmooth").checked),
      glue_spread_scenario: (($("bowlGlueSpreadScenario") || { value: "ideal" }).value || "ideal"),
      glue_coverage: Math.max(0.2, Math.min(1, (parseFloat(($("bowlGlueCoverage") || { value: 100 }).value) || 100) / 100)),
      glue_press: (($("bowlGluePress") || { value: "medium" }).value || "medium"),
      glue_cure_fraction: Math.max(0, Math.min(1, (parseFloat(($("bowlGlueCure") || { value: 100 }).value) || 100) / 100)),
      ti_face_shape: (($("bowlTiFaceShapeVal") || { value: "cup" }).value || "cup"),
      duration_s: bowlDurationSeconds(),
      dt_s: parseFloat(($("bowlDtS") || { value: 0.15 }).value),
    };
  }

  function bowlDurationSeconds() {
    const preset = ($("bowlDurationPreset") || { value: "60" }).value;
    if (preset === "custom") {
      const v = parseFloat(($("bowlDurationS") || { value: 60 }).value);
      return Math.max(1, Math.min(720, isFinite(v) ? v : 60));
    }
    const n = parseFloat(preset);
    return Math.max(1, Math.min(720, isFinite(n) ? n : 60));
  }

  function syncBowlDurationUI() {
    const preset = ($("bowlDurationPreset") || { value: "60" }).value;
    const wrap = $("bowlDurationCustomWrap");
    if (wrap) wrap.classList.toggle("hidden", preset !== "custom");
    if (preset !== "custom" && $("bowlDurationS")) {
      $("bowlDurationS").value = String(preset);
    }
  }

  function transientPayload() {
    return {
      duration_s: bowlDurationSeconds(),
      dt_s: parseFloat(($("bowlDtS") || { value: 0.15 }).value),
      t_amb_c: parseFloat(($("bowlTAmb") || { value: 25 }).value),
      t_warn_c: parseFloat(($("bowlTWarn") || { value: 55 }).value),
      t_off_c: parseFloat(($("bowlTOff") || { value: 70 }).value),
      h_conv_w_m2k: parseFloat(($("bowlHConv") || { value: 40 }).value),
      g_piezo_glue_w_k: parseFloat(($("bowlGPG") || { value: 0.35 }).value),
      g_glue_ti_w_k: parseFloat(($("bowlGGT") || { value: 0.50 }).value),
      k_glue_loss_per_c: parseFloat(($("bowlKGlueLoss") || { value: 0.025 }).value),
      k_eff_drop_per_c: parseFloat(($("bowlKEffDrop") || { value: 0.0018 }).value),
      k_kt_drop_per_c: parseFloat(($("bowlKKtDrop") || { value: 0.0006 }).value),
      derate_smooth: !!($("bowlDerateSmooth") && $("bowlDerateSmooth").checked),
    };
  }

  function bowlPayload() {
    return collectBowlParams();
  }

  function syncBowlFreqChips() {
    const v = $("bowlF0").value;
    document.querySelectorAll("#bowlFreqChips .chip").forEach((c) => {
      c.classList.toggle("active", c.dataset.f0 === v);
    });
  }

  function applyBowlParamsToForm(p) {
    if (!p) return;
    $("bowlF0").value = String(Math.round(p.f0_hz || 19e6));
    syncBowlFreqChips();
    $("bowlDrive").value = p.drive_level ?? 1;
    $("bowlDriveVal").textContent = Number(p.drive_level ?? 1).toFixed(2);
    $("bowlLoad").value = p.load || "gel_tissue";
    $("bowlPiezoMat").value = p.piezo_material || "pzt8";
    $("bowlGlueMat").value = p.glue_material || "glue_epoxy";
    if ($("bowlFaceMat")) $("bowlFaceMat").value = p.face_material || "titanium";
    $("bowlTiH").value = ((p.ti_thickness_m || 3e-4) * 1e3).toFixed(2);
    const outer = p.ti_diameter_m || p.cup_outer_diameter_m || 0.01954;
    $("bowlTiD").value = (outer * 1e3).toFixed(2);
    if ($("bowlCupOuterD")) $("bowlCupOuterD").value = (outer * 1e3).toFixed(2);
    if ($("bowlEra")) {
      const era = (p.era_cm2 != null) ? p.era_cm2 : eraFromDiameterMm(outer * 1e3);
      $("bowlEra").value = Number(era).toFixed(2);
    }
    if ($("bowlCupInnerD")) $("bowlCupInnerD").value = ((p.cup_inner_diameter_m || 0.0185) * 1e3).toFixed(2);
    if ($("bowlCupWall")) $("bowlCupWall").value = ((p.cup_wall_thickness_m || 0.00052) * 1e3).toFixed(2);
    if ($("bowlCupDepth")) $("bowlCupDepth").value = ((p.cup_depth_m || 0.004) * 1e3).toFixed(1);
    $("bowlPiezoD").value = ((p.piezo_diameter_m || 0.018) * 1e3).toFixed(1);
    clampPiezoDiameter(false);
    $("bowlGlueH").value = ((p.glue_thickness_m || 1e-5) * 1e6).toFixed(0);
    if (p.glue_spread_scenario) setGlueSpreadScenario(p.glue_spread_scenario, false);
    if (p.glue_press) setGluePress(p.glue_press, false);
    if (p.glue_cure_fraction != null) setGlueCure(Math.round(Number(p.glue_cure_fraction) * 100), false);
    if (p.ti_face_shape) setTiFaceShape(p.ti_face_shape, false);
    if (p.glue_coverage != null && $("bowlGlueCoverage")) {
      const pct = Math.round(Number(p.glue_coverage) * 100);
      $("bowlGlueCoverage").value = String(Math.max(20, Math.min(100, pct)));
      syncGlueCoverageOut();
    }
    $("bowlGelH").value = ((p.gel_thickness_m || 3e-4) * 1e3).toFixed(2);
    if ($("bowlMatchEn")) $("bowlMatchEn").checked = !!p.matching_enabled;
    if ($("bowlMatchMat") && p.matching_material) $("bowlMatchMat").value = p.matching_material;
    if ($("bowlMatchH") && p.matching_thickness_m != null) $("bowlMatchH").value = (p.matching_thickness_m * 1e6).toFixed(0);
    if ($("bowlBacking")) $("bowlBacking").value = p.backing || "air";
    if ($("bowlKt") && p.kt != null) $("bowlKt").value = p.kt;
    if ($("bowlSpan") && p.spectrum_span != null) $("bowlSpan").value = p.spectrum_span;
    if ($("bowlPcbV") && p.pcb_drive_v != null) $("bowlPcbV").value = p.pcb_drive_v;
    if ($("bowlPElecMax") && p.p_elec_max_w != null) $("bowlPElecMax").value = p.p_elec_max_w;
    syncPowerPresetChips("bowlPowerPresets", p.drive_level ?? 1);
    if ($("bowlRWire") && p.r_wire_piezo_ohm != null) $("bowlRWire").value = p.r_wire_piezo_ohm;
    if ($("bowlRTi") && p.r_ti_return_ohm != null) $("bowlRTi").value = p.r_ti_return_ohm;
    if ($("bowlStackEff") && p.stack_efficiency != null) $("bowlStackEff").value = p.stack_efficiency;
    if ($("bowlDroplet")) $("bowlDroplet").checked = !!p.droplet_demo;
    if ($("bowlTAmb") && p.t_amb_c != null) $("bowlTAmb").value = p.t_amb_c;
    if ($("bowlTWarn") && p.t_warn_c != null) $("bowlTWarn").value = p.t_warn_c;
    if ($("bowlTOff") && p.t_off_c != null) $("bowlTOff").value = p.t_off_c;
    if ($("bowlHConv") && p.h_conv_w_m2k != null) $("bowlHConv").value = p.h_conv_w_m2k;
    if ($("bowlKGlueLoss") && p.k_glue_loss_per_c != null) $("bowlKGlueLoss").value = p.k_glue_loss_per_c;
    if ($("bowlKEffDrop") && p.k_eff_drop_per_c != null) $("bowlKEffDrop").value = p.k_eff_drop_per_c;
    if ($("bowlKKtDrop") && p.k_kt_drop_per_c != null) $("bowlKKtDrop").value = p.k_kt_drop_per_c;
    if ($("bowlGPG") && p.g_piezo_glue_w_k != null) $("bowlGPG").value = p.g_piezo_glue_w_k;
    if ($("bowlGGT") && p.g_glue_ti_w_k != null) $("bowlGGT").value = p.g_glue_ti_w_k;
    if ($("bowlDerateSmooth") && p.derate_smooth != null) $("bowlDerateSmooth").checked = !!p.derate_smooth;
  }

  function ensureBowl() {
    if (bowlInited) return;
    chartTheme();
    bowlCharts.spectrum = lineChart("chartBowlSpectrum", "|T|", "#3b9eff");
    if (bowlCharts.spectrum) {
      bowlCharts.spectrum.data.datasets.push(
        { label: "|R|", data: [], borderColor: "#f07178", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent" },
        { label: "|Z|n", data: [], borderColor: "#ffd866", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent", yAxisID: "y1" }
      );
      bowlCharts.spectrum.options.scales.y1 = { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "|Z| norm" } };
      bowlCharts.spectrum.options.scales.x.title.text = "f (MHz)";
      bowlCharts.spectrum.options.scales.y.title.text = "T / R";
    }
    bowlCharts.glue = lineChart("chartBowlGlue", "P_ac", "#2dd4a8");
    if (bowlCharts.glue) {
      bowlCharts.glue.data.datasets.push({ label: "η", data: [], borderColor: "#c084fc", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent", yAxisID: "y1" });
      bowlCharts.glue.options.scales.y1 = { position: "right", min: 0, max: 1, grid: { drawOnChartArea: false }, title: { display: true, text: "η" } };
      bowlCharts.glue.options.scales.x.title.text = "glue (µm)";
      bowlCharts.glue.options.scales.y.title.text = "P_ac (W)";
    }
    bowlCharts.ti = lineChart("chartBowlTi", "T(f0)", "#3b9eff");
    if (bowlCharts.ti) {
      bowlCharts.ti.data.datasets.push({ label: "Δf", data: [], borderColor: "#ffd866", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent", yAxisID: "y1" });
      bowlCharts.ti.options.scales.y1 = { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Δf (MHz)" } };
      bowlCharts.ti.options.scales.x.title.text = "Ti (mm)";
    }
    if ($("chartBowlEnergy")) {
      bowlCharts.energy = buildEnergyChart($("chartBowlEnergy"));
    }
    bowlCharts.field = lineChart("chartBowlField", "I(z,0)", "#3b9eff");
    if (bowlCharts.field) {
      bowlCharts.field.options.scales.x.title.text = "z (mm)";
      bowlCharts.field.options.scales.y.title.text = "I (W/cm²)";
      bowlCharts.field.options.plugins.legend.display = false;
    }
    bowlCharts.dia = lineChart("chartBowlDia", "P_ac", "#2dd4a8");
    if (bowlCharts.dia) {
      bowlCharts.dia.data.datasets.push({ label: "I", data: [], borderColor: "#ffd866", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent", yAxisID: "y1" });
      bowlCharts.dia.options.scales.y1 = { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "I (W/cm²)" } };
      bowlCharts.dia.options.scales.x.title.text = "Ø (mm)";
      bowlCharts.dia.options.scales.y.title.text = "P_ac (W)";
    }
    bowlCharts.f0 = new Chart($("chartBowlF0"), {
      type: "bar",
      data: { labels: [], datasets: [
        { label: "P_ac", data: [], backgroundColor: "#2dd4a8" },
        { label: "η", data: [], backgroundColor: "#c084fc", yAxisID: "y1" },
        { label: "T_I", data: [], backgroundColor: "#3b9eff", yAxisID: "y1" },
      ]},
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: false,
        scales: {
          y: { title: { display: true, text: "P_ac (W)" }, grid: { color: Chart.defaults.borderColor } },
          y1: { position: "right", min: 0, max: 1, grid: { drawOnChartArea: false }, title: { display: true, text: "η / T_I" } },
          x: { title: { display: true, text: "f (MHz)" } },
        },
      },
    });
    bowlCharts.profile = lineChart("chartBowlProfile", "|p|", "#e6a817");
    if (bowlCharts.profile) {
      bowlCharts.profile.options.scales.x.title.text = "z (mm)";
      bowlCharts.profile.options.scales.y.title.text = "|p| (Pa)";
    }
    bowlCharts.phase = lineChart("chartBowlPhase", "∠Z", "#3b9eff");
    if (bowlCharts.phase) {
      bowlCharts.phase.data.datasets.push({ label: "∠T", data: [], borderColor: "#f07178", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent" });
      bowlCharts.phase.options.scales.x.title.text = "f (MHz)";
      bowlCharts.phase.options.scales.y.title.text = "phase (rad)";
    }
    bowlCharts.temps = buildTempsChart($("chartBowlTemps"));
    bowlCharts.pacEta = lineChart("chartBowlPacEta", "P_ac", "#2dd4a8");
    if (bowlCharts.pacEta) {
      bowlCharts.pacEta.data.datasets.push({ label: "η", data: [], borderColor: "#c084fc", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent", yAxisID: "y1" });
      bowlCharts.pacEta.options.scales.y1 = { position: "right", min: 0, max: 1, grid: { drawOnChartArea: false }, title: { display: true, text: "η" } };
      bowlCharts.pacEta.options.scales.x.title.text = "t (s)";
      bowlCharts.pacEta.options.scales.y.title.text = "P_ac (W)";
    }
    bowlCharts.derate = lineChart("chartBowlDerate", "drive", "#3b9eff");
    if (bowlCharts.derate) {
      bowlCharts.derate.data.datasets.push({ label: "derate", data: [], borderColor: "#f07178", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent" });
      bowlCharts.derate.options.scales.x.title.text = "t (s)";
      bowlCharts.derate.options.scales.y.title.text = "level";
      bowlCharts.derate.options.scales.y.min = 0;
      bowlCharts.derate.options.scales.y.max = 1.05;
    }
    bowlCharts.losses = lineChart("chartBowlLosses", "P_piezo", "#e6a817");
    if (bowlCharts.losses) {
      bowlCharts.losses.data.datasets.push(
        { label: "P_glue", data: [], borderColor: "#c45c26", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent" },
        { label: "P_Ti", data: [], borderColor: "#8a9ba8", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent" },
        { label: "glue_factor", data: [], borderColor: "#c084fc", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent", yAxisID: "y1" }
      );
      bowlCharts.losses.options.scales.y1 = { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "factor" } };
      bowlCharts.losses.options.scales.x.title.text = "t (s)";
      bowlCharts.losses.options.scales.y.title.text = "P (W)";
    }
    bowlInited = true;
    labelBowl();
    syncBowlFreqChips();
  }

  function labelBowl() {
    if (!bowlInited) return;
    if (bowlCharts.spectrum) {
      bowlCharts.spectrum.data.datasets[0].label = t("bowl.legend_t");
      bowlCharts.spectrum.data.datasets[1].label = t("bowl.legend_r");
      bowlCharts.spectrum.data.datasets[2].label = t("bowl.legend_z");
    }
    if (bowlCharts.glue) {
      bowlCharts.glue.data.datasets[0].label = t("bowl.p_ac_axis");
      bowlCharts.glue.data.datasets[1].label = t("bowl.eff_axis");
      bowlCharts.glue.options.scales.x.title.text = t("bowl.glue_um");
    }
    if (bowlCharts.f0) {
      bowlCharts.f0.data.datasets[0].label = t("bowl.p_ac_axis");
      bowlCharts.f0.data.datasets[1].label = t("bowl.eff_axis");
      if (bowlCharts.f0.data.datasets[2]) bowlCharts.f0.data.datasets[2].label = "T_I";
      bowlCharts.f0.options.scales.x.title.text = t("bowl.freq_compare_x") || "f (MHz)";
    }
    if (bowlCharts.ti) bowlCharts.ti.options.scales.x.title.text = t("bowl.ti_mm");
    try { applyEnergyDoughnut(); } catch (err) { console.warn(err); }
    if (bowlCharts.temps) {
      bowlCharts.temps.data.datasets[0].label = t("bowl.legend_t_piezo");
      bowlCharts.temps.data.datasets[1].label = t("bowl.legend_t_glue");
      bowlCharts.temps.data.datasets[2].label = t("bowl.legend_t_ti");
      bowlCharts.temps.options.scales.x.title.text = t("bowl.time_s");
    }
    if (bowlCharts.pacEta) {
      bowlCharts.pacEta.data.datasets[0].label = t("bowl.p_ac_axis");
      bowlCharts.pacEta.data.datasets[1].label = t("bowl.eff_axis");
      bowlCharts.pacEta.options.scales.x.title.text = t("bowl.time_s");
    }
    if (bowlCharts.derate) {
      bowlCharts.derate.data.datasets[0].label = t("bowl.legend_drive");
      bowlCharts.derate.data.datasets[1].label = t("bowl.legend_derate");
      bowlCharts.derate.options.scales.x.title.text = t("bowl.time_s");
    }
    if (bowlCharts.losses) {
      bowlCharts.losses.data.datasets[0].label = t("bowl.p_piezo");
      bowlCharts.losses.data.datasets[1].label = t("bowl.p_glue");
      bowlCharts.losses.data.datasets[2].label = t("bowl.p_ti");
      bowlCharts.losses.data.datasets[3].label = t("bowl.legend_glue_factor");
      bowlCharts.losses.options.scales.x.title.text = t("bowl.time_s");
    }
    Object.keys(bowlCharts).forEach((k) => {
      if (k === "energy") return; // applyEnergyDoughnut already painted
      bumpChart(bowlCharts[k]);
    });
  }

  function drawSchematic(layers, geometry) {
    const svg = $("bowlSvg");
    if (!svg) return;
    const g = geometry || {};
    const W = 720, H = 420;
    const driveOn = (g.drive_level || 0) > 0.05;
    const load = (g.load || "").toLowerCase();
    const showDrop = !!g.droplet_demo && driveOn && (load.includes("water") || load.includes("gel"));
    const depthMm = ((g.cup_depth_m || 0.004) * 1e3);
    const wallPx = Math.max(10, Math.min(28, (g.cup_wall_thickness_m || 5e-4) * 2e4));
    const shape = (g.ti_face_shape || (($("bowlTiFaceShapeVal") || {}).value) || "cup");
    const cupW = 220;
    const cupX = 80;
    const cupTop = 110;
    const cupH = Math.max(70, Math.min(140, 40 + depthMm * 12));
    const bottomH = Math.max(14, Math.min(36, (g.ti_bottom_thickness_m || 3e-4) * 4e4));
    const piezoW = Math.max(40, Math.min(cupW - 2 * wallPx - 20, ((g.piezo_diameter_m || 0.018) / 0.02) * (cupW - 40)));
    const cov = Math.max(0.2, Math.min(1, Number(g.bond_coverage != null ? g.bond_coverage : (g.glue_coverage != null ? g.glue_coverage : 1))));
    const glueW = Math.max(24, piezoW * Math.sqrt(cov));
    const glueH = shape === "hemisphere" ? 7 : (shape === "cone" ? 6 : 6);
    const piezoH = 18;
    const press = (g.glue_press || "medium");
    const cure = Number(g.glue_cure_fraction != null ? g.glue_cure_fraction : 1);
    let html = "";
    html += `<rect x="${cupX + 20}" y="28" width="${cupW - 40}" height="36" rx="4" fill="#2a364a" stroke="#93a0b5"/>`;
    html += `<text x="${cupX + cupW / 2}" y="50" text-anchor="middle" fill="currentColor" font-size="12">PCB / Handstück</text>`;
    html += `<circle cx="${cupX + 40}" cy="100" r="5" fill="#8a9ba8"/><circle cx="${cupX + cupW - 40}" cy="100" r="5" fill="#8a9ba8"/>`;
    html += `<text x="${cupX + cupW / 2}" y="98" text-anchor="middle" fill="currentColor" font-size="10">${t("bowl.schematic_screws")}</text>`;
    const innerL = cupX + wallPx;
    const innerR = cupX + cupW - wallPx;
    const bottomY = cupTop + cupH;
    const midX = cupX + cupW / 2;
    // Ti wall + outer face profile by shape
    let tiPath = "";
    if (shape === "hemisphere") {
      const rx = (cupW - 2 * wallPx) / 2;
      const ry = Math.max(bottomH + 18, 28);
      // outer U with hemispherical bottom
      tiPath = `M ${cupX} ${cupTop} L ${cupX} ${bottomY} `
        + `A ${cupW / 2} ${ry + wallPx * 0.3} 0 0 0 ${cupX + cupW} ${bottomY} `
        + `L ${cupX + cupW} ${cupTop} L ${innerR} ${cupTop} L ${innerR} ${bottomY - 4} `
        + `A ${rx} ${ry} 0 0 1 ${innerL} ${bottomY - 4} `
        + `L ${innerL} ${cupTop} Z`;
    } else if (shape === "cone") {
      const tap = 18;
      tiPath = `M ${cupX} ${cupTop} L ${cupX + tap * 0.35} ${bottomY + bottomH} L ${cupX + cupW - tap * 0.35} ${bottomY + bottomH} L ${cupX + cupW} ${cupTop} `
        + `L ${innerR} ${cupTop} L ${innerR - tap * 0.2} ${bottomY} L ${innerL + tap * 0.2} ${bottomY} L ${innerL} ${cupTop} Z`;
    } else {
      // cup / Schale — mild concave outer bottom
      const dip = 10;
      tiPath = `M ${cupX} ${cupTop} L ${cupX} ${bottomY + bottomH - dip} `
        + `Q ${midX} ${bottomY + bottomH + dip} ${cupX + cupW} ${bottomY + bottomH - dip} `
        + `L ${cupX + cupW} ${cupTop} L ${innerR} ${cupTop} L ${innerR} ${bottomY} `
        + `Q ${midX} ${bottomY + dip * 0.6} ${innerL} ${bottomY} L ${innerL} ${cupTop} Z`;
    }
    html += `<path d="${tiPath}" fill="#8a9ba8" stroke="#556" stroke-width="1.5"/>`;
    html += `<text x="${cupX + cupW + 12}" y="${cupTop + 20}" fill="currentColor" font-size="11">Ti ${t("bowl.schematic_wall")}</text>`;
    html += `<text x="${cupX + cupW + 12}" y="${bottomY + 8}" fill="currentColor" font-size="11">Ti ${t("bowl.schematic_bottom")} (${t("bowl.ti_face_" + shape) || shape})</text>`;
    // piezo + glue inside bottom (glue width reflects coverage)
    const pzX = cupX + (cupW - piezoW) / 2;
    const glueX = cupX + (cupW - glueW) / 2;
    let glueY = bottomY - glueH - 1;
    let pzY = glueY - piezoH;
    if (shape === "hemisphere") {
      glueY = bottomY - glueH - 8;
      pzY = glueY - piezoH;
    } else if (shape === "cone") {
      glueY = bottomY - glueH - 2;
      pzY = glueY - piezoH;
    }
    html += `<rect x="${pzX}" y="${pzY}" width="${piezoW}" height="${piezoH}" fill="#e6a817" stroke="#0006" rx="2"/>`;
    // glue: islands → dashed segments
    const scen = (g.glue_spread_scenario || "ideal");
    if (scen === "islands" || cov < 0.75) {
      const segs = 4;
      const gap = 3;
      const segW = (glueW - gap * (segs - 1)) / segs;
      for (let i = 0; i < segs; i++) {
        if (i % 2 === 1 && scen === "islands") continue;
        html += `<rect x="${glueX + i * (segW + gap)}" y="${glueY}" width="${Math.max(2, segW)}" height="${glueH}" fill="#c45c26" stroke="#0006" opacity="${0.55 + 0.45 * cure}"/>`;
      }
    } else {
      html += `<rect x="${glueX}" y="${glueY}" width="${glueW}" height="${glueH}" fill="#c45c26" stroke="#0006" opacity="${0.55 + 0.45 * cure}"/>`;
    }
    html += `<text x="${pzX + piezoW / 2}" y="${pzY + 12}" text-anchor="middle" fill="#152033" font-size="10">PZT</text>`;
    html += `<text x="${midX}" y="${glueY + 5}" text-anchor="middle" fill="#fff" font-size="8">glue</text>`;
    // bond + shape annotations
    html += `<text x="${cupX}" y="${cupTop - 8}" fill="var(--muted)" font-size="10">${t("bowl.schematic_bond")}: ${scen} · press=${press} · cure=${Math.round(cure * 100)}%</text>`;
    // wires
    html += `<path d="M ${cupX + 55} 64 L ${cupX + 55} ${pzY + 4} L ${pzX + 8} ${pzY + 4}" fill="none" stroke="#3b9eff" stroke-width="2"/>`;
    html += `<text x="${cupX + 58}" y="${pzY - 6}" fill="#3b9eff" font-size="10">${t("bowl.schematic_wire_piezo")}</text>`;
    html += `<path d="M ${cupX + cupW - 55} 64 L ${cupX + cupW - 55} ${cupTop + 30} L ${cupX + cupW - 4} ${cupTop + 30}" fill="none" stroke="#2dd4a8" stroke-width="2"/>`;
    html += `<text x="${cupX + cupW - 52}" y="${cupTop + 24}" fill="#2dd4a8" font-size="10">${t("bowl.schematic_wire_ti")}</text>`;
    // ultrasound arrows — converge for hemisphere, diverge slightly for cone
    const ay0 = bottomY + bottomH + (shape === "hemisphere" ? 22 : 8);
    for (let i = 0; i < 5; i++) {
      const x0 = midX - 40 + i * 20;
      let x1 = x0;
      if (shape === "hemisphere") x1 = midX + (x0 - midX) * 0.45;
      else if (shape === "cone") x1 = midX + (x0 - midX) * 1.25;
      html += `<path d="M ${x0} ${ay0} L ${x1} ${ay0 + 28}" stroke="#3b9eff" stroke-width="2" marker-end="url(#arrow)"/>`;
    }
    html += `<defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#3b9eff"/></marker></defs>`;
    html += `<text x="${midX}" y="${ay0 + 48}" text-anchor="middle" fill="currentColor" font-size="11">${t("bowl.schematic_exit")}</text>`;
    html += `<rect x="${cupX}" y="${ay0 + 52}" width="${cupW}" height="28" fill="#5dade288" stroke="#3498db"/>`;
    html += `<text x="${midX}" y="${ay0 + 70}" text-anchor="middle" fill="currentColor" font-size="11">gel / tissue</text>`;
    if (showDrop) {
      html += `<circle cx="${midX + 55}" cy="${ay0 + 18}" r="7" fill="#5dade2" opacity="0.85"/>`;
      html += `<circle cx="${midX + 62}" cy="${ay0 + 6}" r="3" fill="#a8d8ff" opacity="0.7"/>`;
      html += `<circle cx="${midX + 48}" cy="${ay0 + 4}" r="2.5" fill="#a8d8ff" opacity="0.6"/>`;
      html += `<text x="${midX + 78}" y="${ay0 + 12}" fill="currentColor" font-size="10">${t("bowl.schematic_mist")}</text>`;
    }
    let ly = 40;
    html += `<text x="420" y="28" fill="currentColor" font-size="13" font-weight="600">${t("bowl.schematic_axis")}</text>`;
    const solids = (layers || []).filter((l) => l.name !== "air");
    if (solids.length) {
      solids.forEach((l) => {
        const h = l.scale_group === "um" ? 18 : Math.max(20, Math.min(40, (l.thickness_m || 0) * 1e3 * 40));
        html += `<rect x="420" y="${ly}" width="160" height="${h}" fill="${l.color_hint || "#888"}" stroke="#0006" rx="2"/>`;
        html += `<text x="590" y="${ly + h / 2 + 4}" fill="currentColor" font-size="11">${l.name} · ${l.thickness_display || ""}</text>`;
        ly += h + 4;
      });
    } else {
      html += `<text x="420" y="${ly + 14}" fill="var(--muted)" font-size="11">${t("bowl.schematic_live_hint")}</text>`;
      ly += 28;
    }
    html += `<text x="420" y="${ly + 18}" fill="var(--muted)" font-size="10">${t("bowl.schematic_note")}</text>`;
    html += `<text x="420" y="${ly + 34}" fill="var(--muted)" font-size="10">${t("bowl.schematic_shape_note")}</text>`;
    svg.innerHTML = html;
    const cap = $("bowlDropletCaption");
    if (cap) cap.style.display = showDrop ? "block" : "none";
  }

  function energyParts(energy) {
    const e = energy || {};
    return [
      Number(e.p_radiated_w) || 0,
      Number(e.p_glue_loss_w) || 0,
      Number(e.p_piezo_heat_w) || 0,
      Number(e.p_ti_loss_w) || 0,
    ];
  }

  function renderEnergyDetail(parts) {
    const box = $("bowlEnergyDetail");
    if (!box) return;
    const labels = [t("bowl.p_rad"), t("bowl.p_glue"), t("bowl.p_piezo"), t("bowl.p_ti")];
    const sum = parts.reduce((a, b) => a + b, 0);
    const rows = parts.map((w, i) => {
      const pct = sum > 1e-12 ? (100 * w / sum) : 0;
      return `<div class="ed-row"><span class="ed-name">${labels[i]}</span><span class="ed-w">${w.toFixed(4)} W</span><span class="ed-pct">${pct.toFixed(1)} %</span></div>`;
    }).join("");
    box.innerHTML = rows + `<div class="ed-total">${t("bowl.energy_total")}: ${sum.toFixed(4)} W</div>`;
  }

  function cloneEnergyParts(src) {
    if (!src || typeof src !== "object") return null;
    return {
      p_radiated_w: Number(src.p_radiated_w) || 0,
      p_glue_loss_w: Number(src.p_glue_loss_w) || 0,
      p_piezo_heat_w: Number(src.p_piezo_heat_w) || 0,
      p_ti_loss_w: Number(src.p_ti_loss_w) || 0,
      efficiency: Number(src.efficiency) || 0,
      p_drive_w: Number(src.p_drive_w) || 0,
    };
  }

  /**
   * Always destroy+recreate energy bar with data baked into constructor.
   * Never mutate shared cache arrays; abort-safe; no dead Chart leftovers.
   */
  function applyEnergyDoughnut(phase, opts) {
    try {
      if (!bowlEnergyCache) bowlEnergyCache = { start: null, end: null };
      if (phase) bowlEnergyPhase = phase;
      const src = bowlEnergyCache[bowlEnergyPhase] || bowlEnergyCache.end || bowlEnergyCache.start;
      if (!src) {
        ensureEnergyChartFresh([0.0001, 0, 0, 0]);
        renderEnergyDetail([0, 0, 0, 0]);
        document.querySelectorAll("#bowlEnergyPhase .preset-chip").forEach((b) => {
          b.classList.toggle("active", b.dataset.phase === bowlEnergyPhase);
        });
        return;
      }
      const parts = energyParts(src);
      const allZero = parts.every((v) => v <= 0);
      const data = allZero ? [0.0001, 0, 0, 0] : freshArray(parts);
      // Force recreate every paint (opts.recreate=false ignored for reliability)
      const ch = ensureEnergyChartFresh(data);
      if (ch && typeof ch.resize === "function") {
        try { ch.resize(); } catch (_) { /* ignore */ }
      }
      renderEnergyDetail(allZero ? [0, 0, 0, 0] : parts);
      document.querySelectorAll("#bowlEnergyPhase .preset-chip").forEach((b) => {
        b.classList.toggle("active", b.dataset.phase === bowlEnergyPhase);
      });
    } catch (err) {
      console.warn("applyEnergyDoughnut", err);
      try { ensureEnergyChartFresh([0.25, 0.25, 0.25, 0.25]); } catch (_) { /* ignore */ }
    }
  }


  function applyFreqCompareChart(data) {
    if (!bowlCharts.f0 || !data || !data.rows) return;
    bowlFreqCompareCache = data;
    const rows = data.rows;
    bowlCharts.f0.data.labels = rows.map((r) => {
      const mhz = Number(r.f0_mhz);
      return (Math.abs(mhz - 6) < 0.01) ? "6*" : String(mhz);
    });
    bowlCharts.f0.data.datasets[0].data = freshArray(rows.map((r) => r.p_ac_w));
    bowlCharts.f0.data.datasets[1].data = freshArray(rows.map((r) => r.efficiency));
    if (bowlCharts.f0.data.datasets[2]) {
      bowlCharts.f0.data.datasets[2].data = freshArray(rows.map((r) => r.t_at_f0));
    }
    bumpChart(bowlCharts.f0);
  }

  async function analyzeBowl() {
    if (bowlAnalyzeBusy) return;
    bowlAnalyzeBusy = true;
    const btn = $("btnBowlAnalyze");
    if (btn) btn.disabled = true;
    if (bowlAbort) {
      try { bowlAbort.abort(); } catch (_) { /* ignore */ }
    }
    bowlAbort = new AbortController();
    const signal = bowlAbort.signal;
    try {
      ensureBowl();
      const posted = await postJSON("/api/bowl/params", bowlPayload(), signal);
      const result = posted.result || (await getJSON("/api/bowl/analyze", signal));
      const energy = result.energy || {};
      $("bowlT").textContent = (result.t_at_f0 ?? 0).toFixed(4);
      $("bowlR").textContent = (result.r_at_f0 ?? 0).toFixed(4);
      $("bowlRes").textContent = ((result.resonance_hz || 0) / 1e6).toFixed(3) + " MHz";
      $("bowlShift").textContent = ((result.resonance_shift_hz || 0) / 1e3).toFixed(1) + " kHz";
      $("bowlPac").textContent = (energy.p_radiated_w ?? 0).toFixed(3) + " W";
      $("bowlEta").textContent = ((energy.efficiency ?? 0) * 100).toFixed(1) + " %";
      if ($("bowlTof") && result.time_of_flight) $("bowlTof").textContent = (result.time_of_flight.total_ns || 0).toFixed(1) + " ns";
      if ($("bowlLam")) $("bowlLam").textContent = result.lambda_m ? (result.lambda_m * 1e3).toFixed(3) + " mm" : "—";
      drawSchematic(result.layers || [], Object.assign({}, result.geometry || {}, result.params || {}));
      applyWavePathStrip(result.wave_path || (result.geometry && result.geometry.wave_path));
      try {
        bowlEnergyCache.start = cloneEnergyParts(energy);
        bowlEnergyCache.end = cloneEnergyParts(energy);
        applyEnergyDoughnut(bowlEnergyPhase);
      } catch (err) { console.warn("energy cache", err); }
      // Thermal transient first so heating charts are not left last after many Chart.js updates
      try {
        const tr = await postJSON("/api/bowl/transient", transientPayload(), signal);
        renderBowlTransient(tr);
        const tmOk = $("bowlTransientMetrics");
        if (tmOk) tmOk.removeAttribute("title");
      } catch (terr) {
        if (terr && terr.name === "AbortError") throw terr;
        console.warn("bowl transient", terr);
        const hint = String((terr && terr.message) || terr || "transient failed");
        const tm = $("bowlTransientMetrics");
        if (tm) tm.setAttribute("title", "Transient: " + hint);
        if (btn) btn.title = "Transient: " + hint;
      }
      const span = parseFloat($("bowlSpan") ? $("bowlSpan").value : 0.15);
      const [spec, glue, ti, field, dia, f0c, prof] = await Promise.all([
        getJSON("/api/bowl/spectrum?n=161&span=" + span, signal),
        postJSON("/api/bowl/sweep", { kind: "glue", n: 36 }, signal),
        postJSON("/api/bowl/sweep", { kind: "titanium", h_min_m: 5e-5, h_max_m: 3e-3, n: 100 }, signal),
        getJSON("/api/bowl/field?nx=48&nr=24", signal),
        postJSON("/api/bowl/sweep", { kind: "piezo_diameter", n: 24 }, signal),
        postJSON("/api/bowl/freq_compare", { wide: false }, signal),
        getJSON("/api/bowl/profile?n_per_layer=16", signal),
      ]);
      if (bowlCharts.spectrum) {
        bowlCharts.spectrum.data.labels = (spec.f_hz || []).map((v) => (v / 1e6).toFixed(2));
        bowlCharts.spectrum.data.datasets[0].data = spec.t_intensity || [];
        bowlCharts.spectrum.data.datasets[1].data = spec.r_intensity || [];
        const z = spec.z_in_mag || [];
        const zMax = Math.max(...z, 1e-9);
        bowlCharts.spectrum.data.datasets[2].data = z.map((v) => v / zMax);
        bumpChart(bowlCharts.spectrum);
      }
      if (bowlCharts.phase) {
        bowlCharts.phase.data.labels = (spec.f_hz || []).map((v) => (v / 1e6).toFixed(2));
        bowlCharts.phase.data.datasets[0].data = spec.z_in_phase_rad || [];
        bowlCharts.phase.data.datasets[1].data = spec.t_phase_rad || [];
        bumpChart(bowlCharts.phase);
      }
      if (bowlCharts.glue) {
        bowlCharts.glue.data.labels = (glue.glue_thickness_um || []).map((v) => Number(v).toFixed(1));
        bowlCharts.glue.data.datasets[0].data = glue.p_ac_w || [];
        bowlCharts.glue.data.datasets[1].data = glue.efficiency || [];
        bumpChart(bowlCharts.glue);
      }
      if (bowlCharts.ti) {
        bowlCharts.ti.data.labels = (ti.ti_thickness_mm || []).map((v) => Number(v).toFixed(2));
        bowlCharts.ti.data.datasets[0].data = ti.t_at_f0 || [];
        bowlCharts.ti.data.datasets[1].data = (ti.resonance_shift_hz || []).map((v) => v / 1e6);
        bumpChart(bowlCharts.ti);
      }
      if (bowlCharts.field && field.i_w_cm2) {
        bowlCharts.field.data.labels = (field.z_mm || []).map((v) => Number(v).toFixed(2));
        bowlCharts.field.data.datasets[0].data = field.i_w_cm2[0] || [];
        bumpChart(bowlCharts.field);
      }
      if (bowlCharts.dia) {
        bowlCharts.dia.data.labels = (dia.piezo_diameter_mm || []).map((v) => Number(v).toFixed(1));
        bowlCharts.dia.data.datasets[0].data = dia.p_ac_w || [];
        bowlCharts.dia.data.datasets[1].data = dia.i_sata_w_cm2 || [];
        bumpChart(bowlCharts.dia);
      }
      if (f0c && f0c.rows) applyFreqCompareChart(f0c);
      if (bowlCharts.profile) {
        bowlCharts.profile.data.labels = (prof.z_mm || []).map((v) => Number(v).toFixed(2));
        bowlCharts.profile.data.datasets[0].data = prof.pressure_abs || [];
        bumpChart(bowlCharts.profile);
      }
      if (btn && !(btn.title || "").startsWith("Transient:")) btn.title = "";
    } catch (err) {
      if (err && err.name === "AbortError") return;
      console.warn("analyzeBowl", err);
      if (btn) btn.title = String((err && err.message) || err || "analyze failed");
      const metrics = $("bowlMetrics");
      if (metrics) metrics.setAttribute("data-analyze-error", String((err && err.message) || err || "error"));
    } finally {
      bowlAnalyzeBusy = false;
      if (btn) btn.disabled = false;
    }
  }

  function clearChartYAutoscale(ch) {
    if (!ch || !ch.options || !ch.options.scales) return;
    const y = ch.options.scales.y;
    if (y) {
      delete y.min;
      delete y.max;
    }
  }

  function renderBowlTransient(tr) {
    if (!tr || !tr.series) return;
    const s = tr.series;
    const sum = tr.summary || {};
    // Synchronize Energieaufteilung with thermal run: start (cold) vs end (heated)
    if (sum.energy_start) bowlEnergyCache.start = cloneEnergyParts(sum.energy_start);
    else if ((s.P_ac_w || []).length) {
      bowlEnergyCache.start = {
        p_radiated_w: s.P_ac_w[0] || 0,
        p_glue_loss_w: (s.P_glue_loss_w || [])[0] || 0,
        p_piezo_heat_w: (s.P_piezo_heat_w || [])[0] || 0,
        p_ti_loss_w: (s.P_ti_loss_w || [])[0] || 0,
        efficiency: (s.eta || [])[0] || 0,
      };
    }
    if (sum.energy_end) bowlEnergyCache.end = cloneEnergyParts(sum.energy_end);
    else if ((s.P_ac_w || []).length) {
      const n = s.P_ac_w.length - 1;
      bowlEnergyCache.end = {
        p_radiated_w: s.P_ac_w[n] || 0,
        p_glue_loss_w: (s.P_glue_loss_w || [])[n] || 0,
        p_piezo_heat_w: (s.P_piezo_heat_w || [])[n] || 0,
        p_ti_loss_w: (s.P_ti_loss_w || [])[n] || 0,
        efficiency: (s.eta || [])[n] || 0,
      };
    }
    // Always destroy/recreate energy chart after duration/transient sync (anti-freeze)
    applyEnergyDoughnut(bowlEnergyPhase || "end");
    const labels = (s.t_s || []).slice().map((v) => Number(v).toFixed(v >= 60 ? 0 : 1));
    // KPI strip always when series present
    if ((s.T_piezo_c || []).length || sum.dT_piezo_c != null) {
      if ($("bowlDTPiezo")) $("bowlDTPiezo").textContent = (sum.dT_piezo_c != null ? Number(sum.dT_piezo_c).toFixed(1) : "—") + " K";
      if ($("bowlPacSE")) {
        const a = sum.P_ac_start_w != null ? Number(sum.P_ac_start_w).toFixed(3) : "—";
        const b = sum.P_ac_end_w != null ? Number(sum.P_ac_end_w).toFixed(3) : "—";
        $("bowlPacSE").textContent = a + "→" + b + " W";
      }
      if ($("bowlTGlueMax")) $("bowlTGlueMax").textContent = (sum.T_glue_max_c != null ? Number(sum.T_glue_max_c).toFixed(1) : "—") + " °C";
      if ($("bowlDerateMin")) $("bowlDerateMin").textContent = sum.derate_min != null ? Number(sum.derate_min).toFixed(2) : "—";
    }
    // Temps chart: always destroy+recreate canvas to avoid intermittent Chart.js freezes
    try {
      const chT = ensureTempsChartFresh();
      if (chT) {
        chT.data.labels = labels.slice();
        chT.data.datasets[0].data = freshArray(s.T_piezo_c);
        chT.data.datasets[1].data = freshArray(s.T_glue_c);
        chT.data.datasets[2].data = freshArray(s.T_ti_c);
        clearChartYAutoscale(chT);
        if (typeof chT.resize === "function") chT.resize();
        bumpChart(chT);
      }
    } catch (terr) {
      console.warn("temps chart recreate", terr);
    }
    if (bowlCharts.pacEta) {
      bowlCharts.pacEta.data.labels = labels;
      bowlCharts.pacEta.data.datasets[0].data = freshArray(s.P_ac_w);
      bowlCharts.pacEta.data.datasets[1].data = freshArray(s.eta);
      clearChartYAutoscale(bowlCharts.pacEta);
      bumpChart(bowlCharts.pacEta);
    }
    if (bowlCharts.derate) {
      bowlCharts.derate.data.labels = labels;
      bowlCharts.derate.data.datasets[0].data = freshArray(s.drive_level);
      bowlCharts.derate.data.datasets[1].data = freshArray(s.derate);
      clearChartYAutoscale(bowlCharts.derate);
      bumpChart(bowlCharts.derate);
    }
    if (bowlCharts.losses) {
      bowlCharts.losses.data.labels = labels;
      bowlCharts.losses.data.datasets[0].data = freshArray(s.P_piezo_heat_w);
      bowlCharts.losses.data.datasets[1].data = freshArray(s.P_glue_loss_w);
      bowlCharts.losses.data.datasets[2].data = freshArray(s.P_ti_loss_w);
      bowlCharts.losses.data.datasets[3].data = freshArray(s.glue_loss_factor);
      clearChartYAutoscale(bowlCharts.losses);
      bumpChart(bowlCharts.losses);
    }
  }

  async function refreshBowlTempsOnly() {
    if (bowlTempsBusy) return;
    bowlTempsBusy = true;
    const btn = $("btnBowlTempsRefresh");
    const labelBusy = t("bowl.btn_temps_refresh_busy");
    const labelIdle = t("bowl.btn_temps_refresh");
    if (btn) {
      btn.disabled = true;
      btn.classList.add("is-busy");
      const span = btn.querySelector("[data-temps-label]");
      if (span) span.textContent = labelBusy;
      else btn.textContent = labelBusy;
    }
    if (bowlTempsAbort) {
      try { bowlTempsAbort.abort(); } catch (_) { /* ignore */ }
    }
    bowlTempsAbort = new AbortController();
    const signal = bowlTempsAbort.signal;
    try {
      ensureBowl();
      await postJSON("/api/bowl/params", bowlPayload(), signal);
      const tr = await postJSON("/api/bowl/transient", transientPayload(), signal);
      renderBowlTransient(tr);
      const tmOk = $("bowlTransientMetrics");
      if (tmOk) tmOk.removeAttribute("title");
      if (btn) btn.title = t("bowl.btn_temps_refresh_title");
    } catch (err) {
      if (err && err.name === "AbortError") return;
      console.warn("refreshBowlTempsOnly", err);
      const hint = String((err && err.message) || err || "temps refresh failed");
      if (btn) btn.title = hint;
      const tm = $("bowlTransientMetrics");
      if (tm) tm.setAttribute("title", "Temps: " + hint);
    } finally {
      bowlTempsBusy = false;
      if (btn) {
        btn.disabled = false;
        btn.classList.remove("is-busy");
        const span = btn.querySelector("[data-temps-label]");
        if (span) {
          span.setAttribute("data-i18n", "bowl.btn_temps_refresh");
          span.textContent = labelIdle;
        } else btn.textContent = labelIdle;
      }
    }
  }

  async function refreshBowlEnergyOnly() {
    if (bowlEnergyBusy) return;
    bowlEnergyBusy = true;
    const btn = $("btnBowlEnergyRefresh");
    const labelBusy = t("bowl.btn_energy_refresh_busy");
    const labelIdle = t("bowl.btn_energy_refresh");
    if (btn) {
      btn.disabled = true;
      btn.classList.add("is-busy");
      const span = btn.querySelector("[data-energy-label]");
      if (span) span.textContent = labelBusy;
      else btn.textContent = labelBusy;
    }
    if (bowlEnergyAbort) {
      try { bowlEnergyAbort.abort(); } catch (_) { /* ignore */ }
    }
    bowlEnergyAbort = new AbortController();
    const signal = bowlEnergyAbort.signal;
    try {
      ensureBowl();
      await postJSON("/api/bowl/params", bowlPayload(), signal);
      const en = await postJSON("/api/bowl/energy", {
        duration_s: bowlDurationSeconds(),
        dt_s: parseFloat(($("bowlDtS") || { value: 0.15 }).value),
        include_heated: true,
        t_amb_c: parseFloat(($("bowlTAmb") || { value: 25 }).value),
        t_warn_c: parseFloat(($("bowlTWarn") || { value: 55 }).value),
        t_off_c: parseFloat(($("bowlTOff") || { value: 70 }).value),
        h_conv_w_m2k: parseFloat(($("bowlHConv") || { value: 40 }).value),
        g_piezo_glue_w_k: parseFloat(($("bowlGPG") || { value: 0.35 }).value),
        g_glue_ti_w_k: parseFloat(($("bowlGGT") || { value: 0.50 }).value),
        k_glue_loss_per_c: parseFloat(($("bowlKGlueLoss") || { value: 0.025 }).value),
        k_eff_drop_per_c: parseFloat(($("bowlKEffDrop") || { value: 0.0018 }).value),
        k_kt_drop_per_c: parseFloat(($("bowlKKtDrop") || { value: 0.0006 }).value),
        derate_smooth: !!($("bowlDerateSmooth") && $("bowlDerateSmooth").checked),
      }, signal);
      bowlEnergyCache.start = cloneEnergyParts(en.energy_start);
      bowlEnergyCache.end = cloneEnergyParts(en.energy_end || en.energy_start);
      applyEnergyDoughnut(bowlEnergyPhase || "end");
      if (btn) btn.title = t("bowl.btn_energy_refresh_title");
    } catch (err) {
      if (err && err.name === "AbortError") return;
      console.warn("refreshBowlEnergyOnly", err);
      const hint = String((err && err.message) || err || "energy refresh failed");
      if (btn) btn.title = hint;
    } finally {
      bowlEnergyBusy = false;
      if (btn) {
        btn.disabled = false;
        btn.classList.remove("is-busy");
        const span = btn.querySelector("[data-energy-label]");
        if (span) {
          span.setAttribute("data-i18n", "bowl.btn_energy_refresh");
          span.textContent = labelIdle;
        } else btn.textContent = labelIdle;
      }
    }
  }

  function syncGlueCoverageOut() {
    const el = $("bowlGlueCoverage");
    const out = $("bowlGlueCoverageOut");
    if (!el || !out) return;
    out.textContent = String(el.value) + " %";
  }


  function geometryFromForm() {
    const mmOr = (id, def) => {
      const el = $(id);
      const v = el ? parseFloat(el.value) : NaN;
      return isFinite(v) ? v : def;
    };
    const covPct = parseFloat(($("bowlGlueCoverage") || { value: 100 }).value) || 100;
    const curePct = parseFloat(($("bowlGlueCure") || { value: 100 }).value) || 100;
    return {
      cup_depth_m: mmOr("bowlCupDepth", 4) * 1e-3,
      cup_wall_thickness_m: mmOr("bowlCupWall", 0.52) * 1e-3,
      ti_bottom_thickness_m: mmOr("bowlTiH", 0.3) * 1e-3,
      piezo_diameter_m: mmOr("bowlPiezoD", 18) * 1e-3,
      ti_face_shape: (($("bowlTiFaceShapeVal") || { value: "cup" }).value || "cup"),
      glue_spread_scenario: (($("bowlGlueSpreadScenario") || { value: "ideal" }).value || "ideal"),
      glue_coverage: Math.max(0.2, Math.min(1, covPct / 100)),
      bond_coverage: Math.max(0.2, Math.min(1, covPct / 100)),
      glue_press: (($("bowlGluePress") || { value: "medium" }).value || "medium"),
      glue_cure_fraction: Math.max(0, Math.min(1, curePct / 100)),
      load: (($("bowlLoad") || { value: "gel_tissue" }).value || "gel_tissue"),
      drive_level: parseFloat(($("bowlDrive") || { value: 1 }).value) || 1,
      droplet_demo: !!($("bowlDroplet") && $("bowlDroplet").checked),
    };
  }

  function refreshSchematicLive() {
    drawSchematic([], geometryFromForm());
  }

  function setTiFaceShape(key, updateHint) {
    const k = key || "cup";
    if ($("bowlTiFaceShapeVal")) $("bowlTiFaceShapeVal").value = k;
    document.querySelectorAll("#bowlTiFaceShape .preset-chip").forEach((b) => {
      b.classList.toggle("active", b.dataset.tiFaceShape === k);
    });
    const hint = $("bowlTiFaceShapeHint");
    if (hint && updateHint !== false) {
      const i18nKey = "bowl.ti_face_hint_" + k;
      hint.setAttribute("data-i18n", i18nKey);
      hint.textContent = t(i18nKey);
    }
    refreshSchematicLive();
  }

  function applyWavePathStrip(wp) {
    if (!wp) return;
    const shapeKey = wp.ti_face_shape || "cup";
    if ($("bowlWaveShape")) $("bowlWaveShape").textContent = t("bowl.ti_face_" + shapeKey) || shapeKey;
    if ($("bowlWaveT")) $("bowlWaveT").textContent = (wp.t_at_f0 != null ? Number(wp.t_at_f0).toFixed(4) : "—");
    if ($("bowlWaveLossGlue")) $("bowlWaveLossGlue").textContent = (wp.loss_glue != null ? (Number(wp.loss_glue) * 100).toFixed(1) + " %" : "—");
    if ($("bowlWavePac")) $("bowlWavePac").textContent = (wp.p_ac_w != null ? Number(wp.p_ac_w).toFixed(3) + " W" : "—");
    if ($("bowlWaveZFocus")) $("bowlWaveZFocus").textContent = (wp.z_focus_mm != null ? Number(wp.z_focus_mm).toFixed(2) + " mm" : "—");
  }

  function setGlueSpreadScenario(key, updateHint) {
    const k = key || "ideal";
    if ($("bowlGlueSpreadScenario")) $("bowlGlueSpreadScenario").value = k;
    document.querySelectorAll("#bowlTiFaceShape .preset-chip").forEach((b) => {
    b.addEventListener("click", () => {
      setTiFaceShape(b.dataset.tiFaceShape, true);
      // diagram only — no auto full-analyze
    });
  });
  document.querySelectorAll("#bowlGlueSpread .preset-chip").forEach((b) => {
      b.classList.toggle("active", b.dataset.glueSpread === k);
    });
    const hint = $("bowlGlueSpreadHint");
    if (hint && updateHint !== false) {
      const i18nKey = "bowl.glue_spread_hint_" + k;
      hint.setAttribute("data-i18n", i18nKey);
      hint.textContent = t(i18nKey);
    }
  }

  function setGluePress(key, updateHint) {
    const k = key || "medium";
    if ($("bowlGluePress")) $("bowlGluePress").value = k;
    document.querySelectorAll("#bowlGluePressChips .preset-chip").forEach((b) => {
      b.classList.toggle("active", b.dataset.gluePress === k);
    });
    const hint = $("bowlGluePressHint");
    if (hint && updateHint !== false) {
      const i18nKey = "bowl.glue_press_hint_" + k;
      hint.setAttribute("data-i18n", i18nKey);
      hint.textContent = t(i18nKey);
    }
  }

  function setGlueCure(pctOrKey, updateHint) {
    let pct = 100;
    if (typeof pctOrKey === "string") {
      const named = { cured: 100, partial: 55, uncured: 15 };
      pct = named[pctOrKey] != null ? named[pctOrKey] : parseFloat(pctOrKey);
    } else {
      pct = Number(pctOrKey);
    }
    if (!isFinite(pct)) pct = 100;
    pct = Math.max(0, Math.min(100, Math.round(pct)));
    if ($("bowlGlueCure")) $("bowlGlueCure").value = String(pct);
    const out = $("bowlGlueCureOut");
    if (out) out.textContent = pct + " %";
    let chip = "cured";
    if (pct <= 30) chip = "uncured";
    else if (pct <= 70) chip = "partial";
    document.querySelectorAll("#bowlGlueCureChips .preset-chip").forEach((b) => {
      b.classList.toggle("active", b.dataset.glueCure === chip);
    });
    const hint = $("bowlGlueCureHint");
    if (hint && updateHint !== false) {
      const i18nKey = "bowl.glue_cure_hint_" + chip;
      hint.setAttribute("data-i18n", i18nKey);
      hint.textContent = t(i18nKey);
    }
  }

  async function resetBowl() {

    const data = await (await fetch("/api/bowl/params")).json();
    applyBowlParamsToForm(data.params || {});
    $("bowlPiezoAuto").checked = true;
    $("bowlPiezoH").value = "";
    $("bowlPiezoH").disabled = true;
  }

  async function loadBowlPreset(name) {
    const posted = await postJSON("/api/bowl/preset", { name });
    applyBowlParamsToForm(posted.params || {});
    $("bowlPiezoAuto").checked = posted.params && posted.params.piezo_thickness_m == null;
  }

  async function runBowlCompare() {
    const help = (await (await fetch("/api/bowl/params")).json()).help || {};
    const defs = help.preset_defs || {};
    const aName = $("bowlCmpA").value;
    const bName = $("bowlCmpB").value;
    const cmp = await postJSON("/api/bowl/compare", { a: defs[aName] || { f0_hz: 19e6 }, b: defs[bName] || { f0_hz: 10e6 } });
    const d = cmp.delta || {};
    $("bowlCompareOut").textContent = JSON.stringify({
      a: aName, b: bName,
      dP_ac: (d.p_radiated_w || 0).toFixed(4),
      dEta: (d.efficiency || 0).toFixed(4),
      dT: (d.t_at_f0 || 0).toFixed(5),
      dFres_kHz: ((d.resonance_hz || 0) / 1e3).toFixed(2),
    }, null, 2);
  }


  function isSettingsCollapsed() {
    return localStorage.getItem(SETTINGS_COLLAPSE_KEY) === "1";
  }

  function updateCollapseLabels(collapsed) {
    const btn = $("btnSettingsCollapse");
    if (!btn) return;
    const icon = btn.querySelector(".collapse-icon");
    const label = btn.querySelector(".collapse-label");
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    if (icon) icon.textContent = collapsed ? "»" : "«";
    if (label) {
      label.setAttribute("data-i18n", collapsed ? "header.settings_show" : "header.settings_hide");
      label.textContent = t(collapsed ? "header.settings_show" : "header.settings_hide");
    }
    btn.title = t(collapsed ? "header.settings_show" : "header.settings_hide");
  }

  function setSettingsCollapsed(collapsed) {
    collapsed = !!collapsed;
    document.body.classList.toggle("settings-collapsed", collapsed);
    localStorage.setItem(SETTINGS_COLLAPSE_KEY, collapsed ? "1" : "0");
    // Only show reopen for the active tab
    const therapyOn = !$("tab-therapy") || !$("tab-therapy").classList.contains("hidden");
    const bowlOn = $("tab-bowl") && !$("tab-bowl").classList.contains("hidden");
    const rt = $("btnSettingsReopenTherapy");
    const rb = $("btnSettingsReopenBowl");
    if (rt) {
      rt.hidden = !(collapsed && therapyOn);
      rt.style.display = (collapsed && therapyOn) ? "" : "none";
    }
    if (rb) {
      rb.hidden = !(collapsed && bowlOn);
      rb.style.display = (collapsed && bowlOn) ? "" : "none";
    }
    // Hard-hide settings columns (CSS also hides; belt + suspenders)
    document.querySelectorAll(".settings-col").forEach((el) => {
      el.style.display = collapsed ? "none" : "";
    });
    updateCollapseLabels(collapsed);
    resizeAllCharts();
    requestAnimationFrame(resizeAllCharts);
  }

  function syncPowerPresetChips(groupId, level) {
    const g = $(groupId);
    if (!g) return;
    const lv = Number(level);
    g.querySelectorAll(".preset-chip").forEach((b) => {
      const v = parseFloat(b.dataset.power);
      b.classList.toggle("active", Math.abs(v - lv) < 0.026);
    });
  }

  function setTherapyDriveLevel(level) {
    const lv = Math.max(0.05, Math.min(1, Number(level)));
    if ($("driveLevel")) $("driveLevel").value = lv;
    if ($("driveLevelVal")) $("driveLevelVal").textContent = lv.toFixed(2);
    syncPowerPresetChips("therapyPowerPresets", lv);
  }

  function setBowlDriveLevel(level) {
    const lv = Math.max(0.05, Math.min(1, Number(level)));
    if ($("bowlDrive")) $("bowlDrive").value = lv;
    if ($("bowlDriveVal")) $("bowlDriveVal").textContent = lv.toFixed(2);
    syncPowerPresetChips("bowlPowerPresets", lv);
  }

  // events
  document.querySelectorAll(".tab-btn").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  document.querySelectorAll(".lang-btn").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
  $("btnTheme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(THEME_KEY, next);
    chartTheme();
    resizeAllCharts();
  });
  $("modelSelect").addEventListener("change", async () => {
    const card = $("ldmTyp16Card");
    if (card) card.hidden = $("modelSelect").value !== "LDM_TRIPLE";
    await applySettings();
    await loadPrograms();
  });
  // initial LDM stub card
  if ($("ldmTyp16Card") && $("modelSelect")) {
    $("ldmTyp16Card").hidden = $("modelSelect").value !== "LDM_TRIPLE";
  }
  $("programSelect").addEventListener("change", onProgramChange);
  $("btnApply").addEventListener("click", applySettings);
  $("btnWrite").addEventListener("click", applySettings);
  $("btnStart").addEventListener("click", async () => { await applySettings(); renderStatus(await postJSON("/api/start")); });
  $("btnPause").addEventListener("click", async () => renderStatus(await postJSON("/api/pause")));
  $("btnReset").addEventListener("click", async () => { socHist=[]; fsmHist=[]; burstHist=[]; renderStatus(await postJSON("/api/reset")); });
  $("btnDock").addEventListener("click", async () => renderStatus(await postJSON("/api/dock")));
  $("btnUndock").addEventListener("click", async () => renderStatus(await postJSON("/api/undock")));
  $("btnStep").addEventListener("click", async () => renderStatus(await postJSON("/api/step")));
  $("btnRun").addEventListener("click", async () => {
    await applySettings(); await postJSON("/api/start");
    renderStatus(await postJSON("/api/run", { seconds: parseFloat($("runSec").value) }));
  });
  $("btnSelftest").addEventListener("click", async () => {
    const data = await (await fetch("/api/selftest")).json();
    const ul = $("selftestList"); ul.innerHTML = "";
    (data.results || []).forEach((r, idx) => {
      const li = document.createElement("li");
      li.className = r.pass ? "pass" : "fail";
      li.innerHTML = `<span><span class="dot ${r.pass ? "ok" : "bad"}"></span>${t("selftest.a"+(idx+1))}</span><b>${r.pass ? t("selftest.pass") : t("selftest.fail")}</b>`;
      ul.appendChild(li);
    });
  });
  $("btnPng").addEventListener("click", () => {
    if (!therapyCharts.ix) return;
    const a = document.createElement("a");
    a.href = therapyCharts.ix.toBase64Image();
    a.download = "skinova_ix.png";
    a.click();
  });
  $("btnSavePreset").addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(settingsPayload(), null, 2)], { type: "application/json" }));
    a.download = "skinova_preset.json";
    a.click();
  });
  $("presetFile").addEventListener("change", async (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    const p = JSON.parse(await f.text());
    if (p.model) $("modelSelect").value = p.model;
    if (p.i_set != null) $("iSata").value = p.i_set;
    if (p.duration_s != null) $("durationS").value = p.duration_s;
    if (p.mode) $("modeSelect").value = p.mode;
    if (p.path) $("pathSelect").value = p.path;
    if (p.gel_present != null) $("gelPresent").checked = p.gel_present;
    await applySettings();
  });
  if ($("bowlDrive")) $("bowlDrive").addEventListener("input", (e) => {
    if ($("bowlDriveVal")) $("bowlDriveVal").textContent = Number(e.target.value).toFixed(2);
    syncPowerPresetChips("bowlPowerPresets", e.target.value);
  });

  // Event delegation — collapse must work even if other controls fail to bind
  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("#btnSettingsCollapse, .btn-collapse-local, #btnSettingsReopenTherapy, #btnSettingsReopenBowl");
    if (!t) return;
    ev.preventDefault();
    if (t.id === "btnSettingsCollapse") {
      setSettingsCollapsed(!document.body.classList.contains("settings-collapsed"));
    } else if (t.classList.contains("btn-collapse-local")) {
      setSettingsCollapsed(true);
    } else {
      setSettingsCollapsed(false);
    }
  });
  if ($("driveLevel")) {
    $("driveLevel").addEventListener("input", (e) => {
      setTherapyDriveLevel(e.target.value);
    });
  }
  if ($("pcbDriveV") && $("vdrive")) {
    $("pcbDriveV").addEventListener("change", () => {
      $("vdrive").value = $("pcbDriveV").value;
    });
    $("vdrive").addEventListener("change", () => {
      $("pcbDriveV").value = $("vdrive").value;
    });
  }
  document.querySelectorAll("#therapyPowerPresets .preset-chip").forEach((b) => {
    b.addEventListener("click", () => {
      setTherapyDriveLevel(b.dataset.power);
      applySettings();
    });
  });
  document.querySelectorAll("#bowlPowerPresets .preset-chip").forEach((b) => {
    b.addEventListener("click", () => {
      setBowlDriveLevel(b.dataset.power);
    });
  });

  $("bowlPiezoAuto").addEventListener("change", (e) => { $("bowlPiezoH").disabled = e.target.checked; });
  if ($("bowlTiD")) $("bowlTiD").addEventListener("input", () => syncRadiatingDiameter("ti"));
  if ($("bowlCupOuterD")) $("bowlCupOuterD").addEventListener("input", () => syncRadiatingDiameter("outer"));
  if ($("bowlEra")) $("bowlEra").addEventListener("input", () => syncRadiatingDiameter("era"));
  if ($("bowlCupInnerD")) $("bowlCupInnerD").addEventListener("input", () => { syncWallFromInnerOuter(); clampPiezoDiameter(true); });
  if ($("bowlPiezoD")) $("bowlPiezoD").addEventListener("input", () => clampPiezoDiameter(true));
  if ($("bowlPiezoD")) $("bowlPiezoD").addEventListener("change", () => clampPiezoDiameter(true));
  $("btnBowlAnalyze").addEventListener("click", analyzeBowl);

  async function refreshBowlFreqCompareOnly() {
    if (bowlFreqCompareBusy) return;
    bowlFreqCompareBusy = true;
    const btn = $("btnBowlFreqCompareRefresh");
    const labelBusy = t("bowl.btn_freq_compare_refresh_busy");
    const labelIdle = t("bowl.btn_freq_compare_refresh");
    if (btn) {
      btn.disabled = true;
      btn.classList.add("is-busy");
      const span = btn.querySelector("[data-freq-compare-label]");
      if (span) span.textContent = labelBusy;
      else btn.textContent = labelBusy;
    }
    if (bowlFreqCompareAbort) {
      try { bowlFreqCompareAbort.abort(); } catch (_) { /* ignore */ }
    }
    bowlFreqCompareAbort = new AbortController();
    const signal = bowlFreqCompareAbort.signal;
    try {
      ensureBowl();
      await postJSON("/api/bowl/params", bowlPayload(), signal);
      const data = await postJSON("/api/bowl/freq_compare", { wide: false }, signal);
      applyFreqCompareChart(data);
      if (btn) btn.title = t("bowl.btn_freq_compare_refresh_title");
    } catch (err) {
      if (err && err.name === "AbortError") return;
      console.warn("refreshBowlFreqCompareOnly", err);
      const hint = String((err && err.message) || err || "freq compare refresh failed");
      if (btn) btn.title = hint;
    } finally {
      bowlFreqCompareBusy = false;
      if (btn) {
        btn.disabled = false;
        btn.classList.remove("is-busy");
        const span = btn.querySelector("[data-freq-compare-label]");
        if (span) {
          span.setAttribute("data-i18n", "bowl.btn_freq_compare_refresh");
          span.textContent = labelIdle;
        } else btn.textContent = labelIdle;
      }
    }
  }

  if ($("btnBowlTempsRefresh")) $("btnBowlTempsRefresh").addEventListener("click", refreshBowlTempsOnly);
  if ($("btnBowlEnergyRefresh")) $("btnBowlEnergyRefresh").addEventListener("click", refreshBowlEnergyOnly);
  if ($("btnBowlFreqCompareRefresh")) $("btnBowlFreqCompareRefresh").addEventListener("click", refreshBowlFreqCompareOnly);

  document.querySelectorAll("#bowlEnergyPhase .preset-chip").forEach((b) => {
    b.addEventListener("click", () => applyEnergyDoughnut(b.dataset.phase));
  });
  document.querySelectorAll("#bowlGlueSpread .preset-chip").forEach((b) => {
    b.addEventListener("click", () => {
      setGlueSpreadScenario(b.dataset.glueSpread, true);
      refreshSchematicLive();
      // No auto-analyze — user presses Analysieren or Energie neu berechnen
    });
  });
  document.querySelectorAll("#bowlGluePressChips .preset-chip").forEach((b) => {
    b.addEventListener("click", () => setGluePress(b.dataset.gluePress, true));
  });
  document.querySelectorAll("#bowlGlueCureChips .preset-chip").forEach((b) => {
    b.addEventListener("click", () => setGlueCure(b.dataset.glueCure, true));
  });
  if ($("bowlGlueCoverage")) {
    $("bowlGlueCoverage").addEventListener("input", syncGlueCoverageOut);
    syncGlueCoverageOut();
  }
  if ($("bowlGlueCure")) {
    $("bowlGlueCure").addEventListener("input", () => setGlueCure($("bowlGlueCure").value, true));
  }
  setGlueSpreadScenario((($("bowlGlueSpreadScenario") || {}).value) || "ideal", true);
  setGluePress((($("bowlGluePress") || {}).value) || "medium", true);
  setGlueCure((($("bowlGlueCure") || {}).value) || 100, true);
  setTiFaceShape((($("bowlTiFaceShapeVal") || {}).value) || "cup", true);
  $("btnBowlReset").addEventListener("click", resetBowl);
  if ($("bowlDurationPreset")) {
    $("bowlDurationPreset").addEventListener("change", syncBowlDurationUI);
    syncBowlDurationUI();
  }
  document.querySelectorAll("#bowlFreqChips .chip").forEach((c) => c.addEventListener("click", () => {
    $("bowlF0").value = c.dataset.f0;
    syncBowlFreqChips();
  }));
  document.querySelectorAll("#bowlPresets .preset-btn").forEach((b) => b.addEventListener("click", () => loadBowlPreset(b.dataset.preset)));
  if ($("btnBowlCompare")) $("btnBowlCompare").addEventListener("click", runBowlCompare);
  if ($("f0Select")) $("f0Select").addEventListener("change", applySettings);


  /* ========== Chart expand / info modal ========== */
  let modalChart = null;
  const CHART_CAPTION_KEY = {
    chartBowlSpectrum: "bowl.caption_spectrum",
    chartBowlGlue: "bowl.caption_glue",
    chartBowlTi: "bowl.caption_ti",
    chartBowlEnergy: "bowl.caption_energy",
    chartBowlField: "bowl.caption_field",
    chartBowlDia: "bowl.caption_dia",
    chartBowlF0: "bowl.caption_freq_compare",
    chartBowlProfile: "bowl.caption_profile",
    chartBowlPhase: "bowl.caption_phase",
    chartBowlTemps: "bowl.caption_temps",
    chartBowlPacEta: "bowl.caption_pac_eta",
    chartBowlDerate: "bowl.caption_derate",
    chartBowlLosses: "bowl.caption_losses",
    chartIx: "captions.i_x",
    chartTx: "captions.t_x",
    chartDose: "captions.dose",
    chartSoc: "captions.soc",
    chartBurst: "captions.burst",
    chartFsm: "captions.fsm",
  };
  const CHART_INSTANCE_MAP = {
    chartBowlSpectrum: () => bowlCharts.spectrum,
    chartBowlGlue: () => bowlCharts.glue,
    chartBowlTi: () => bowlCharts.ti,
    chartBowlEnergy: () => bowlCharts.energy,
    chartBowlField: () => bowlCharts.field,
    chartBowlDia: () => bowlCharts.dia,
    chartBowlF0: () => bowlCharts.f0,
    chartBowlProfile: () => bowlCharts.profile,
    chartBowlPhase: () => bowlCharts.phase,
    chartBowlTemps: () => bowlCharts.temps,
    chartBowlPacEta: () => bowlCharts.pacEta,
    chartBowlDerate: () => bowlCharts.derate,
    chartBowlLosses: () => bowlCharts.losses,
    chartIx: () => therapyCharts.ix,
    chartTx: () => therapyCharts.tx,
    chartDose: () => therapyCharts.dose,
    chartSoc: () => therapyCharts.soc,
    chartBurst: () => therapyCharts.burst,
    chartFsm: () => therapyCharts.fsm,
  };

  function cloneChartConfig(src) {
    if (!src) return null;
    const labels = Array.isArray(src.data.labels) ? src.data.labels.slice() : [];
    const datasets = (src.data.datasets || []).map((ds) => {
      const copy = Object.assign({}, ds);
      copy.data = Array.isArray(ds.data) ? ds.data.slice() : ds.data;
      if (Array.isArray(ds.backgroundColor)) copy.backgroundColor = ds.backgroundColor.slice();
      if (Array.isArray(ds.borderColor)) copy.borderColor = ds.borderColor.slice();
      return copy;
    });
    let options;
    try {
      options = JSON.parse(JSON.stringify(src.options || {}));
    } catch (_) {
      options = { responsive: true, maintainAspectRatio: false, animation: false };
    }
    options.responsive = true;
    options.maintainAspectRatio = false;
    options.animation = false;
    return { type: src.config.type, data: { labels, datasets }, options };
  }

  function resolveChartTitle(canvasId, infoKey) {
    const btn = document.querySelector('[data-chart-expand="' + canvasId + '"]');
    const head = btn && btn.closest(".chart-card");
    const titleEl = head && head.querySelector(".card-title");
    if (titleEl && titleEl.textContent.trim()) return titleEl.textContent.trim();
    const key = infoKey || "";
    if (key.startsWith("bowl.info_")) {
      const map = {
        spectrum: "bowl.spectrum", glue: "bowl.sweep_glue", ti: "bowl.sweep_ti",
        energy: "bowl.energy", field: "bowl.field", dia: "bowl.sweep_dia",
        f0: "bowl.freq_compare", profile: "bowl.profile", phase: "bowl.phase",
        temps: "bowl.chart_temps", pacEta: "bowl.chart_pac_eta",
        derate: "bowl.chart_derate", losses: "bowl.chart_losses",
      };
      return t(map[key.replace("bowl.info_", "")] || key);
    }
    return canvasId;
  }

  function formatInfoHtml(text) {
    const s = String(text || "");
    if (!s || s.startsWith("bowl.info_") || s.startsWith("therapy.info_")) {
      return "<p><em>" + (s || "—") + "</em></p>";
    }
    const esc = (x) => String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const sectionRe = /^(Was gezeigt wird|Physik \/ Modell|Eingaben.*|Formeln.*|Handrechnung.*|Nutzen|Button.*|Что показано|Физика \/ модель|Входы.*|Формулы.*|Ручной пересчёт.*|Зачем|Кнопка.*)$/i;
    return s.split(/\n\n+/).map((block) => {
      const lines = block.split(/\n/).map((l) => l.trimEnd());
      const head = (lines[0] || "").trim();
      if (/^CALIBRATION|^КАЛИБРОВКА|^KALIBRIERUNG/i.test(head)) {
        return '<div class="info-calib">' + esc(block.trim()) + "</div>";
      }
      if (sectionRe.test(head) && lines.length > 1) {
        const body = lines.slice(1).filter((l) => l.length);
        const isList = body.length >= 2 && body.every((l) => /^(\d+[).]\s+|[-•]\s+)/.test(l.trim()));
        if (isList) {
          const items = body.map((l) => "<li>" + esc(l.replace(/^(\d+[).]\s+|[-•]\s+)/, "")) + "</li>").join("");
          return '<div class="info-section"><h4 class="info-h">' + esc(head) + "</h4><ol class=\"info-ol\">" + items + "</ol></div>";
        }
        return '<div class="info-section"><h4 class="info-h">' + esc(head) + "</h4><p>" + body.map(esc).join("<br>") + "</p></div>";
      }
      if (lines.length >= 2 && lines.every((l) => !l || /^\d+[).]\s+/.test(l.trim()))) {
        const items = lines.filter(Boolean).map((l) => "<li>" + esc(l.replace(/^\d+[).]\s+/, "")) + "</li>").join("");
        return "<ol class=\"info-ol\">" + items + "</ol>";
      }
      return "<p>" + esc(block.trim()).replace(/\n/g, "<br>") + "</p>";
    }).join("");
  }

  let modalWideAbort = null;

  /** Wider axis / denser points for fullscreen only — does not mutate main charts. */
  async function fetchWideChartConfig(canvasId) {
    const spanUi = parseFloat(($("bowlSpan") || { value: 0.15 }).value) || 0.15;
    if (canvasId === "chartBowlSpectrum" || canvasId === "chartBowlPhase") {
      const span = Math.min(0.85, Math.max(0.45, spanUi * 3));
      const spec = await getJSON("/api/bowl/spectrum?n=241&span=" + span);
      const labels = (spec.f_hz || []).map((v) => (v / 1e6).toFixed(2));
      if (canvasId === "chartBowlSpectrum") {
        const z = spec.z_in_mag || [];
        const zMax = Math.max(...z, 1e-9);
        return {
          type: "line",
          data: {
            labels,
            datasets: [
              { label: t("bowl.legend_t") || "|T|", data: freshArray(spec.t_intensity), borderColor: "#3b9eff", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0 },
              { label: t("bowl.legend_r") || "|R|", data: freshArray(spec.r_intensity), borderColor: "#f07178", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0 },
              { label: t("bowl.legend_z") || "|Z|n", data: z.map((v) => v / zMax), borderColor: "#ffd866", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0, yAxisID: "y1" },
            ],
          },
          options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            scales: {
              x: { title: { display: true, text: "f (MHz)" } },
              y: { title: { display: true, text: "T / R" } },
              y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "|Z| norm" } },
            },
          },
        };
      }
      return {
        type: "line",
        data: {
          labels,
          datasets: [
            { label: "∠Z", data: freshArray(spec.z_in_phase_rad), borderColor: "#3b9eff", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0 },
            { label: "∠T", data: freshArray(spec.t_phase_rad), borderColor: "#f07178", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          scales: { x: { title: { display: true, text: "f (MHz)" } }, y: { title: { display: true, text: "phase (rad)" } } },
        },
      };
    }
    if (canvasId === "chartBowlGlue") {
      const glue = await postJSON("/api/bowl/sweep", { kind: "glue", h_min_m: 5e-7, h_max_m: 8e-5, n: 64 });
      return {
        type: "line",
        data: {
          labels: (glue.glue_thickness_um || []).map((v) => Number(v).toFixed(1)),
          datasets: [
            { label: t("bowl.p_ac_axis") || "P_ac", data: freshArray(glue.p_ac_w), borderColor: "#2dd4a8", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0 },
            { label: t("bowl.eff_axis") || "η", data: freshArray(glue.efficiency), borderColor: "#c084fc", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0, yAxisID: "y1" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          scales: {
            x: { title: { display: true, text: t("bowl.glue_um") || "glue (µm)" } },
            y: { title: { display: true, text: "P_ac (W)" } },
            y1: { position: "right", min: 0, max: 1, grid: { drawOnChartArea: false }, title: { display: true, text: "η" } },
          },
        },
      };
    }
    if (canvasId === "chartBowlTi") {
      const ti = await postJSON("/api/bowl/sweep", { kind: "titanium", h_min_m: 3e-5, h_max_m: 3.5e-3, n: 120 });
      return {
        type: "line",
        data: {
          labels: (ti.ti_thickness_mm || []).map((v) => Number(v).toFixed(2)),
          datasets: [
            { label: "T(f0)", data: freshArray(ti.t_at_f0), borderColor: "#3b9eff", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0 },
            { label: "Δf", data: (ti.resonance_shift_hz || []).map((v) => v / 1e6), borderColor: "#ffd866", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0, yAxisID: "y1" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          scales: {
            x: { title: { display: true, text: t("bowl.ti_mm") || "Ti (mm)" } },
            y: { title: { display: true, text: "T" } },
            y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Δf (MHz)" } },
          },
        },
      };
    }
    if (canvasId === "chartBowlField") {
      const field = await getJSON("/api/bowl/field?nx=80&nr=24&z_max_m=0.025");
      return {
        type: "line",
        data: {
          labels: (field.z_mm || []).map((v) => Number(v).toFixed(2)),
          datasets: [{ label: "I(z,0)", data: freshArray((field.i_w_cm2 || [])[0] || []), borderColor: "#3b9eff", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0 }],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          plugins: { legend: { display: false } },
          scales: { x: { title: { display: true, text: "z (mm)" } }, y: { title: { display: true, text: "I (W/cm²)" } } },
        },
      };
    }
    if (canvasId === "chartBowlDia") {
      const dMax = (parseFloat(($("bowlTiD") || { value: 19.54 }).value) || 19.54) * 1e-3;
      const dia = await postJSON("/api/bowl/sweep", { kind: "piezo_diameter", h_min_m: 0.008, h_max_m: dMax, n: 40 });
      return {
        type: "line",
        data: {
          labels: (dia.piezo_diameter_mm || []).map((v) => Number(v).toFixed(1)),
          datasets: [
            { label: "P_ac", data: freshArray(dia.p_ac_w), borderColor: "#2dd4a8", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0 },
            { label: "I", data: freshArray(dia.i_sata_w_cm2), borderColor: "#ffd866", backgroundColor: "transparent", borderWidth: 2, pointRadius: 0, yAxisID: "y1" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          scales: {
            x: { title: { display: true, text: "Ø (mm)" } },
            y: { title: { display: true, text: "P_ac (W)" } },
            y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "I (W/cm²)" } },
          },
        },
      };
    }
    if (canvasId === "chartBowlEnergy") {
      const src = bowlEnergyCache[bowlEnergyPhase] || bowlEnergyCache.end || bowlEnergyCache.start;
      const parts = src ? energyParts(src) : [0.25, 0.25, 0.25, 0.25];
      const allZero = parts.every((v) => v <= 0);
      const data = allZero ? [0.0001, 0, 0, 0] : freshArray(parts);
      return {
        type: "bar",
        data: {
          labels: energyChartLabels(),
          datasets: [{ label: "W", data, backgroundColor: ["#2dd4a8", "#c45c26", "#e6a817", "#8a9ba8"], borderWidth: 1, borderColor: "#151d2c", borderRadius: 4 }],
        },
        options: {
          indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false,
          plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true, title: { display: true, text: "W" } }, y: { grid: { display: false } } },
        },
      };
    }
    if (canvasId === "chartBowlF0") {
      const fc = await postJSON("/api/bowl/freq_compare", {
        wide: true, f_min_hz: 0.5e6, f_max_hz: 22e6, n_wide: 101,
      });
      const w = fc.wide || {};
      const labels = (w.f_mhz || []).map((v) => Number(v).toFixed(2));
      const anchors = new Set((fc.anchors_mhz || [1, 3, 6, 10, 19]).map(Number));
      const pointR = (w.f_mhz || []).map((v) => (anchors.has(Math.round(Number(v) * 100) / 100) || [...anchors].some((a) => Math.abs(a - Number(v)) < 0.08)) ? 5 : 0);
      return {
        type: "line",
        data: {
          labels,
          datasets: [
            { label: t("bowl.p_ac_axis") || "P_ac", data: freshArray(w.p_ac_w), borderColor: "#2dd4a8", backgroundColor: "transparent", borderWidth: 2, pointRadius: pointR, pointBackgroundColor: "#2dd4a8" },
            { label: t("bowl.eff_axis") || "η", data: freshArray(w.efficiency), borderColor: "#c084fc", backgroundColor: "transparent", borderWidth: 2, pointRadius: pointR, pointBackgroundColor: "#c084fc", yAxisID: "y1" },
            { label: "T_I", data: freshArray(w.t_at_f0), borderColor: "#3b9eff", backgroundColor: "transparent", borderWidth: 1.5, borderDash: [4, 3], pointRadius: 0, yAxisID: "y1" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          scales: {
            x: { title: { display: true, text: "f (MHz) · wide 0.5–22 · *6=CALIB" } },
            y: { title: { display: true, text: "P_ac (W)" } },
            y1: { position: "right", min: 0, max: 1, grid: { drawOnChartArea: false }, title: { display: true, text: "η / T_I" } },
          },
          plugins: {
            title: { display: true, text: t("bowl.freq_compare_wide_title") || "P_ac(f) / η(f) · anchors 1/3/6*/10/19" },
          },
        },
      };
    }
    return null;
  }

  async function openChartModal(canvasId, infoKey) {
    if (String(canvasId || "").indexOf("Bowl") >= 0) {
      try { ensureBowl(); } catch (_) { /* ignore */ }
    }
    const getter = CHART_INSTANCE_MAP[canvasId];
    const src = getter ? getter() : null;
    const modal = $("chartModal");
    const canvas = $("chartModalCanvas");
    if (!modal || !canvas) return;
    $("chartModalTitle").textContent = resolveChartTitle(canvasId, infoKey);
    const capKey = CHART_CAPTION_KEY[canvasId];
    const cap = capKey ? t(capKey) : "";
    const wideNote = t("bowl.expand_wide_note");
    $("chartModalCaption").textContent = ((cap && cap !== capKey) ? cap : "") + ((wideNote && wideNote !== "bowl.expand_wide_note") ? (" · " + wideNote) : "");
    $("chartModalInfo").innerHTML = formatInfoHtml(t(infoKey || ""));

    if (modalChart) {
      try { modalChart.destroy(); } catch (_) { /* ignore */ }
      modalChart = null;
    }
    if (modalWideAbort) {
      try { modalWideAbort.abort(); } catch (_) { /* ignore */ }
    }
    modalWideAbort = new AbortController();

    modal.classList.remove("hidden");
    modal.removeAttribute("hidden");
    document.body.style.overflow = "hidden";

    let cfg = null;
    const wideIds = {
      chartBowlSpectrum: 1, chartBowlPhase: 1, chartBowlGlue: 1, chartBowlTi: 1,
      chartBowlField: 1, chartBowlDia: 1, chartBowlEnergy: 1, chartBowlF0: 1,
    };
    if (wideIds[canvasId]) {
      try {
        // Ensure server has current params before wide fetch
        await postJSON("/api/bowl/params", bowlPayload(), modalWideAbort.signal);
        cfg = await fetchWideChartConfig(canvasId);
      } catch (err) {
        if (err && err.name === "AbortError") return;
        console.warn("wide fetch", canvasId, err);
      }
    }
    if (!cfg) cfg = cloneChartConfig(src);
    if (cfg) {
      try {
        const existing = (typeof Chart.getChart === "function") ? Chart.getChart(canvas) : null;
        if (existing) existing.destroy();
      } catch (_) { /* ignore */ }
      modalChart = new Chart(canvas, cfg);
    } else {
      modalChart = new Chart(canvas, {
        type: "line",
        data: { labels: [], datasets: [{ label: "—", data: [], borderColor: "#3b9eff", pointRadius: 0 }] },
        options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false } } },
      });
    }
    requestAnimationFrame(() => {
      try { if (modalChart) { modalChart.resize(); modalChart.update("none"); } } catch (_) { /* ignore */ }
    });
  }

  function closeChartModal() {
    const modal = $("chartModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("hidden", "");
    document.body.style.overflow = "";
    if (modalChart) {
      try { modalChart.destroy(); } catch (_) { /* ignore */ }
      modalChart = null;
    }
  }

  document.addEventListener("click", (ev) => {
    const expandBtn = ev.target.closest("[data-chart-expand]");
    if (expandBtn) {
      ev.preventDefault();
      openChartModal(expandBtn.getAttribute("data-chart-expand"), expandBtn.getAttribute("data-info-key"));
      return;
    }
    const infoBtn = ev.target.closest("[data-chart-info]");
    if (infoBtn) {
      ev.preventDefault();
      openChartModal(infoBtn.getAttribute("data-chart-info"), infoBtn.getAttribute("data-info-key"));
      return;
    }
    if (ev.target.closest("[data-modal-close]")) {
      ev.preventDefault();
      closeChartModal();
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    const modal = $("chartModal");
    if (modal && !modal.classList.contains("hidden")) closeChartModal();
  });


  document.documentElement.setAttribute("data-theme", localStorage.getItem(THEME_KEY) || "dark");
  $("bowlPiezoH").disabled = true;
  let _resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(resizeAllCharts, 120);
  });
  initTherapyCharts();
  setSettingsCollapsed(isSettingsCollapsed());
  syncPowerPresetChips("therapyPowerPresets", ($("driveLevel") || { value: 1 }).value);
  syncPowerPresetChips("bowlPowerPresets", ($("bowlDrive") || { value: 1 }).value);
  if (localStorage.getItem(LANG_KEY) && localStorage.getItem(LANG_KEY) !== window.__LANG__) setLang(localStorage.getItem(LANG_KEY));
  else applyI18n();
  updateCollapseLabels(isSettingsCollapsed());
  // Default landing tab: Akustik-Schale (not therapy)
  switchTab("bowl");
  loadPrograms().then(refresh);
})();
