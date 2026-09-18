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
      bowlCharts.energy = new Chart($("chartBowlEnergy"), {
      type: "doughnut",
      data: {
        labels: ["P_ac", "glue", "piezo", "Ti"],
        datasets: [{
          data: [0.25, 0.25, 0.25, 0.25],
          backgroundColor: ["#2dd4a8", "#c45c26", "#e6a817", "#8a9ba8"],
          borderWidth: 2,
          borderColor: "#151d2c",
          hoverOffset: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12, font: { size: 11 } } },
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
      },
    });
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
      ]},
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: false,
        scales: {
          y: { title: { display: true, text: "P_ac (W)" }, grid: { color: Chart.defaults.borderColor } },
          y1: { position: "right", min: 0, max: 1, grid: { drawOnChartArea: false }, title: { display: true, text: "η" } },
          x: { title: { display: true, text: "f0 (MHz)" } },
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
    bowlCharts.temps = lineChart("chartBowlTemps", "T_piezo", "#e6a817");
    if (bowlCharts.temps) {
      bowlCharts.temps.data.datasets.push(
        { label: "T_glue", data: [], borderColor: "#c45c26", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent" },
        { label: "T_Ti", data: [], borderColor: "#8a9ba8", borderWidth: 2, pointRadius: 0, backgroundColor: "transparent" }
      );
      bowlCharts.temps.options.scales.x.title.text = "t (s)";
      bowlCharts.temps.options.scales.y.title.text = "T (°C)";
    }
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
    if (bowlCharts.ti) bowlCharts.ti.options.scales.x.title.text = t("bowl.ti_mm");
    if (bowlCharts.energy) bowlCharts.energy.data.labels = [t("bowl.p_rad"), t("bowl.p_glue"), t("bowl.p_piezo"), t("bowl.p_ti")];
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
    Object.values(bowlCharts).forEach((ch) => bumpChart(ch));
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
    const cupW = 220;
    const cupX = 80;
    const cupTop = 110;
    const cupH = Math.max(70, Math.min(140, 40 + depthMm * 12));
    const bottomH = Math.max(14, Math.min(28, (g.ti_bottom_thickness_m || 3e-4) * 4e4));
    const piezoW = Math.max(40, Math.min(cupW - 2 * wallPx - 20, ((g.piezo_diameter_m || 0.018) / 0.02) * (cupW - 40)));
    const glueH = 6;
    const piezoH = 18;
    let html = "";
    // PCB / handpiece
    html += `<rect x="${cupX + 20}" y="28" width="${cupW - 40}" height="36" rx="4" fill="#2a364a" stroke="#93a0b5"/>`;
    html += `<text x="${cupX + cupW / 2}" y="50" text-anchor="middle" fill="currentColor" font-size="12">PCB / Handstück</text>`;
    // screws
    html += `<circle cx="${cupX + 40}" cy="100" r="5" fill="#8a9ba8"/><circle cx="${cupX + cupW - 40}" cy="100" r="5" fill="#8a9ba8"/>`;
    html += `<text x="${cupX + cupW / 2}" y="98" text-anchor="middle" fill="currentColor" font-size="10">${t("bowl.schematic_screws")}</text>`;
    // Ti half-cup U-shape
    const innerL = cupX + wallPx;
    const innerR = cupX + cupW - wallPx;
    const bottomY = cupTop + cupH;
    html += `<path d="M ${cupX} ${cupTop} L ${cupX} ${bottomY + bottomH} L ${cupX + cupW} ${bottomY + bottomH} L ${cupX + cupW} ${cupTop} L ${innerR} ${cupTop} L ${innerR} ${bottomY} L ${innerL} ${bottomY} L ${innerL} ${cupTop} Z" fill="#8a9ba8" stroke="#556" stroke-width="1.5"/>`;
    html += `<text x="${cupX + cupW + 12}" y="${cupTop + 20}" fill="currentColor" font-size="11">Ti ${t("bowl.schematic_wall")}</text>`;
    html += `<text x="${cupX + cupW + 12}" y="${bottomY + bottomH / 2 + 4}" fill="currentColor" font-size="11">Ti ${t("bowl.schematic_bottom")}</text>`;
    // piezo + glue inside bottom
    const pzX = cupX + (cupW - piezoW) / 2;
    const glueY = bottomY - glueH - 1;
    const pzY = glueY - piezoH;
    html += `<rect x="${pzX}" y="${pzY}" width="${piezoW}" height="${piezoH}" fill="#e6a817" stroke="#0006" rx="2"/>`;
    html += `<rect x="${pzX}" y="${glueY}" width="${piezoW}" height="${glueH}" fill="#c45c26" stroke="#0006"/>`;
    html += `<text x="${pzX + piezoW / 2}" y="${pzY + 12}" text-anchor="middle" fill="#152033" font-size="10">PZT</text>`;
    html += `<text x="${pzX + piezoW / 2}" y="${glueY + 5}" text-anchor="middle" fill="#fff" font-size="8">glue</text>`;
    // wires: PCB → piezo, PCB → Ti wall
    html += `<path d="M ${cupX + 55} 64 L ${cupX + 55} ${pzY + 4} L ${pzX + 8} ${pzY + 4}" fill="none" stroke="#3b9eff" stroke-width="2"/>`;
    html += `<text x="${cupX + 58}" y="${pzY - 6}" fill="#3b9eff" font-size="10">${t("bowl.schematic_wire_piezo")}</text>`;
    html += `<path d="M ${cupX + cupW - 55} 64 L ${cupX + cupW - 55} ${cupTop + 30} L ${cupX + cupW - 4} ${cupTop + 30}" fill="none" stroke="#2dd4a8" stroke-width="2"/>`;
    html += `<text x="${cupX + cupW - 52}" y="${cupTop + 24}" fill="#2dd4a8" font-size="10">${t("bowl.schematic_wire_ti")}</text>`;
    // ultrasound arrows exiting outer face downward
    const ax = cupX + cupW / 2;
    const ay0 = bottomY + bottomH + 8;
    for (let i = 0; i < 5; i++) {
      const x = ax - 40 + i * 20;
      html += `<path d="M ${x} ${ay0} L ${x} ${ay0 + 28}" stroke="#3b9eff" stroke-width="2" marker-end="url(#arrow)"/>`;
    }
    html += `<defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#3b9eff"/></marker></defs>`;
    html += `<text x="${ax}" y="${ay0 + 48}" text-anchor="middle" fill="currentColor" font-size="11">${t("bowl.schematic_exit")}</text>`;
    // gel/tissue band
    html += `<rect x="${cupX}" y="${ay0 + 52}" width="${cupW}" height="28" fill="#5dade288" stroke="#3498db"/>`;
    html += `<text x="${ax}" y="${ay0 + 70}" text-anchor="middle" fill="currentColor" font-size="11">gel / tissue</text>`;
    // droplet / mist educational cue
    if (showDrop) {
      html += `<circle cx="${ax + 55}" cy="${ay0 + 18}" r="7" fill="#5dade2" opacity="0.85"/>`;
      html += `<circle cx="${ax + 62}" cy="${ay0 + 6}" r="3" fill="#a8d8ff" opacity="0.7"/>`;
      html += `<circle cx="${ax + 48}" cy="${ay0 + 4}" r="2.5" fill="#a8d8ff" opacity="0.6"/>`;
      html += `<text x="${ax + 78}" y="${ay0 + 12}" fill="currentColor" font-size="10">${t("bowl.schematic_mist")}</text>`;
    }
    // stack legend (acoustic axis)
    let ly = 40;
    html += `<text x="420" y="28" fill="currentColor" font-size="13" font-weight="600">${t("bowl.schematic_axis")}</text>`;
    const solids = (layers || []).filter((l) => l.name !== "air");
    solids.forEach((l) => {
      const h = l.scale_group === "um" ? 18 : Math.max(20, Math.min(40, (l.thickness_m || 0) * 1e3 * 40));
      html += `<rect x="420" y="${ly}" width="160" height="${h}" fill="${l.color_hint || "#888"}" stroke="#0006" rx="2"/>`;
      html += `<text x="590" y="${ly + h / 2 + 4}" fill="currentColor" font-size="11">${l.name} · ${l.thickness_display || ""}</text>`;
      ly += h + 4;
    });
    html += `<text x="420" y="${ly + 18}" fill="var(--muted)" font-size="10">${t("bowl.schematic_note")}</text>`;
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

  function applyEnergyDoughnut(phase) {
    try {
      if (!bowlEnergyCache) bowlEnergyCache = { start: null, end: null };
      if (phase) bowlEnergyPhase = phase;
      const src = bowlEnergyCache[bowlEnergyPhase] || bowlEnergyCache.end || bowlEnergyCache.start;
      if (!src) {
        renderEnergyDetail([0, 0, 0, 0]);
        return;
      }
      const parts = energyParts(src);
      // Chart.js hides an all-zero doughnut — keep a tiny placeholder only for empty state
      const allZero = parts.every((v) => v <= 0);
      const data = allZero ? [0.0001, 0, 0, 0] : parts;
      if (bowlCharts.energy) {
        bowlCharts.energy.data.labels = [t("bowl.p_rad"), t("bowl.p_glue"), t("bowl.p_piezo"), t("bowl.p_ti")];
        bowlCharts.energy.data.datasets[0].data = data;
        bumpChart(bowlCharts.energy);
      }
      renderEnergyDetail(allZero ? [0, 0, 0, 0] : parts);
      document.querySelectorAll("#bowlEnergyPhase .preset-chip").forEach((b) => {
        b.classList.toggle("active", b.dataset.phase === bowlEnergyPhase);
      });
    } catch (err) {
      console.warn("applyEnergyDoughnut", err);
    }
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
      drawSchematic(result.layers || [], result.geometry || result.params || {});
      try {
        bowlEnergyCache.start = {
          p_radiated_w: energy.p_radiated_w || 0,
          p_glue_loss_w: energy.p_glue_loss_w || 0,
          p_piezo_heat_w: energy.p_piezo_heat_w || 0,
          p_ti_loss_w: energy.p_ti_loss_w || 0,
          efficiency: energy.efficiency || 0,
        };
        bowlEnergyCache.end = Object.assign({}, bowlEnergyCache.start);
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
        postJSON("/api/bowl/sweep", { kind: "titanium", n: 36 }, signal),
        getJSON("/api/bowl/field?nx=48&nr=24", signal),
        postJSON("/api/bowl/sweep", { kind: "piezo_diameter", n: 24 }, signal),
        postJSON("/api/bowl/sweep", { kind: "f0", n: 4 }, signal),
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
      if (bowlCharts.f0 && f0c.rows) {
        bowlCharts.f0.data.labels = f0c.rows.map((r) => String(r.f0_mhz));
        bowlCharts.f0.data.datasets[0].data = f0c.rows.map((r) => r.p_ac_w);
        bowlCharts.f0.data.datasets[1].data = f0c.rows.map((r) => r.efficiency);
        bumpChart(bowlCharts.f0);
      }
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
    if (sum.energy_start) bowlEnergyCache.start = sum.energy_start;
    else if ((s.P_ac_w || []).length) {
      bowlEnergyCache.start = {
        p_radiated_w: s.P_ac_w[0] || 0,
        p_glue_loss_w: (s.P_glue_loss_w || [])[0] || 0,
        p_piezo_heat_w: (s.P_piezo_heat_w || [])[0] || 0,
        p_ti_loss_w: (s.P_ti_loss_w || [])[0] || 0,
        efficiency: (s.eta || [])[0] || 0,
      };
    }
    if (sum.energy_end) bowlEnergyCache.end = sum.energy_end;
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
    if (bowlCharts.temps) {
      bowlCharts.temps.data.labels = labels;
      bowlCharts.temps.data.datasets[0].data = (s.T_piezo_c || []).slice();
      bowlCharts.temps.data.datasets[1].data = (s.T_glue_c || []).slice();
      bowlCharts.temps.data.datasets[2].data = (s.T_ti_c || []).slice();
      clearChartYAutoscale(bowlCharts.temps);
      bumpChart(bowlCharts.temps);
      try {
        if (typeof bowlCharts.temps.resize === "function") bowlCharts.temps.resize();
      } catch (_) { /* ignore */ }
    }
    if (bowlCharts.pacEta) {
      bowlCharts.pacEta.data.labels = labels;
      bowlCharts.pacEta.data.datasets[0].data = (s.P_ac_w || []).slice();
      bowlCharts.pacEta.data.datasets[1].data = (s.eta || []).slice();
      clearChartYAutoscale(bowlCharts.pacEta);
      bumpChart(bowlCharts.pacEta);
    }
    if (bowlCharts.derate) {
      bowlCharts.derate.data.labels = labels;
      bowlCharts.derate.data.datasets[0].data = (s.drive_level || []).slice();
      bowlCharts.derate.data.datasets[1].data = (s.derate || []).slice();
      clearChartYAutoscale(bowlCharts.derate);
      bumpChart(bowlCharts.derate);
    }
    if (bowlCharts.losses) {
      bowlCharts.losses.data.labels = labels;
      bowlCharts.losses.data.datasets[0].data = (s.P_piezo_heat_w || []).slice();
      bowlCharts.losses.data.datasets[1].data = (s.P_glue_loss_w || []).slice();
      bowlCharts.losses.data.datasets[2].data = (s.P_ti_loss_w || []).slice();
      bowlCharts.losses.data.datasets[3].data = (s.glue_loss_factor || []).slice();
      clearChartYAutoscale(bowlCharts.losses);
      bumpChart(bowlCharts.losses);
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
  $("modelSelect").addEventListener("change", async () => { await applySettings(); await loadPrograms(); });
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
  document.querySelectorAll("#bowlEnergyPhase .preset-chip").forEach((b) => {
    b.addEventListener("click", () => applyEnergyDoughnut(b.dataset.phase));
  });
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
  loadPrograms().then(refresh);
})();
