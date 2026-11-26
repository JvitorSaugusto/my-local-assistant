/* Modo Autônomo Isolado — UI 100% com ícones SVG (sem emojis), polling inteligente, Diff e controle por fase */
(function () {
  "use strict";

  const API_BASE = "/api/autonomous";

  const ICONS = {
    cpu: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/></svg>',
    plus: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
    refresh: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/></svg>',
    close: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    play: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>',
    pause: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>',
    stop: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>',
    trash: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>',
    fileText: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
    gitBranch: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>',
    gitCommit: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><line x1="1.05" y1="12" x2="7" y2="12"/><line x1="17.01" y1="12" x2="22.96" y2="12"/></svg>',
    codeDiff: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
    alert: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    shield: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    check: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    download: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
    activity: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    copy: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
  };

  function icon(name) {
    return `<span class="auto-ico" aria-hidden="true">${ICONS[name] || ""}</span>`;
  }

  const STATUS_META = {
    created: { label: "Criada", color: "#94a3b8" },
    preflight: { label: "Pre-flight", color: "#38bdf8" },
    waiting_confirmation: { label: "Aguardando Confirmação", color: "#f59e0b" },
    planning: { label: "Planejando", color: "#38bdf8" },
    executing: { label: "Executando", color: "#3b82f6" },
    phase_gate: { label: "Aprovação de Fase", color: "#f59e0b" },
    auditing: { label: "Auditando", color: "#a855f7" },
    final_review: { label: "Juiz Final", color: "#c084fc" },
    paused: { label: "Pausada", color: "#eab308" },
    done: { label: "Concluída", color: "#22c55e" },
    done_with_blockers: { label: "Concluída c/ Bloqueios", color: "#f97316" },
    failed: { label: "Falhou", color: "#ef4444" },
    cancelled: { label: "Cancelada", color: "#64748b" },
  };

  const ui = {
    open: false,
    missions: [],
    workspaces: [],
    selectedId: null,
    selectedDetail: null,
    events: [],
    showCreate: false,
    pollTimer: null,
    reportText: null,
    reportFilename: null,
    diffData: null,
    lastRenderSig: "",
  };

  function esc(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function detectActiveWorkspace() {
    try {
      if (window.state && Array.isArray(window.state.chats) && window.state.activeId != null) {
        const active = window.state.chats.find((c) => c.id === window.state.activeId);
        if (active && active.workspace_path) return active.workspace_path;
      }
      const wsInput = document.querySelector("#workspace-input, #workspacePath, [data-workspace-path]");
      if (wsInput) {
        const val = wsInput.value || wsInput.getAttribute("data-workspace-path");
        if (val) return val;
      }
      return localStorage.getItem("autonomous_last_workspace") || "";
    } catch {
      return "";
    }
  }

  async function loadKnownWorkspaces() {
    try {
      const res = await fetch("/api/workspaces");
      if (!res.ok) return;
      const data = await res.json();
      const list = Array.isArray(data) ? data : (data.workspaces || []);
      ui.workspaces = list
        .map((w) => (typeof w === "string" ? w : (w.path || w.workspace_path || "")))
        .filter(Boolean);
    } catch {
      // opcional
    }
  }

  async function api(path, options) {
    const res = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...(options || {}),
    });
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!res.ok) {
      throw new Error((data && (data.detail || data.message)) || `Erro HTTP ${res.status}`);
    }
    return data;
  }

  function injectStyles() {
    if (document.getElementById("auto-mode-styles")) return;
    const style = document.createElement("style");
    style.id = "auto-mode-styles";
    style.textContent = `
      .auto-ico { display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
      .auto-trigger-btn {
        display: inline-flex; align-items: center; gap: 6px;
        background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
        border-radius: 8px; padding: 6px 11px; font-size: 13px; font-weight: 500;
        cursor: pointer; transition: background 0.15s, border-color 0.15s;
      }
      .auto-trigger-btn:hover { background: #334155; border-color: #60a5fa; }
      .auto-trigger-btn.floating {
        position: fixed; right: 18px; bottom: 78px; z-index: 9500;
        box-shadow: 0 8px 24px rgba(0,0,0,0.45);
      }
      .auto-badge-dot {
        width: 8px; height: 8px; border-radius: 999px; background: #22c55e;
        display: none; box-shadow: 0 0 8px #22c55e;
      }
      .auto-badge-dot.active { display: inline-block; }

      #auto-modal-backdrop {
        position: fixed; inset: 0; background: rgba(2, 6, 23, 0.72);
        z-index: 9990; display: none; align-items: center; justify-content: center;
        padding: 16px; backdrop-filter: blur(3px);
      }
      #auto-modal-backdrop.open { display: flex; }
      .auto-modal {
        width: min(1140px, 96vw); height: min(88vh, 840px);
        background: #0f172a; color: #e2e8f0; border: 1px solid #334155;
        border-radius: 14px; display: flex; flex-direction: column; overflow: hidden;
        box-shadow: 0 24px 64px rgba(0, 0, 0, 0.65); font-family: system-ui, -apple-system, sans-serif;
      }
      .auto-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 18px; border-bottom: 1px solid #1e293b; background: #111827;
      }
      .auto-header h2 { margin: 0; font-size: 15px; display: flex; align-items: center; gap: 8px; }
      .auto-header-actions { display: flex; gap: 8px; align-items: center; }
      .auto-body { display: grid; grid-template-columns: 300px 1fr; flex: 1; min-height: 0; }
      .auto-sidebar {
        border-right: 1px solid #1e293b; overflow-y: auto; padding: 10px;
        background: #0b1220; display: flex; flex-direction: column; gap: 8px;
      }
      .auto-main { overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }
      .auto-card {
        padding: 10px 12px; border-radius: 10px; border: 1px solid #1e293b;
        background: #111827; cursor: pointer; transition: border-color 0.15s, background 0.15s;
      }
      .auto-card:hover { border-color: #475569; }
      .auto-card.selected { border-color: #3b82f6; background: #172554; }
      .auto-card-title { font-size: 13px; font-weight: 600; margin-bottom: 5px; color: #f8fafc; display: flex; align-items: center; gap: 6px; }
      .auto-card-meta { font-size: 11px; color: #94a3b8; display: flex; justify-content: space-between; gap: 6px; }
      .auto-pill {
        display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px;
        font-size: 11px; font-weight: 600; color: #0f172a;
      }
      .auto-btn {
        display: inline-flex; align-items: center; gap: 5px;
        background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
        border-radius: 7px; padding: 6px 11px; font-size: 12px; font-weight: 600; cursor: pointer;
      }
      .auto-btn:hover { background: #334155; }
      .auto-btn.xs { padding: 3px 8px; font-size: 11px; }
      .auto-btn.primary { background: #2563eb; border-color: #3b82f6; color: #fff; }
      .auto-btn.primary:hover { background: #1d4ed8; }
      .auto-btn.warn { background: #b45309; border-color: #d97706; color: #fff; }
      .auto-btn.danger { background: #991b1b; border-color: #dc2626; color: #fff; }
      .auto-btn.success { background: #15803d; border-color: #16a34a; color: #fff; }
      .auto-field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
      .auto-field label { font-size: 12px; color: #cbd5e1; font-weight: 600; }
      .auto-field input, .auto-field textarea, .auto-field select {
        background: #020617; color: #f8fafc; border: 1px solid #334155;
        border-radius: 7px; padding: 8px 10px; font-size: 13px; font-family: inherit;
      }
      .auto-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
      .auto-box {
        border: 1px solid #1e293b; background: #111827; border-radius: 10px; padding: 12px 14px;
      }
      .auto-box.alert { border-color: #d97706; background: rgba(180, 83, 9, 0.14); }
      .auto-alert-title { display: flex; align-items: center; gap: 6px; font-weight: 700; margin-bottom: 6px; color: #fbbf24; }
      .auto-bar-wrap { height: 8px; background: #1e293b; border-radius: 999px; overflow: hidden; margin-top: 6px; }
      .auto-bar-fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #22c55e); transition: width 0.25s; }
      .auto-phase { border: 1px solid #1e293b; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; background: #0b1220; }
      .auto-item { font-size: 12px; padding: 6px 0; border-top: 1px solid #1e293b; display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
      .auto-item:first-of-type { border-top: none; }
      .auto-events { max-height: 180px; overflow-y: auto; font-family: ui-monospace, monospace; font-size: 11px; color: #cbd5e1; line-height: 1.5; }
      .auto-pre {
        white-space: pre-wrap; font-family: ui-monospace, monospace; font-size: 12px;
        background: #020617; border: 1px solid #1e293b; border-radius: 8px; padding: 12px; max-height: 360px; overflow: auto;
      }
      .auto-branch-tag {
        display: inline-flex; align-items: center; gap: 4px; background: #020617;
        border: 1px solid #334155; border-radius: 6px; padding: 2px 7px; font-family: ui-monospace, monospace;
        font-size: 11px; color: #93c5fd; cursor: pointer;
      }
      .auto-branch-tag:hover { border-color: #60a5fa; }
      @media (max-width: 780px) {
        .auto-body { grid-template-columns: 1fr; }
        .auto-sidebar { max-height: 180px; border-right: none; border-bottom: 1px solid #1e293b; }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    if (document.getElementById("auto-modal-backdrop")) return;
    const backdrop = document.createElement("div");
    backdrop.id = "auto-modal-backdrop";
    backdrop.innerHTML = `
      <div class="auto-modal" role="dialog" aria-label="Modo Autônomo">
        <div class="auto-header">
          <h2>${icon("cpu")} Modo Autônomo <span style="font-size:11px;color:#94a3b8;font-weight:400;">isolado · branch auto/*</span></h2>
          <div class="auto-header-actions">
            <button type="button" class="auto-btn primary" id="auto-new-btn">${icon("plus")} Nova Missão</button>
            <button type="button" class="auto-btn" id="auto-refresh-btn">${icon("refresh")} Atualizar</button>
            <button type="button" class="auto-btn" id="auto-close-btn" aria-label="Fechar">${icon("close")}</button>
          </div>
        </div>
        <div class="auto-body">
          <div class="auto-sidebar" id="auto-sidebar"></div>
          <div class="auto-main" id="auto-main"></div>
        </div>
      </div>
    `;
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeModal();
    });
    document.body.appendChild(backdrop);

    document.getElementById("auto-close-btn").onclick = closeModal;
    document.getElementById("auto-refresh-btn").onclick = () => refreshAll(false, true);
    document.getElementById("auto-new-btn").onclick = () => {
      ui.showCreate = true;
      ui.reportText = null;
      ui.diffData = null;
      ui.lastRenderSig = "";
      renderMain();
    };
  }

  function mountTriggerButton() {
    if (document.getElementById("auto-open-btn")) return;
    const btn = document.createElement("button");
    btn.id = "auto-open-btn";
    btn.type = "button";
    btn.className = "auto-trigger-btn";
    btn.innerHTML = `<span class="auto-badge-dot" id="auto-active-dot"></span>${icon("cpu")}<span>Autônomo</span>`;
    btn.onclick = openModal;

    const buttons = Array.from(document.querySelectorAll("button"));
    const tasksBtn = buttons.find((b) => /tarefas/i.test(b.textContent || ""));
    if (tasksBtn && tasksBtn.parentElement) {
      tasksBtn.parentElement.insertBefore(btn, tasksBtn);
    } else {
      btn.classList.add("floating");
      document.body.appendChild(btn);
    }
  }

  function openModal() {
    ensureModal();
    ui.open = true;
    ui.lastRenderSig = "";
    document.getElementById("auto-modal-backdrop").classList.add("open");
    loadKnownWorkspaces();
    refreshAll(false, true);
    startPolling();
  }

  function closeModal() {
    ui.open = false;
    const bd = document.getElementById("auto-modal-backdrop");
    if (bd) bd.classList.remove("open");
    stopPolling();
  }

  function startPolling() {
    stopPolling();
    ui.pollTimer = setInterval(() => {
      if (ui.open) refreshAll(true, false);
    }, 3500);
  }

  function stopPolling() {
    if (ui.pollTimer) {
      clearInterval(ui.pollTimer);
      ui.pollTimer = null;
    }
  }

  function isUserEditingForm() {
    const main = document.getElementById("auto-main");
    if (!main) return false;
    const active = document.activeElement;
    if (!active || !main.contains(active)) return false;
    return ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName);
  }

  async function refreshAll(silent, forceRender) {
    try {
      const data = await api("/missions?limit=50");
      ui.missions = data.missions || [];
      const dot = document.getElementById("auto-active-dot");
      if (dot) dot.classList.toggle("active", (data.active_ids || []).length > 0);

      if (!ui.selectedId && ui.missions.length > 0 && !ui.showCreate) {
        ui.selectedId = ui.missions[0].id;
      }
      if (ui.selectedId && !ui.showCreate) {
        const [detail, evs] = await Promise.all([
          api(`/missions/${ui.selectedId}`),
          api(`/missions/${ui.selectedId}/events?limit=80`),
        ]);
        ui.selectedDetail = detail;
        ui.events = evs.events || [];
      }
      renderSidebar();

      if (!forceRender && isUserEditingForm()) {
        return;
      }
      const sig = JSON.stringify({
        showCreate: ui.showCreate,
        id: ui.selectedDetail && ui.selectedDetail.id,
        updated: ui.selectedDetail && ui.selectedDetail.updated_at,
        running: ui.selectedDetail && ui.selectedDetail.is_running,
        evCount: ui.events.length,
        hasRep: Boolean(ui.reportText),
        hasDiff: Boolean(ui.diffData),
      });
      if (forceRender || sig !== ui.lastRenderSig) {
        ui.lastRenderSig = sig;
        renderMain();
      }
    } catch (err) {
      if (!silent) alert("Erro no Modo Autônomo: " + err.message);
    }
  }

  function statusPill(status) {
    const info = STATUS_META[status] || { label: status, color: "#94a3b8" };
    return `<span class="auto-pill" style="background:${info.color}">${esc(info.label)}</span>`;
  }

  function renderSidebar() {
    const el = document.getElementById("auto-sidebar");
    if (!el) return;
    if (!ui.missions.length) {
      el.innerHTML = '<div style="font-size:12px;color:#64748b;padding:12px;">Nenhuma missão criada ainda. Clique em "Nova Missão".</div>';
      return;
    }
    el.innerHTML = ui.missions
      .map((m) => {
        const pct = m.progress ? m.progress.effective_pct : 0;
        const selected = !ui.showCreate && m.id === ui.selectedId ? "selected" : "";
        return `
          <div class="auto-card ${selected}" data-mid="${esc(m.id)}">
            <div class="auto-card-title">${m.is_running ? `<span style="color:#22c55e;">${icon("activity")}</span>` : ""}<span>${esc(m.title)}</span></div>
            <div style="margin-bottom:6px;">${statusPill(m.status)}</div>
            <div class="auto-card-meta">
              <span>${esc(m.mode)}</span>
              <span>${pct.toFixed(0)}% efetivo</span>
            </div>
          </div>
        `;
      })
      .join("");
    el.querySelectorAll(".auto-card").forEach((card) => {
      card.onclick = () => {
        ui.showCreate = false;
        ui.reportText = null;
        ui.diffData = null;
        ui.lastRenderSig = "";
        ui.selectedId = card.getAttribute("data-mid");
        refreshAll(false, true);
      };
    });
  }

  function renderCreateForm() {
    const wsDefault = detectActiveWorkspace();
    const datalistOpts = (ui.workspaces || []).map((w) => `<option value="${esc(w)}"></option>`).join("");
    return `
      <div class="auto-box">
        <h3 style="margin:0 0 12px 0;font-size:15px;">Nova Missão Autônoma</h3>
        <form id="auto-create-form">
          <div class="auto-grid-2">
            <div class="auto-field">
              <label>Título da Missão</label>
              <input name="title" required placeholder="Ex.: Padronizar rotas da API" />
            </div>
            <div class="auto-field">
              <label>Workspace (caminho absoluto do repositório)</label>
              <input name="workspace_path" list="auto-ws-list" required value="${esc(wsDefault)}" placeholder="C:\\Users\\...\\meu-projeto" />
              <datalist id="auto-ws-list">${datalistOpts}</datalist>
            </div>
          </div>
          <div class="auto-field">
            <label>Objetivo Principal (seja específico nos critérios de aceite)</label>
            <textarea name="objective" rows="4" required placeholder="Descreva o objetivo final, pastas/arquivos alvo e o que precisa passar nos testes..."></textarea>
          </div>
          <div class="auto-grid-2">
            <div class="auto-field">
              <label>Regras de Negócio Imutáveis (1 por linha)</label>
              <textarea name="business_rules" rows="3" placeholder="Nunca alterar conta Root interna&#10;Manter compatibilidade com /api/auth/jwt/"></textarea>
            </div>
            <div class="auto-field">
              <label>Convenções Obrigatórias (1 por linha)</label>
              <textarea name="conventions" rows="3" placeholder="Usar FastAPI Depends&#10;Cobrir rotas novas com pytest"></textarea>
            </div>
          </div>
          <div class="auto-grid-2">
            <div class="auto-field">
              <label>Modo de Execução</label>
              <select name="mode">
                <option value="">Automático (Pre-flight decide)</option>
                <option value="edit">Edição escopada (branch auto/*)</option>
                <option value="diagnostic_only">Diagnóstico somente leitura</option>
                <option value="greenfield_phased">Projeto do zero por fases (Phase Gate)</option>
              </select>
            </div>
            <div class="auto-field">
              <label>Limites (Tasks / Tentativas / Ciclos Juiz)</label>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">
                <input type="number" name="max_total_tasks" value="25" min="1" max="200" title="Máx. tasks" />
                <input type="number" name="max_retries_per_item" value="3" min="1" max="10" title="Máx. tentativas por item" />
                <input type="number" name="max_review_cycles" value="2" min="0" max="5" title="Ciclos Juiz Final" />
              </div>
            </div>
          </div>
          <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:10px 0 14px 0;font-size:12px;">
            <label><input type="checkbox" name="auto_commit" checked /> Auto-commit por item concluído</label>
            <label><input type="checkbox" name="require_phase_approval" /> Pausar para aprovação entre fases</label>
            <label><input type="checkbox" name="auto_start" checked /> Iniciar automaticamente se Pre-flight aprovar</label>
          </div>
          <div style="display:flex;gap:8px;">
            <button type="submit" class="auto-btn primary">${icon("shield")} Executar Pre-flight e Criar</button>
            <button type="button" class="auto-btn" id="auto-cancel-create">Cancelar</button>
          </div>
        </form>
      </div>
    `;
  }

  function renderMissionDetail(m) {
    const prog = m.progress || { effective_pct: 0, done_items: 0, total_items: 0, blocked_items: 0 };
    const pf = m.preflight;

    let preflightHtml = "";
    if (m.status === "waiting_confirmation" && pf) {
      preflightHtml = `
        <div class="auto-box alert">
          <div class="auto-alert-title">${icon("alert")} Pre-flight: escopo precisa de confirmação (clareza: ${esc(pf.clarity)} · chance estimada: ${esc(pf.estimated_success_band)})</div>
          ${pf.missing_info.length ? `<div style="font-size:12px;margin-bottom:6px;"><b>Faltando:</b><ul>${pf.missing_info.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
          ${pf.warnings.length ? `<div style="font-size:12px;margin-bottom:6px;"><b>Avisos:</b><ul>${pf.warnings.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
          <div class="auto-field">
            <label>Complementar regras de negócio (opcional, 1 por linha)</label>
            <textarea id="auto-confirm-rules" rows="2" placeholder="Adicione restrições extras antes de iniciar..."></textarea>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <select id="auto-confirm-mode" class="auto-btn">
              <option value="edit" ${m.mode === "edit" ? "selected" : ""}>Modo Edição</option>
              <option value="diagnostic_only" ${m.mode === "diagnostic_only" ? "selected" : ""}>Somente Diagnóstico</option>
              <option value="greenfield_phased" ${m.mode === "greenfield_phased" ? "selected" : ""}>Por Fases (Greenfield)</option>
            </select>
            <button type="button" class="auto-btn success" id="auto-btn-confirm">${icon("check")} Confirmar e Iniciar Mesmo Assim</button>
          </div>
        </div>
      `;
    }

    let phaseGateHtml = "";
    if (m.status === "phase_gate") {
      phaseGateHtml = `
        <div class="auto-box alert" style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
          <div><div class="auto-alert-title" style="margin-bottom:2px;">${icon("shield")} Phase Gate</div>Fase concluída e auditada. Revise a branch <code>${esc(m.branch_name || "")}</code> e aprove para seguir.</div>
          <button type="button" class="auto-btn success" id="auto-btn-approve-phase">${icon("check")} Aprovar Próxima Fase</button>
        </div>
      `;
    }

    const phasesHtml = (m.phases || []).length
      ? m.phases
          .map(
            (p) => `
          <div class="auto-phase">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
              <b style="font-size:13px;">Fase ${p.order}: ${esc(p.title)}</b>
              <span style="font-size:11px;color:#94a3b8;">${esc(p.status)}</span>
            </div>
            ${(p.items || [])
              .map(
                (it) => `
              <div class="auto-item">
                <div>
                  <code>${esc(it.id)}</code> ${esc(it.title)}
                  ${it.commit_sha ? `<span style="color:#22c55e;">(${esc(it.commit_sha.slice(0, 8))})</span>` : ""}
                  ${it.last_error && it.status === "blocked" ? `<div style="color:#f87171;font-size:11px;margin-top:2px;">${esc(it.last_error)}</div>` : ""}
                </div>
                <div style="display:flex;align-items:center;gap:6px;white-space:nowrap;">
                  <span style="color:#94a3b8;">${esc(it.status)} (${it.attempts})</span>
                  ${it.status === "blocked" && !m.is_running ? `<button type="button" class="auto-btn xs" data-retry-item="${esc(it.id)}">${icon("refresh")} Reexecutar</button>` : ""}
                </div>
              </div>
            `
              )
              .join("")}
          </div>
        `
          )
          .join("")
      : '<div style="font-size:12px;color:#64748b;">Plano por fases ainda não foi gerado.</div>';

    const eventsHtml = (ui.events || [])
      .map((ev) => `<div>[${esc((ev.created_at || "").slice(11, 19))}] <b>${esc(ev.event_type)}</b> — ${esc(ev.message)}</div>`)
      .join("");

    const diffBoxHtml = ui.diffData
      ? `
        <div class="auto-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
            <b>${icon("codeDiff")} Git Diff Acumulado (${(ui.diffData.commits || []).length} commit(s), ${(ui.diffData.pending_files || []).length} pendente(s))</b>
            <button class="auto-btn xs" id="auto-btn-close-diff">${icon("close")} Fechar</button>
          </div>
          <pre class="auto-pre">${esc(ui.diffData.diff || "(nenhuma alteração detectada vs commit base)")}</pre>
        </div>
      `
      : "";

    const reportBoxHtml = ui.reportText
      ? `
        <div class="auto-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;">
            <b>${icon("fileText")} Relatório Final (.md)</b>
            <div style="display:flex;gap:6px;">
              <button class="auto-btn xs primary" id="auto-btn-download-report">${icon("download")} Baixar .md</button>
              <button class="auto-btn xs" id="auto-btn-close-report">${icon("close")} Fechar</button>
            </div>
          </div>
          <pre class="auto-pre">${esc(ui.reportText)}</pre>
        </div>
      `
      : "";

    return `
      <div class="auto-box">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;">
          <div>
            <h3 style="margin:0 0 6px 0;font-size:16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">${esc(m.title)} ${statusPill(m.status)}</h3>
            <div style="font-size:12px;color:#94a3b8;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              ${m.branch_name ? `<span class="auto-branch-tag" id="auto-copy-branch" title="Copiar nome da branch">${icon("gitBranch")} ${esc(m.branch_name)} ${icon("copy")}</span>` : `<span>Branch: ainda não criada</span>`}
              <span>Modo: <b>${esc(m.mode)}</b></span>
              <span>Auto-commit: <b>${m.config.auto_commit ? "ativo" : "manual"}</b></span>
              <span>Tasks: ${m.tasks_executed}/${m.config.max_total_tasks}</span>
              <span>Revisões: ${m.review_cycles_used}/${m.config.max_review_cycles}</span>
            </div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            ${!m.is_running && ["planning", "executing", "auditing", "final_review"].includes(m.status) ? `<button class="auto-btn primary" id="auto-btn-start">${icon("play")} Iniciar</button>` : ""}
            ${m.is_running || ["executing", "planning", "auditing", "final_review"].includes(m.status) ? `<button class="auto-btn warn" id="auto-btn-pause">${icon("pause")} Pausar</button>` : ""}
            ${m.status === "paused" ? `<button class="auto-btn success" id="auto-btn-resume">${icon("play")} Retomar</button>` : ""}
            ${m.base_commit ? `<button class="auto-btn" id="auto-btn-diff">${icon("codeDiff")} Diff</button>` : ""}
            ${!m.config.auto_commit && m.branch_name && !m.is_running ? `<button class="auto-btn" id="auto-btn-commit">${icon("gitCommit")} Commitar</button>` : ""}
            ${m.has_report ? `<button class="auto-btn" id="auto-btn-report">${icon("fileText")} Relatório</button>` : ""}
            ${!["done", "done_with_blockers", "failed", "cancelled"].includes(m.status) ? `<button class="auto-btn danger" id="auto-btn-cancel">${icon("stop")} Cancelar</button>` : ""}
            ${!m.is_running ? `<button class="auto-btn" id="auto-btn-delete" title="Excluir missão">${icon("trash")}</button>` : ""}
          </div>
        </div>
        <div style="margin-top:10px;font-size:12px;color:#cbd5e1;">
          Progresso objetivo: <b>${prog.effective_pct.toFixed(1)}% efetivo</b> (${prog.done_items}/${prog.total_items} concluídos, ${prog.blocked_items} bloqueado(s))
          <div class="auto-bar-wrap"><div class="auto-bar-fill" style="width:${Math.min(100, prog.effective_pct)}%"></div></div>
        </div>
        ${m.last_error ? `<div style="margin-top:8px;font-size:12px;color:#f87171;"><b>Último erro:</b> ${esc(m.last_error)}</div>` : ""}
      </div>
      ${preflightHtml}
      ${phaseGateHtml}
      ${diffBoxHtml}
      ${reportBoxHtml}
      <div class="auto-box">
        <div style="font-weight:700;font-size:13px;margin-bottom:8px;">Fases e Checklist</div>
        ${phasesHtml}
      </div>
      <div class="auto-box">
        <div style="font-weight:700;font-size:13px;margin-bottom:6px;">Log de Eventos</div>
        <div class="auto-events" id="auto-events-box">${eventsHtml || "Sem eventos."}</div>
      </div>
    `;
  }

  function renderMain() {
    const el = document.getElementById("auto-main");
    if (!el) return;

    const prevMainScroll = el.scrollTop;
    const prevEventsEl = document.getElementById("auto-events-box");
    const prevEventsScroll = prevEventsEl ? prevEventsEl.scrollTop : 0;

    if (ui.showCreate || !ui.selectedDetail) {
      el.innerHTML = renderCreateForm();
      const form = document.getElementById("auto-create-form");
      if (form) {
        form.onsubmit = async (ev) => {
          ev.preventDefault();
          const fd = new FormData(form);
          const ws = String(fd.get("workspace_path") || "").trim();
          try { localStorage.setItem("autonomous_last_workspace", ws); } catch {}
          const lines = (name) =>
            String(fd.get(name) || "")
              .split(/\r?\n/)
              .map((s) => s.trim())
              .filter(Boolean);
          const modeVal = String(fd.get("mode") || "").trim();
          const payload = {
            title: String(fd.get("title") || "").trim(),
            workspace_path: ws,
            objective: String(fd.get("objective") || "").trim(),
            business_rules: lines("business_rules"),
            conventions: lines("conventions"),
            mode: modeVal || null,
            auto_apply_mode: !modeVal,
            auto_start: Boolean(fd.get("auto_start")),
            config: {
              max_total_tasks: Number(fd.get("max_total_tasks") || 25),
              max_retries_per_item: Number(fd.get("max_retries_per_item") || 3),
              max_review_cycles: Number(fd.get("max_review_cycles") || 2),
              auto_commit: Boolean(fd.get("auto_commit")),
              require_phase_approval: Boolean(fd.get("require_phase_approval")),
            },
          };
          try {
            const created = await api("/missions", { method: "POST", body: JSON.stringify(payload) });
            ui.showCreate = false;
            ui.selectedId = created.id;
            ui.lastRenderSig = "";
            await refreshAll(false, true);
          } catch (err) {
            alert("Falha ao criar missão: " + err.message);
          }
        };
      }
      const cancelCreate = document.getElementById("auto-cancel-create");
      if (cancelCreate) {
        cancelCreate.onclick = () => {
          ui.showCreate = false;
          ui.lastRenderSig = "";
          renderMain();
        };
      }
      return;
    }

    const m = ui.selectedDetail;
    el.innerHTML = renderMissionDetail(m);
    el.scrollTop = prevMainScroll;
    const newEventsEl = document.getElementById("auto-events-box");
    if (newEventsEl) newEventsEl.scrollTop = prevEventsScroll;

    const bind = (id, fn) => {
      const node = document.getElementById(id);
      if (node) node.onclick = fn;
    };

    bind("auto-copy-branch", async () => {
      try {
        await navigator.clipboard.writeText(m.branch_name || "");
      } catch {
        // fallback silencioso
      }
    });

    bind("auto-btn-confirm", async () => {
      const extraRules = String((document.getElementById("auto-confirm-rules") || {}).value || "")
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean);
      const overrideMode = (document.getElementById("auto-confirm-mode") || {}).value || null;
      try {
        await api(`/missions/${m.id}/confirm`, {
          method: "POST",
          body: JSON.stringify({
            override_mode: overrideMode,
            extra_business_rules: extraRules,
            auto_start: true,
          }),
        });
        await refreshAll(false, true);
      } catch (err) {
        alert(err.message);
      }
    });

    bind("auto-btn-approve-phase", async () => {
      try {
        await api(`/missions/${m.id}/approve-phase`, { method: "POST", body: JSON.stringify({ auto_start: true }) });
        await refreshAll(false, true);
      } catch (err) {
        alert(err.message);
      }
    });
    bind("auto-btn-start", async () => {
      try { await api(`/missions/${m.id}/start`, { method: "POST" }); await refreshAll(false, true); } catch (err) { alert(err.message); }
    });
    bind("auto-btn-pause", async () => {
      try { await api(`/missions/${m.id}/pause`, { method: "POST" }); await refreshAll(false, true); } catch (err) { alert(err.message); }
    });
    bind("auto-btn-resume", async () => {
      try { await api(`/missions/${m.id}/resume`, { method: "POST", body: JSON.stringify({ auto_start: true }) }); await refreshAll(false, true); } catch (err) { alert(err.message); }
    });
    bind("auto-btn-cancel", async () => {
      if (!confirm("Cancelar esta missão e limpar alterações pendentes na branch?")) return;
      try { await api(`/missions/${m.id}/cancel`, { method: "POST" }); await refreshAll(false, true); } catch (err) { alert(err.message); }
    });
    bind("auto-btn-delete", async () => {
      if (!confirm("Excluir registro desta missão?")) return;
      try {
        await api(`/missions/${m.id}`, { method: "DELETE" });
        ui.selectedId = null;
        ui.selectedDetail = null;
        ui.reportText = null;
        ui.diffData = null;
        await refreshAll(false, true);
      } catch (err) {
        alert(err.message);
      }
    });
    bind("auto-btn-diff", async () => {
      try {
        ui.diffData = await api(`/missions/${m.id}/diff`);
        ui.lastRenderSig = "";
        renderMain();
      } catch (err) {
        alert(err.message);
      }
    });
    bind("auto-btn-close-diff", () => {
      ui.diffData = null;
      ui.lastRenderSig = "";
      renderMain();
    });
    bind("auto-btn-commit", async () => {
      try {
        const res = await api(`/missions/${m.id}/commit`, { method: "POST" });
        if (!res.commit_sha) alert("Nenhuma alteração pendente para commitar.");
        await refreshAll(false, true);
      } catch (err) {
        alert(err.message);
      }
    });
    bind("auto-btn-report", async () => {
      try {
        const rep = await api(`/missions/${m.id}/report`);
        ui.reportText = rep.content;
        ui.reportFilename = rep.filename || `mission_${m.id}.md`;
        ui.lastRenderSig = "";
        renderMain();
      } catch (err) {
        alert(err.message);
      }
    });
    bind("auto-btn-close-report", () => {
      ui.reportText = null;
      ui.lastRenderSig = "";
      renderMain();
    });
    bind("auto-btn-download-report", () => {
      const blob = new Blob([ui.reportText || ""], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = ui.reportFilename || `mission_${m.id}.md`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });

    el.querySelectorAll("[data-retry-item]").forEach((btn) => {
      btn.onclick = async () => {
        const itemId = btn.getAttribute("data-retry-item");
        try {
          await api(`/missions/${m.id}/items/${itemId}/retry`, {
            method: "POST",
            body: JSON.stringify({ auto_start: true }),
          });
          await refreshAll(false, true);
        } catch (err) {
          alert(err.message);
        }
      };
    });
  }

  function boot() {
    injectStyles();
    mountTriggerButton();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
