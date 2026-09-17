/* Skinova simulator SPA — therapy + acoustic bowl. Labels via i18n only. */
(function () {
  const LANG_KEY = "skinova_lang";
  const THEME_KEY = "skinova_theme";
  let i18n = window.__I18N__ || {};
  let lang = localStorage.getItem(LANG_KEY) || window.__LANG__ || "de";
  let programs = [];
  let socHist = [], fsmHist = [], burstHist = [];
  let therapyCharts = {};
  let bowlCharts = {};
  let bowlInited = false;

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
  async function postJSON(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
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
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: true } },
        scales: {
          x: { title: { display: true, text: "" }, ticks: { maxTicksLimit: 8 }, grid: { color: Chart.defaults.borderColor } },
          y: { title: { display: true, text: "" }, grid: { color: Chart.defaults.borderColor } },
        },
      },
    });
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
    return {
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
      eta_elec: parseFloat($("etaElec").value),
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
    };
  }

  async function setLang(code) {
    lang = code;
    localStorage.setItem(LANG_KEY, code);
    const keep = settingsPayload();
    i18n = await (await fetch("/api/i18n/" + code)).json();
    applyI18n();
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
    set("vLam", data.lambda_m ? (data.lambda_m * 1e3).toFixed(3) + " mm" : "—");
    set("vZn", data.z_n_m ? (data.z_n_m * 1e3).toFixed(1) + " mm" : "—");
    if ($("xHalf")) $("xHalf").value = data.x_half_m ? (data.x_half_m * 1e3).toFixed(2) + " mm" : "—";
    if (data.nvm) set("vTrem", (data.nvm.t_remaining_s || 0).toFixed(1) + " s");
    set("vSoc", ((data.soc || 0) * 100).toFixed(1) + " %");
    if (snap) {
      set("vR1", Number(snap.r1).toFixed(2));
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

  function switchTab(name) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    $("tab-therapy").classList.toggle("hidden", name !== "therapy");
    $("tab-bowl").classList.toggle("hidden", name !== "bowl");
    if (name === "bowl") { ensureBowl(); analyzeBowl(); }
  }

  function bowlPayload() {
    const auto = $("bowlPiezoAuto").checked;
    const piezoH = $("bowlPiezoH").value;
    return {
      f0_hz: parseFloat($("bowlF0").value),
      drive_level: parseFloat($("bowlDrive").value),
      load: $("bowlLoad").value,
      piezo_material: $("bowlPiezoMat").value,
      glue_material: $("bowlGlueMat").value,
      ti_thickness_m: parseFloat($("bowlTiH").value) * 1e-3,
      ti_diameter_m: parseFloat($("bowlTiD").value) * 1e-3,
      piezo_thickness_m: auto || piezoH === "" ? null : parseFloat(piezoH) * 1e-3,
      piezo_diameter_m: parseFloat($("bowlPiezoD").value) * 1e-3,
      glue_thickness_m: parseFloat($("bowlGlueH").value) * 1e-6,
      gel_thickness_m: parseFloat($("bowlGelH").value) * 1e-3,
    };
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
    bowlCharts.energy = new Chart($("chartBowlEnergy"), {
      type: "doughnut",
      data: { labels: ["P_ac", "glue", "piezo", "Ti"], datasets: [{ data: [1,1,1,1], backgroundColor: ["#2dd4a8","#c45c26","#e6a817","#8a9ba8"], borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right" } } },
    });
    bowlCharts.field = lineChart("chartBowlField", "I(z,0)", "#3b9eff");
    if (bowlCharts.field) {
      bowlCharts.field.options.scales.x.title.text = "z (mm)";
      bowlCharts.field.options.scales.y.title.text = "I (W/cm²)";
      bowlCharts.field.options.plugins.legend.display = false;
    }
    bowlInited = true;
    labelBowl();
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
    Object.values(bowlCharts).forEach((ch) => ch && ch.update("none"));
  }

  function drawSchematic(layers) {
    const svg = $("bowlSvg");
    if (!svg || !layers) return;
    const W = 640, H = 320, pad = 36;
    const solids = layers.filter((l) => l.name !== "air");
    const heights = solids.map((l) => l.scale_group === "um"
      ? Math.max(16, Math.log10(l.thickness_m * 1e6 + 1) * 26)
      : Math.max(26, Math.min(88, l.thickness_m * 1e3 * 110)));
    const sum = heights.reduce((a, b) => a + b, 0) || 1;
    const scale = (H - 2 * pad) / sum;
    let y = pad;
    let html = `<text x="16" y="22" fill="currentColor" font-size="13">${t("bowl.schematic")}</text>`;
    solids.forEach((l, i) => {
      const h = heights[i] * scale;
      const w = 340 * (l.diameter_m ? Math.min(1, l.diameter_m / 0.02) : 0.9);
      const x0 = 110;
      html += `<rect x="${x0}" y="${y}" width="${w}" height="${h}" fill="${l.color_hint || "#888"}" stroke="#0006" rx="3"/>`;
      html += `<text x="${x0 + w + 10}" y="${y + h / 2 + 4}" fill="currentColor" font-size="12">${l.name} · ${l.thickness_display} · Z=${Number(l.z_mrayl).toFixed(2)}</text>`;
      y += h;
    });
    svg.innerHTML = html;
  }

  async function analyzeBowl() {
    ensureBowl();
    const posted = await postJSON("/api/bowl/params", bowlPayload());
    const result = posted.result || (await (await fetch("/api/bowl/analyze")).json());
    const energy = result.energy || {};
    $("bowlT").textContent = (result.t_at_f0 ?? 0).toFixed(4);
    $("bowlR").textContent = (result.r_at_f0 ?? 0).toFixed(4);
    $("bowlRes").textContent = ((result.resonance_hz || 0) / 1e6).toFixed(3) + " MHz";
    $("bowlShift").textContent = ((result.resonance_shift_hz || 0) / 1e3).toFixed(1) + " kHz";
    $("bowlPac").textContent = (energy.p_radiated_w ?? 0).toFixed(3) + " W";
    $("bowlEta").textContent = ((energy.efficiency ?? 0) * 100).toFixed(1) + " %";
    drawSchematic(result.layers || []);
    if (bowlCharts.energy) {
      bowlCharts.energy.data.datasets[0].data = [
        energy.p_radiated_w || 0, energy.p_glue_loss_w || 0, energy.p_piezo_heat_w || 0, energy.p_ti_loss_w || 0,
      ];
      bowlCharts.energy.update();
    }
    const spec = await (await fetch("/api/bowl/spectrum?n=161")).json();
    if (bowlCharts.spectrum) {
      bowlCharts.spectrum.data.labels = (spec.f_hz || []).map((v) => (v / 1e6).toFixed(2));
      bowlCharts.spectrum.data.datasets[0].data = spec.t_intensity || [];
      bowlCharts.spectrum.data.datasets[1].data = spec.r_intensity || [];
      const z = spec.z_in_mag || [];
      const zMax = Math.max(...z, 1e-9);
      bowlCharts.spectrum.data.datasets[2].data = z.map((v) => v / zMax);
      bowlCharts.spectrum.update();
    }
    const glue = await postJSON("/api/bowl/sweep", { kind: "glue", n: 36 });
    if (bowlCharts.glue) {
      bowlCharts.glue.data.labels = (glue.glue_thickness_um || []).map((v) => Number(v).toFixed(1));
      bowlCharts.glue.data.datasets[0].data = glue.p_ac_w || [];
      bowlCharts.glue.data.datasets[1].data = glue.efficiency || [];
      bowlCharts.glue.update();
    }
    const ti = await postJSON("/api/bowl/sweep", { kind: "titanium", n: 36 });
    if (bowlCharts.ti) {
      bowlCharts.ti.data.labels = (ti.ti_thickness_mm || []).map((v) => Number(v).toFixed(2));
      bowlCharts.ti.data.datasets[0].data = ti.t_at_f0 || [];
      bowlCharts.ti.data.datasets[1].data = (ti.resonance_shift_hz || []).map((v) => v / 1e6);
      bowlCharts.ti.update();
    }
    const field = await (await fetch("/api/bowl/field?nx=48&nr=24")).json();
    if (bowlCharts.field && field.i_w_cm2) {
      bowlCharts.field.data.labels = (field.z_mm || []).map((v) => Number(v).toFixed(2));
      bowlCharts.field.data.datasets[0].data = field.i_w_cm2[0] || [];
      bowlCharts.field.update();
    }
  }

  async function resetBowl() {
    const data = await (await fetch("/api/bowl/params")).json();
    const p = data.params || {};
    $("bowlF0").value = String(Math.round(p.f0_hz || 19e6));
    $("bowlDrive").value = p.drive_level ?? 1;
    $("bowlDriveVal").textContent = Number(p.drive_level ?? 1).toFixed(2);
    $("bowlLoad").value = p.load || "gel_tissue";
    $("bowlPiezoMat").value = p.piezo_material || "pzt8";
    $("bowlGlueMat").value = p.glue_material || "glue_epoxy";
    $("bowlTiH").value = ((p.ti_thickness_m || 3e-4) * 1e3).toFixed(2);
    $("bowlTiD").value = ((p.ti_diameter_m || 0.01954) * 1e3).toFixed(2);
    $("bowlPiezoAuto").checked = true;
    $("bowlPiezoH").value = "";
    $("bowlPiezoH").disabled = true;
    $("bowlPiezoD").value = ((p.piezo_diameter_m || 0.018) * 1e3).toFixed(1);
    $("bowlGlueH").value = ((p.glue_thickness_m || 1e-5) * 1e6).toFixed(0);
    $("bowlGelH").value = ((p.gel_thickness_m || 3e-4) * 1e3).toFixed(2);
    await analyzeBowl();
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
  $("bowlDrive").addEventListener("input", (e) => { $("bowlDriveVal").textContent = Number(e.target.value).toFixed(2); });
  $("bowlPiezoAuto").addEventListener("change", (e) => { $("bowlPiezoH").disabled = e.target.checked; });
  $("btnBowlAnalyze").addEventListener("click", analyzeBowl);
  $("btnBowlReset").addEventListener("click", resetBowl);

  document.documentElement.setAttribute("data-theme", localStorage.getItem(THEME_KEY) || "dark");
  $("bowlPiezoH").disabled = true;
  initTherapyCharts();
  if (localStorage.getItem(LANG_KEY) && localStorage.getItem(LANG_KEY) !== window.__LANG__) setLang(localStorage.getItem(LANG_KEY));
  else applyI18n();
  loadPrograms().then(refresh);
})();
