/* Skinova simulator SPA — all UI strings from i18n (no hardcoded labels). */
(function () {
  const LANG_KEY = "skinova_lang";
  const THEME_KEY = "skinova_theme";
  let i18n = window.__I18N__ || {};
  let lang = localStorage.getItem(LANG_KEY) || window.__LANG__ || "de";
  let programs = [];
  let timer = null;
  let socHistory = [];
  let fsmHistory = [];
  let burstHistory = [];

  function t(key) {
    const parts = key.split(".");
    let cur = i18n;
    for (const p of parts) {
      if (!cur || typeof cur !== "object" || !(p in cur)) return key;
      cur = cur[p];
    }
    return typeof cur === "string" ? cur : key;
  }

  function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      const val = t(key);
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        el.placeholder = val;
      } else {
        el.textContent = val;
      }
    });
    document.title = t("app.title");
    document.querySelectorAll(".lang-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.lang === lang);
    });
  }

  async function setLang(code) {
    lang = code;
    localStorage.setItem(LANG_KEY, code);
    // Persist UI state in localStorage; reload strings without full page loss of form values
    const formState = collectSettings();
    const res = await fetch(`/api/i18n/${code}`);
    i18n = await res.json();
    applyI18n();
    // restore form
    Object.entries(formState).forEach(([k, v]) => {
      const el = document.getElementById(k);
      if (!el) return;
      if (el.type === "checkbox") el.checked = !!v;
      else el.value = v;
    });
    await loadPrograms();
    // soft navigation: update URL lang without reload
    const url = new URL(window.location.href);
    url.searchParams.set("lang", code);
    history.replaceState(null, "", url);
  }

  function collectSettings() {
    return {
      modelSelect: document.getElementById("modelSelect").value,
      programSelect: document.getElementById("programSelect").value,
      durationS: document.getElementById("durationS").value,
      modeSelect: document.getElementById("modeSelect").value,
      iSata: document.getElementById("iSata").value,
      prfHz: document.getElementById("prfHz").value,
      dutyInterp: document.getElementById("dutyInterp").value,
      limitDomain: document.getElementById("limitDomain").value,
      c0nF: document.getElementById("c0nF").value,
      vdrive: document.getElementById("vdrive").value,
      etaElec: document.getElementById("etaElec").value,
      stackEff: document.getElementById("stackEff").value,
      gelPresent: document.getElementById("gelPresent").checked,
      forceN: document.getElementById("forceN").value,
      enable2d: document.getElementById("enable2d").checked,
      pathSelect: document.getElementById("pathSelect").value,
      dtMacro: document.getElementById("dtMacro").value,
      seed: document.getElementById("seed").value,
      tWarn: document.getElementById("tWarn").value,
      tOff: document.getElementById("tOff").value,
      motionStill: document.getElementById("motionStill").value,
      motionEps: document.getElementById("motionEps").value,
      batCap: document.getElementById("batCap").value,
      runSec: document.getElementById("runSec").value,
    };
  }

  function settingsPayload() {
    const s = collectSettings();
    return {
      model: s.modelSelect,
      program_id: parseInt(s.programSelect || "1", 10),
      duration_s: parseFloat(s.durationS),
      mode: s.modeSelect,
      i_set: parseFloat(s.iSata),
      prf_hz: parseFloat(s.prfHz),
      duty_interpretation: s.dutyInterp,
      limit_domain: s.limitDomain,
      c0_nF: parseFloat(s.c0nF),
      vdrive_peak_v: parseFloat(s.vdrive),
      eta_elec: parseFloat(s.etaElec),
      stack_efficiency: parseFloat(s.stackEff),
      gel_present: !!s.gelPresent,
      force_n: parseFloat(s.forceN),
      enable_2d: !!s.enable2d,
      path: s.pathSelect,
      dt_macro_s: parseFloat(s.dtMacro) / 1000.0,
      seed: parseInt(s.seed, 10),
      t_warn_c: parseFloat(s.tWarn),
      t_off_c: parseFloat(s.tOff),
      motion_still_s: parseFloat(s.motionStill),
      motion_eps: parseFloat(s.motionEps),
      bat_capacity_wh: parseFloat(s.batCap),
    };
  }

  async function post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : "{}",
    });
    return res.json();
  }

  async function loadPrograms() {
    const model = document.getElementById("modelSelect").value;
    const res = await fetch(`/api/programs?model=${encodeURIComponent(model)}`);
    const data = await res.json();
    programs = data.programs || [];
    const sel = document.getElementById("programSelect");
    const prev = sel.value;
    sel.innerHTML = "";
    programs.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `${p.id}. ${p.name}`;
      sel.appendChild(opt);
    });
    if (prev) sel.value = prev;
    onProgramChange();
  }

  function onProgramChange() {
    const id = parseInt(document.getElementById("programSelect").value, 10);
    const p = programs.find((x) => x.id === id);
    if (!p) return;
    document.getElementById("durationS").value = p.duration_s;
    document.getElementById("modeSelect").value = p.mode;
    document.getElementById("iSata").value = p.i_sata_w_cm2;
    document.getElementById("prfHz").value = p.prf_hz || 100;
    document.getElementById("zones").value = (p.zones || []).join(", ");
  }

  function mkChart(id, label) {
    const ctx = document.getElementById(id);
    return new Chart(ctx, {
      type: "line",
      data: { labels: [], datasets: [{ label, data: [], borderWidth: 2, pointRadius: 0, tension: 0.2 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { color: getComputedStyle(document.body).getPropertyValue("--text") } } },
        scales: {
          x: { ticks: { color: "#888", maxTicksLimit: 6 }, grid: { color: "#3333" } },
          y: { ticks: { color: "#888" }, grid: { color: "#3333" } },
        },
      },
    });
  }

  const charts = {
    ix: mkChart("chartIx", "I(x)"),
    tx: mkChart("chartTx", "T(x)"),
    dose: mkChart("chartDose", "Dose"),
    soc: mkChart("chartSoc", "SoC"),
    burst: mkChart("chartBurst", "Burst"),
    fsm: mkChart("chartFsm", "FSM"),
  };

  function updateChartsFromSnap(snap, status) {
    if (!snap) return;
    const x = (snap.x_mm || []).map((v) => v.toFixed(2));
    charts.ix.data.labels = x;
    charts.ix.data.datasets[0].data = snap.i_profile || [];
    charts.ix.data.datasets[0].label = t("plots.i_x");
    charts.ix.update("none");

    charts.tx.data.labels = x;
    charts.tx.data.datasets[0].data = snap.t_profile || [];
    charts.tx.data.datasets[0].label = t("plots.t_x");
    charts.tx.update("none");

    charts.dose.data.labels = x;
    charts.dose.data.datasets[0].data = snap.dose_profile || [];
    charts.dose.data.datasets[0].label = t("plots.dose");
    charts.dose.update("none");

    socHistory.push(snap.soc);
    if (socHistory.length > 120) socHistory.shift();
    charts.soc.data.labels = socHistory.map((_, i) => i);
    charts.soc.data.datasets[0].data = socHistory;
    charts.soc.data.datasets[0].label = t("plots.soc");
    charts.soc.update("none");

    burstHistory.push(snap.burst_on ? 1 : 0);
    if (burstHistory.length > 80) burstHistory.shift();
    charts.burst.data.labels = burstHistory.map((_, i) => i);
    charts.burst.data.datasets[0].data = burstHistory;
    charts.burst.data.datasets[0].label = t("plots.burst");
    charts.burst.update("none");

    const fmap = {
      IDLE_DOCKED: 0, IDLE_UNDOCKED: 1, PROGRAMMED_WAIT: 2, RUNNING: 3,
      PAUSED_NO_CONTACT: 4, FAULT_OVERTEMP: 5, FAULT_MOTION: 6,
      FAULT_BATTERY: 7, FINISHED: 8, LOCKED_NEEDS_STATION: 9,
    };
    fsmHistory.push(fmap[snap.state] ?? -1);
    if (fsmHistory.length > 120) fsmHistory.shift();
    charts.fsm.data.labels = fsmHistory.map((_, i) => i);
    charts.fsm.data.datasets[0].data = fsmHistory;
    charts.fsm.data.datasets[0].label = t("plots.fsm");
    charts.fsm.update("none");
  }

  function renderStatus(data) {
    const snap = data.snapshot;
    document.getElementById("vState").textContent = data.state || "—";
    document.getElementById("vF0").textContent = data.f0_hz ? (data.f0_hz / 1e6).toFixed(0) + " MHz" : "—";
    document.getElementById("vLam").textContent = data.lambda_m ? (data.lambda_m * 1e3).toFixed(3) + " mm" : "—";
    document.getElementById("vZn").textContent = data.z_n_m ? (data.z_n_m * 1e3).toFixed(1) + " mm" : "—";
    document.getElementById("xHalf").value = data.x_half_m ? (data.x_half_m * 1e3).toFixed(2) + " mm" : "—";
    if (data.nvm) {
      document.getElementById("vTrem").textContent = (data.nvm.t_remaining_s || 0).toFixed(1) + " s";
    }
    document.getElementById("vSoc").textContent = ((data.soc || 0) * 100).toFixed(1) + " %";
    if (snap) {
      document.getElementById("vR1").textContent = snap.r1.toFixed(2);
      document.getElementById("vPac").textContent = snap.p_ac.toFixed(3) + " W";
      document.getElementById("vPbat").textContent = snap.p_bat.toFixed(3) + " W";
      document.getElementById("vContact").textContent = snap.contact ? t("yes") : t("no");
      document.getElementById("vVswr").textContent = snap.vswr.toFixed(2);
      document.getElementById("vTpiezo").textContent = snap.t_piezo_c.toFixed(2) + " °C";
      document.getElementById("vTskin").textContent = snap.t_skin_surface_c.toFixed(2) + " °C";
      document.getElementById("vIsata").textContent = snap.i_sata.toFixed(3);
      document.getElementById("vGel").textContent = (snap.gel_thickness_m * 1e3).toFixed(3) + " mm";
      updateChartsFromSnap(snap, data);
    }
  }

  async function refresh() {
    const res = await fetch("/api/status");
    renderStatus(await res.json());
  }

  async function applySettings() {
    const data = await post("/api/settings", settingsPayload());
    renderStatus(data);
  }

  document.querySelectorAll(".lang-btn").forEach((b) => {
    b.addEventListener("click", () => setLang(b.dataset.lang));
  });
  document.getElementById("btnTheme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(THEME_KEY, next);
  });
  document.getElementById("modelSelect").addEventListener("change", async () => {
    await applySettings();
    await loadPrograms();
  });
  document.getElementById("programSelect").addEventListener("change", onProgramChange);
  document.getElementById("btnApply").addEventListener("click", applySettings);
  document.getElementById("btnWrite").addEventListener("click", applySettings);
  document.getElementById("btnStart").addEventListener("click", async () => {
    await applySettings();
    renderStatus(await post("/api/start"));
  });
  document.getElementById("btnPause").addEventListener("click", async () => {
    renderStatus(await post("/api/pause"));
  });
  document.getElementById("btnReset").addEventListener("click", async () => {
    socHistory = []; fsmHistory = []; burstHistory = [];
    renderStatus(await post("/api/reset"));
  });
  document.getElementById("btnDock").addEventListener("click", async () => {
    renderStatus(await post("/api/dock"));
  });
  document.getElementById("btnUndock").addEventListener("click", async () => {
    renderStatus(await post("/api/undock"));
  });
  document.getElementById("btnStep").addEventListener("click", async () => {
    renderStatus(await post("/api/step"));
  });
  document.getElementById("btnRun").addEventListener("click", async () => {
    await applySettings();
    await post("/api/start");
    const sec = parseFloat(document.getElementById("runSec").value);
    renderStatus(await post("/api/run", { seconds: sec }));
  });
  document.getElementById("btnSelftest").addEventListener("click", async () => {
    const res = await fetch("/api/selftest");
    const data = await res.json();
    const ul = document.getElementById("selftestList");
    ul.innerHTML = "";
    (data.results || []).forEach((r, idx) => {
      const li = document.createElement("li");
      li.className = r.pass ? "pass" : "fail";
      const key = `selftest.a${idx + 1}`;
      li.innerHTML = `<span><span class="dot ${r.pass ? "ok" : "bad"}"></span>${t(key)}</span><b>${r.pass ? t("selftest.pass") : t("selftest.fail")}</b>`;
      ul.appendChild(li);
    });
  });
  document.getElementById("btnPng").addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = charts.ix.toBase64Image();
    a.download = "skinova_ix.png";
    a.click();
  });
  document.getElementById("btnSavePreset").addEventListener("click", () => {
    const preset = settingsPayload();
    const blob = new Blob([JSON.stringify(preset, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "skinova_preset.json";
    a.click();
  });
  document.getElementById("presetFile").addEventListener("change", async (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    const text = await file.text();
    const p = JSON.parse(text);
    if (p.model) document.getElementById("modelSelect").value = p.model;
    if (p.i_set != null) document.getElementById("iSata").value = p.i_set;
    if (p.duration_s != null) document.getElementById("durationS").value = p.duration_s;
    if (p.mode) document.getElementById("modeSelect").value = p.mode;
    if (p.path) document.getElementById("pathSelect").value = p.path;
    if (p.gel_present != null) document.getElementById("gelPresent").checked = p.gel_present;
    await applySettings();
  });

  // init
  const savedTheme = localStorage.getItem(THEME_KEY) || "dark";
  document.documentElement.setAttribute("data-theme", savedTheme);
  if (localStorage.getItem(LANG_KEY) && localStorage.getItem(LANG_KEY) !== window.__LANG__) {
    setLang(localStorage.getItem(LANG_KEY));
  } else {
    applyI18n();
  }
  loadPrograms().then(refresh);
})();
