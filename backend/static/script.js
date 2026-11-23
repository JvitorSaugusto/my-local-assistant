/* ============================================================
   Assistente IA Local — cliente
   Desktop + Mobile
   ============================================================ */

const API = {
  chats: "/api/chats/",
  chat: (id) => `/api/chats/${id}`,
  chatSearch: "/api/chats/search",
  chatPresets: "/api/chats/presets",
  messages: (thread_id) => `/api/ai/${thread_id}/messages`,
  tasks: (thread_id) => `/api/tasks/${thread_id}/tasks`,
  createTask: (threadId) => `/api/tasks/${threadId}`,
  updateTask: (taskId) => `/api/tasks/${taskId}`,
  deleteTask: (taskId) => `/api/tasks/${taskId}`,
  retryTask: (taskId) => `/api/tasks/${taskId}/retry`,
  taskDiff: (taskId) => `/api/tasks/${taskId}/diff`,
  revertTask: (taskId) => `/api/tasks/${taskId}/revert`,
  bulkDeleteTasks: "/api/tasks/bulk/delete",
  autocommit: "/api/tasks/autocommit",
  handoffPlan: "/api/handoff/plan",
  handoffDryrun: "/api/handoff/dryrun",
  packContent: (name) => `/api/handoff/packs/${encodeURIComponent(name)}/content`,
  packDownload: (name) => `/api/handoff/packs/${encodeURIComponent(name)}`,
  threadArtifacts: (threadId) => `/api/handoff/artifacts/${encodeURIComponent(threadId)}`,
  saveArtifact: (threadId) => `/api/handoff/artifacts/${encodeURIComponent(threadId)}`,
  deleteArtifact: (threadId, name) => `/api/handoff/artifacts/${encodeURIComponent(threadId)}/${encodeURIComponent(name)}`,
  settings: "/api/settings",
  ollamaPs: "/api/settings/ollama/ps",
  ollamaUnload: "/api/settings/ollama/unload",
  memories: "/api/memories",
  memoryItem: (id) => `/api/memories/${id}`,
  monitorStatus: "/api/monitor/status",
  monitorStart: "/api/monitor/start",
  monitorStop: "/api/monitor/stop",
  monitorBuild: "/api/monitor/build",
  monitorTestRoutes: "/api/monitor/test-routes",
  ragScope: "/api/rag/scope",
  ragLinks: "/api/rag/links",
  createTasksBatch: (threadId) => `/api/tasks/${threadId}`,
  send: "/api/ai/",
  stop: (threadId) => `/api/ai/${threadId}/stop`,
  size: (threadId) => `/api/ai/${threadId}/size`,
  live: (threadId) => `/api/ai/${threadId}/live`,
  newChat: (threadId) => `/api/ai/${threadId}/new-chat`,
  releaseTasks: (threadId) => `/api/ai/${threadId}/release-tasks`,
  rewind: (threadId) => `/api/ai/${threadId}/rewind`,
  batch: "/api/ai/batch/",
  upload: (threadId) => `/api/uploads/${encodeURIComponent(threadId)}`,
};

// Deve ser igual a ATTACHMENT_MARKER em backend/graph/utils.py
const ATTACHMENT_MARKER = "[Arquivos anexados]";
const ATTACH_EXTENSIONS = [".md", ".txt", ".py", ".json", ".csv", ".pdf", ".docx"];
const ATTACH_MAX_BYTES = 10 * 1024 * 1024;
const ATTACH_MAX_FILES = 5;

// ============================================================
// ELEMENTOS
// ============================================================

const el = {
  sidebar: document.getElementById("sidebar"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
  chatList: document.getElementById("chat-list"),
  sidebarMsg: document.getElementById("sidebar-msg"),
  btnNewChat: document.getElementById("btn-new-chat"),
  welcome: document.getElementById("welcome"),
  chatView: document.getElementById("chat-view"),
  chatTitle: document.getElementById("chat-title"),
  messages: document.getElementById("messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  btnAttach: document.getElementById("btn-attach"),
  attachInput: document.getElementById("attach-input"),
  attachments: document.getElementById("attachments"),
  btnHeavy: document.getElementById("btn-heavy"),
  btnSend: document.getElementById("btn-send"),
  btnTheme: document.getElementById("btn-theme"),
  inputSnippet: document.getElementById("task_snippet"),
  btnEnhance: document.getElementById("btn-enhance"),
  btnAudit: document.getElementById("btn-audit"),
  batchPanel: document.getElementById("batch-panel"),
  batchInput: document.getElementById("batch-input"),
  btnSendBatch: document.getElementById("btn-send-batch"),
  batchStatus: document.getElementById("batch-status"),
  btnToggleTasks: document.getElementById("btn-toggle-tasks"),
  app: document.getElementById("app"),
  scrim: document.getElementById("scrim"),
  btnAuto: document.getElementById("btn-auto"),
  btnSidebarClose: document.getElementById("btn-sidebar-close"),
  btnCloseDrawer: document.getElementById("btn-close-drawer"),
  tasksBadge: document.getElementById("tasks-badge"),
  taskSummary: document.getElementById("task-summary"),
  btnTaskFilters: document.getElementById("btn-task-filters"),
  taskFiltersAdv: document.getElementById("task-filters-adv"),
  filtersDot: document.getElementById("filters-dot"),
  bulkBar: document.getElementById("bulk-bar"),
  drawerFoot: document.getElementById("drawer-foot"),
  chatSearch: document.getElementById("chat-search"),
  btnWorkspaceChip: document.getElementById("btn-workspace-chip"),
  workspaceChipLabel: document.getElementById("workspace-chip-label"),
  connDot: document.getElementById("conn-dot"),
  connText: document.getElementById("conn-text"),
  composer: document.getElementById("composer"),
  composerFoot: document.getElementById("composer-foot"),
  btnSources: document.getElementById("btn-sources"),
  sourcesMenu: document.getElementById("sources-menu"),
  sourcesList: document.getElementById("sources-list"),
  sourcesNote: document.getElementById("sources-note"),
  sourcesCount: document.getElementById("sources-count"),
  tasksPanel: document.getElementById("tasks-panel"),
  tasksList: document.getElementById("tasks-list"),
  tasksCount: document.getElementById("tasks-count"),
  btnExecuteTasks: document.getElementById("btn-execute-tasks"),
  taskFilterSearch: document.getElementById("task-filter-search"),
  taskFilterPriority: document.getElementById("task-filter-priority"),
  taskFilterMode: document.getElementById("task-filter-mode"),
  btnClearTaskFilters: document.getElementById("btn-clear-task-filters"),
  taskSelectAll: document.getElementById("task-select-all"),
  tasksSelectedCount: document.getElementById("tasks-selected-count"),
  btnExecuteSelected: document.getElementById("btn-execute-selected"),
  btnDeleteSelected: document.getElementById("btn-delete-selected"),
  workspacePath: document.getElementById("workspace-path"),
  btnAddWorkspace: document.getElementById("btn-add-workspace"),
  workspaceList: document.getElementById("workspace-list"),
  btnBrowseWorkspace: document.getElementById("btn-browse-workspace"),
  workspaceBrowser: document.getElementById("workspace-browser"),
  wbPath: document.getElementById("wb-path"),
  wbList: document.getElementById("wb-list"),
  wbUse: document.getElementById("wb-use"),
  wbClose: document.getElementById("wb-close"),
  
  // Elementos do Modal de Tarefas
  taskModal: document.getElementById("task-modal"),
  taskForm: document.getElementById("task-form"),
  btnAddTask: document.getElementById("btn-add-task"),
  btnCancelModal: document.getElementById("btn-cancel-modal"),
  modalTitle: document.getElementById("task-modal-title"),
  inputId: document.getElementById("task_id"),
  inputTitle: document.getElementById("task_title"),
  inputDesc: document.getElementById("task_description"),
  inputFiles: document.getElementById("task_files"),
  btnImportTasks: document.getElementById('btn-import-tasks'),
  importTasksModal: document.getElementById('import-tasks-modal'),
  importTasksForm: document.getElementById('import-tasks-form'),
  btnCancelImport: document.getElementById('btn-cancel-import'),
  inputImportJson: document.getElementById('import_json_content')
};

// ============================================================
// ÍCONES SVG
// ============================================================

const ICON = {
  bubble: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.6A8.5 8.5 0 0 1 4 11.5 8.38 8.38 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5Z"/></svg>`,
  trash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M18 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>`,
  pencil: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>`,
  user: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
  bot: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4"/><path d="M8 2h8"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/></svg>`,
  copy: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>`,
  send: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/></svg>`,
  stop: `<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`,
  sun: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`,
  moon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>`,
  brain: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5a3 3 0 0 0-3 3 2.5 2.5 0 0 0-1.5 4.5A2.5 2.5 0 0 0 9 17a3 3 0 0 0 3 2"/><path d="M12 5a3 3 0 0 1 3 3 2.5 2.5 0 0 1 1.5 4.5A2.5 2.5 0 0 1 15 17a3 3 0 0 1-3 2"/><path d="M12 5v14"/></svg>`,
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>`,
  pin: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/></svg>`,
  tag: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/></svg>`,
};

// ============================================================
// ESTADO
// ============================================================

ICON.bolt = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z"/></svg>`;
ICON.spark = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z"/></svg>`;

const state = {
  chats: [],
  activeId: null,
  sending: false,
  pendingChats: new Set(),
  pollingInterval: null,
  expectedAiCount: {},
  workspacePath: "",
  workspaces: [],
  attachments: [], // File[] aguardando envio junto com a próxima mensagem
  uploading: false,
  currentTasks: [], // Guarda as tarefas exibidas em tela para edição rápida
  tasksSig: null,
  taskFilters: { q: "", status: "all", priority: "all", mode: "all" },
  selectedTaskIds: new Set(), // ids marcados para executar/excluir em lote
  chatQuery: "", // filtro da busca de conversas
  drawerTab: "tasks",
  routeModes: {}, // modo fixo por conversa: { [chatId]: "heavy" | "enhance" }
  stopRequested: false,
};

// ============================================================
// TEMA CLARO / ESCURO
// ============================================================

const HLJS_THEMES = {
  dark: "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css",
  light: "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-light.min.css",
};

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const link = document.getElementById("hljs-theme");
  if (link) link.href = HLJS_THEMES[theme];
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "light" ? "#f6f7f9" : "#0e0f13";
  if (el.btnTheme) {
    el.btnTheme.innerHTML = theme === "light" ? ICON.moon : ICON.sun;
    el.btnTheme.title = theme === "light" ? "Mudar para tema escuro" : "Mudar para tema claro";
  }
  try { localStorage.setItem("assistant_theme", theme); } catch {}
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  applyTheme(current === "light" ? "dark" : "light");
}

// ============================================================
// HORÁRIO / TEMPO DE RESPOSTA
// ============================================================

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function formatElapsed(sec) {
  if (sec == null || isNaN(sec)) return "";
  if (sec < 60) return `${sec.toFixed(1).replace(".", ",")} s`;
  return `${Math.floor(sec / 60)} min ${Math.round(sec % 60)} s`;
}

setInterval(() => {
  document.querySelectorAll('[data-typing="1"]').forEach((w) => {
    const t = w.querySelector(".typing-timer");
    if (t) t.textContent = `${Math.floor((Date.now() - Number(w.dataset.start)) / 1000)} s`;
  });
}, 1000);

// ============================================================
// MARKDOWN
// ============================================================

if (typeof marked === "undefined") console.error("[Markdown] marked.js não foi carregado.");
if (typeof DOMPurify === "undefined") console.error("[Markdown] DOMPurify não foi carregado.");

if (typeof marked !== "undefined") {
  marked.use({ gfm: true, breaks: true });
}

function escapeHtml(str = "") {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function renderContent(text = "") {
  const source = String(text);
  if (typeof marked === "undefined") return `<p>${escapeHtml(source)}</p>`;
  const html = marked.parse(source);
  if (typeof DOMPurify === "undefined") return html;
  return DOMPurify.sanitize(html, { ADD_ATTR: ["class", "target", "rel"] });
}

function enhanceCodeBlocks(container) {
  if (typeof hljs === "undefined") return;
  const blocks = container.querySelectorAll("pre code");
  blocks.forEach((block) => {
    if (!block.dataset.highlighted) {
      hljs.highlightElement(block);
      block.dataset.highlighted = "true";
    }
    const pre = block.parentElement;
    if (!pre || pre.querySelector(".code-copy")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "code-copy";
    btn.title = "Copiar código";
    btn.innerHTML = ICON.copy;
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(block.textContent || "");
        btn.innerHTML = ICON.check;
        btn.classList.add("copied");
        setTimeout(() => {
          btn.innerHTML = ICON.copy;
          btn.classList.remove("copied");
        }, 1200);
      } catch (error) {
        console.error("[Clipboard] Falha ao copiar:", error);
      }
    });
    pre.appendChild(btn);
  });
}

// ============================================================
// API
// ============================================================

function setConn(ok) {
  if (!el.connDot) return;
  el.connDot.classList.toggle("ok", ok);
  el.connDot.classList.toggle("off", !ok);
  if (el.connText) el.connText.textContent = ok ? "servidor online" : "sem conexão";
}

async function api(url, options = {}) {
  let res;
  try {
    res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch (error) {
    setConn(false);
    throw error;
  }
  setConn(true);

  if (!res.ok) {
    let detail = "";
    try {
      const errorData = await res.json();
      detail = errorData?.detail || errorData?.message || "";
    } catch {}
    throw new Error(detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status}`);
  }

  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

function setSidebarMsg(msg = "", isError = false) {
  el.sidebarMsg.textContent = msg;
  el.sidebarMsg.style.color = isError ? "var(--danger)" : "var(--faint)";
}

// ============================================================
// WORKSPACES
// ============================================================

function loadWorkspaces() {
  try {
    const saved = JSON.parse(localStorage.getItem("assistant_workspaces") || "[]");
    state.workspaces = Array.isArray(saved) ? saved : [];
    const active = localStorage.getItem("assistant_workspace_active");
    if (active === "") {
      state.workspacePath = "";
    } else if (active && state.workspaces.includes(active)) {
      state.workspacePath = active;
    } else if (state.workspaces.length) {
      state.workspacePath = state.workspaces[0];
    }
  } catch (error) {
    state.workspaces = [];
    state.workspacePath = "";
  }
  renderWorkspaces();
}

function saveWorkspaces() {
  localStorage.setItem("assistant_workspaces", JSON.stringify(state.workspaces));
  localStorage.setItem("assistant_workspace_active", state.workspacePath);
  schedulePinSave();
}

function renderWorkspaces() {
  syncWorkspaceChip();
  loadRagScope();
  el.workspaceList.innerHTML = "";
  if (!state.workspaces.length) {
    el.workspaceList.innerHTML = `<div class="workspace-empty">Nenhum diretório adicionado (usando modo pessoal sem projeto).</div>`;
    el.workspacePath.value = "";
    return;
  }
  const noneItem = document.createElement("div");
  noneItem.className = "workspace-item" + (!state.workspacePath ? " active" : "");
  noneItem.innerHTML = `<button type="button" class="workspace-select" title="Usar sem projeto vinculado (anexos globais e conversas pessoais)">Sem projeto (modo pessoal)</button>`;
  noneItem.querySelector(".workspace-select").addEventListener("click", () => setActiveWorkspace(""));
  el.workspaceList.appendChild(noneItem);
  state.workspaces.forEach((workspace) => {
    const parts = String(workspace || "").split(/[\\/]/).filter(Boolean);
    const name = parts[parts.length - 1] || workspace;
    const parent = parts.length > 1 ? (parts.length > 2 ? `…/${parts[parts.length - 2]}` : parts[0]) : "";
    const item = document.createElement("div");
    item.className = "workspace-item" + (workspace === state.workspacePath ? " active" : "");
    item.innerHTML = `
      <button type="button" class="workspace-select workspace-select-rich" title="${escapeHtml(workspace)}">
        <span class="ws-name">${escapeHtml(name)}</span>
        ${parent ? `<span class="ws-path">${escapeHtml(parent)}</span>` : ""}
      </button>
      <button type="button" class="workspace-remove" title="Remover diretório">×</button>
    `;
    item.querySelector(".workspace-select").addEventListener("click", () => setActiveWorkspace(workspace));
    item.querySelector(".workspace-remove").addEventListener("click", () => removeWorkspace(workspace));
    el.workspaceList.appendChild(item);
  });
  el.workspacePath.value = state.workspacePath;
}

function setActiveWorkspace(workspace) {
  state.workspacePath = workspace;
  saveWorkspaces();
  renderWorkspaces();
}

function addWorkspace() {
  const path = el.workspacePath.value.trim();
  if (!path) return;
  if (!state.workspaces.includes(path)) state.workspaces.push(path);
  state.workspacePath = path;
  saveWorkspaces();
  renderWorkspaces();
}

function removeWorkspace(workspace) {
  state.workspaces = state.workspaces.filter((item) => item !== workspace);
  if (state.workspacePath === workspace) state.workspacePath = state.workspaces[0] || "";
  saveWorkspaces();
  renderWorkspaces();
}

// ============================================================
// NAVEGADOR DE PASTAS DO SERVIDOR
// O caminho do workspace vale no PC onde o backend roda; aqui você escolhe a pasta lá, de qualquer aparelho.
// ============================================================

const WB = { current: null };

function renderWorkspaceBrowser() {
  const data = WB.current;
  if (!data) return;
  el.wbPath.textContent = data.roots ? "Pastas raiz do servidor" : data.path;
  const items = [];
  if (data.parent !== null) {
    items.push(`<button type="button" class="wb-item" data-path="${escapeHtml(data.parent)}">↩ Voltar</button>`);
  }
  data.dirs.forEach((dir) => {
    items.push(
      `<button type="button" class="wb-item" data-path="${escapeHtml(dir.path)}">📁 ${escapeHtml(dir.name)}` +
        `${dir.is_repo ? '<span class="wb-badge">git</span>' : ""}</button>`
    );
  });
  el.wbList.innerHTML = items.join("") || `<div class="wb-empty">Nenhuma subpasta aqui.</div>`;
  el.wbUse.classList.toggle("hidden", !!data.roots);
}

async function loadWorkspaceBrowser(path = "") {
  el.wbList.innerHTML = `<div class="wb-empty">Carregando…</div>`;
  try {
    WB.current = await api(`/api/workspaces/browse?path=${encodeURIComponent(path)}`);
    renderWorkspaceBrowser();
  } catch (error) {
    WB.current = null;
    el.wbPath.textContent = "";
    el.wbUse.classList.add("hidden");
    el.wbList.innerHTML = `<div class="wb-empty">${escapeHtml(error.message)}</div>`;
  }
}

function toggleWorkspaceBrowser(open) {
  const show = open ?? el.workspaceBrowser.classList.contains("hidden");
  el.workspaceBrowser.classList.toggle("hidden", !show);
  if (show) loadWorkspaceBrowser("");
}

function useBrowsedWorkspace() {
  if (!WB.current || WB.current.roots || !WB.current.path) return;
  el.workspacePath.value = WB.current.path;
  addWorkspace();
  toggleWorkspaceBrowser(false);
}

// ============================================================
// MOBILE SIDEBAR
// ============================================================

const SB_KEY = "assistant_sidebar_collapsed";

function isMobile() { return window.matchMedia("(max-width: 780px)").matches; }
function isOverlayDrawer() { return window.matchMedia("(max-width: 1100px)").matches; }

function updateScrim() {
  const sidebarOpen = isMobile() && el.sidebar.classList.contains("open");
  const drawerOpen = isOverlayDrawer() && el.app.classList.contains("drawer-open");
  el.scrim.classList.toggle("show", sidebarOpen || drawerOpen);
}

function sidebarIsOpen() {
  return isMobile() ? el.sidebar.classList.contains("open") : !el.app.classList.contains("sb-collapsed");
}

function openSidebar() {
  if (isMobile()) {
    el.sidebar.classList.add("open");
  } else {
    el.app.classList.remove("sb-collapsed");
    try { localStorage.setItem(SB_KEY, "0"); } catch {}
  }
  el.sidebarToggle.setAttribute("aria-expanded", "true");
  updateScrim();
}

function closeSidebar() {
  if (isMobile()) {
    el.sidebar.classList.remove("open");
  } else {
    el.app.classList.add("sb-collapsed");
    try { localStorage.setItem(SB_KEY, "1"); } catch {}
  }
  el.sidebarToggle.setAttribute("aria-expanded", "false");
  updateScrim();
}

function toggleSidebar() { if (sidebarIsOpen()) closeSidebar(); else openSidebar(); }

function setDrawerTab(tab) {
  state.drawerTab = tab;
  document.querySelectorAll(".drawer .tab").forEach((node) => {
    const on = node.dataset.tab === tab;
    node.classList.toggle("active", on);
    node.setAttribute("aria-selected", String(on));
  });
  document.querySelectorAll(".drawer .tab-panel").forEach((node) => {
    node.classList.toggle("hidden", node.dataset.panel !== tab);
  });
  el.drawerFoot.classList.toggle("hidden", tab !== "tasks");
}

function openDrawer(tab) {
  if (tab) setDrawerTab(tab);
  if (isMobile()) el.sidebar.classList.remove("open");
  el.app.classList.add("drawer-open");
  el.tasksPanel.setAttribute("aria-hidden", "false");
  el.btnToggleTasks.classList.add("active");
  updateScrim();
}

function closeDrawer() {
  el.app.classList.remove("drawer-open");
  el.tasksPanel.setAttribute("aria-hidden", "true");
  el.btnToggleTasks.classList.remove("active");
  updateScrim();
}

// Em telas largas o painel fica ao lado do chat; nas demais ele cobre a tela e precisa fechar sozinho.
function closeDrawerIfOverlay() { if (isOverlayDrawer()) closeDrawer(); }

window.addEventListener("resize", () => {
  if (!isMobile()) el.sidebar.classList.remove("open");
  el.sidebarToggle.setAttribute("aria-expanded", String(sidebarIsOpen()));
  updateScrim();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (state.sending && !event.defaultPrevented) { stopGeneration(); return; }
  if (el.app.classList.contains("drawer-open") && isOverlayDrawer()) closeDrawer();
  else if (isMobile() && el.sidebar.classList.contains("open")) closeSidebar();
});

// ============================================================
// CHAT LIST
// ============================================================

async function loadChats() {
  try {
    const data = await api(API.chats);
    state.chats = Array.isArray(data) ? data : (data?.chats ?? []);
    renderChatList();
    setSidebarMsg(state.chats.length ? "" : "Nenhuma conversa ainda.");
  } catch (err) {
    setSidebarMsg("Não foi possível carregar o histórico.", true);
  }
}

function chatGroupLabel(iso) {
  const when = new Date(iso);
  if (isNaN(when)) return "Anteriores";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  when.setHours(0, 0, 0, 0);
  const days = Math.round((today - when) / 86400000);
  if (days <= 0) return "Hoje";
  if (days === 1) return "Ontem";
  if (days <= 7) return "Últimos 7 dias";
  if (days <= 30) return "Últimos 30 dias";
  return "Anteriores";
}

function renderChatList() {
  renderFolderBar();
  el.chatList.innerHTML = "";
  const query = state.chatQuery.trim().toLowerCase();
  const folderFilter = state.chatFolderFilter || "all";
  const tagFilter = (state.chatTagFilter || "").toLowerCase();

  const chats = state.chats
    .filter((chat) => {
      if (folderFilter === "__pinned__" && !chat.pinned) return false;
      if (folderFilter !== "all" && folderFilter !== "__pinned__" && (chat.folder || "") !== folderFilter) return false;
      if (tagFilter && !(chat.tags || []).some((t) => String(t).toLowerCase() === tagFilter)) return false;
      if (!query) return true;
      const hay = [chat.title, chat.folder, ...(chat.tags || [])].join(" ").toLowerCase();
      return hay.includes(query);
    })
    .sort((a, b) => {
      if (Boolean(a.pinned) !== Boolean(b.pinned)) return a.pinned ? -1 : 1;
      return (Date.parse(b.created_at) || Date.now()) - (Date.parse(a.created_at) || Date.now());
    });

  if (!chats.length && (query || folderFilter !== "all" || tagFilter)) {
    const empty = document.createElement("li");
    empty.className = "chat-group";
    empty.textContent = "Nenhuma conversa corresponde ao filtro";
    el.chatList.appendChild(empty);
    return;
  }

  let lastGroup = null;
  chats.forEach((chat) => {
    const group = chat.pinned ? "📌 Fixadas" : chatGroupLabel(chat.created_at);
    if (group !== lastGroup) {
      const header = document.createElement("li");
      header.className = "chat-group";
      header.textContent = group;
      el.chatList.appendChild(header);
      lastGroup = group;
    }
    const li = document.createElement("li");
    li.className = "chat-item" + (chat.id === state.activeId ? " active" : "") + (chat.pinned ? " is-pinned" : "");
    li.dataset.id = chat.id;
    const metaPills = [
      chat.folder ? `<span class="chat-pill folder">${escapeHtml(chat.folder)}</span>` : "",
      ...(chat.tags || []).slice(0, 3).map((tag) => `<span class="chat-pill tag" data-filter-tag="${escapeHtml(tag)}">#${escapeHtml(tag)}</span>`),
    ].filter(Boolean).join("");
    li.innerHTML = `
      ${ICON.bubble}
      <span class="chat-item-main">
        <span class="chat-item-title">${escapeHtml(chat.title || "Nova conversa")}</span>
        ${metaPills ? `<span class="chat-item-meta">${metaPills}</span>` : ""}
      </span>
      <span class="chat-pin-sb${chat.pinned ? " on" : ""}" title="${chat.pinned ? "Desafixar do topo" : "Fixar no topo"}" role="button">${ICON.pin}</span>
      <span class="chat-org" title="Pasta e tags" role="button">${ICON.tag}</span>
      <span class="chat-edit" title="Editar título" role="button">${ICON.pencil}</span>
      <span class="chat-del" title="Excluir" role="button">${ICON.trash}</span>
    `;
    li.addEventListener("click", (event) => {
      const tagEl = event.target.closest("[data-filter-tag]");
      if (tagEl) {
        event.stopPropagation();
        const nextTag = tagEl.dataset.filterTag || "";
        state.chatTagFilter = state.chatTagFilter === nextTag ? "" : nextTag;
        renderChatList();
        return;
      }
      if (event.target.closest(".chat-del, .chat-edit, .chat-pin-sb, .chat-org")) return;
      openChat(chat.id);
    });
    li.querySelector(".chat-pin-sb").addEventListener("click", (e) => {
      e.stopPropagation();
      toggleChatSidebarPin(chat.id);
    });
    li.querySelector(".chat-org").addEventListener("click", (e) => {
      e.stopPropagation();
      openChatOrgModal(chat);
    });
    li.querySelector(".chat-del").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(chat.id);
    });
    li.querySelector(".chat-edit").addEventListener("click", (e) => {
      e.stopPropagation();
      editChat(chat.id, chat.title);
    });
    el.chatList.appendChild(li);
  });
}

async function createChat() {
  try {
    const chat = await api(API.chats, { method: "POST", body: JSON.stringify({ title: "Nova conversa" }) });
    if (chat?.id != null) {
      state.chats.unshift(chat);
      renderChatList();
      await openChat(chat.id);
    } else {
      await loadChats();
    }
  } catch (err) {
    setSidebarMsg("Falha ao criar conversa.", true);
  }
}

async function deleteChat(id) {
  const doomed = state.chats.find((chat) => chat.id === id);
  if (doomed?.thread_id) api(pinUrl(doomed.thread_id), { method: "DELETE" }).catch(() => {});
  try { await api(API.chat(id), { method: "DELETE" }); } catch (err) {}
  state.chats = state.chats.filter((chat) => chat.id !== id);
  if (state.activeId === id) { state.activeId = null; showWelcome(); }
  renderChatList();
}

async function editChat(id, oldTitle) {
  const newTitle = prompt("Novo título", oldTitle);
  if (newTitle === null || newTitle.trim() === "") return;
  try {
    await fetch(API.chat(id), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: newTitle.trim() }) });
    const chat = state.chats.find(c => c.id === id);
    if (chat) chat.title = newTitle.trim();
    if (state.activeId === id) {
      const titleEl = document.querySelector("#chat-title");
      if (titleEl) titleEl.textContent = newTitle.trim();
    }
    renderChatList();
  } catch (err) {
    alert("Não foi possível atualizar o título.");
  }
}

// ============================================================
// TAREFAS PENDENTES E MODAL (CRUD)
// ============================================================

async function loadTasks(threadId = null) {
  const thread = threadId ?? state.chats.find((chat) => chat.id === state.activeId)?.thread_id;
  if (!thread) {
    renderTasks([]);
    return;
  }
  try {
    const tasks = await api(API.tasks(thread));
    const list = Array.isArray(tasks) ? tasks : [];
    const sig = JSON.stringify(list);
    state.currentTasks = list;
    if (sig === state.tasksSig) return; // evita fechar <details> a cada polling
    state.tasksSig = sig;
    renderTasks(list);
  } catch (err) {
    state.tasksSig = null;
    state.currentTasks = [];
    renderTasks([]);
    el.tasksCount.textContent = "Não foi possível carregar as tarefas.";
  }
}

function normalizeTaskDescription(desc) {
  // "**Objetivo:**" sozinho na linha vira um subtítulo
  return String(desc || "").trim().replace(/^\*\*(.+?):\*\*[ \t]*$/gm, "#### $1");
}

const STATUS_LABEL = {
  pending: "Pendente", queued: "Na fila", running: "Executando",
  review: "Em revisão", completed: "Concluída", failed: "Falhou",
};
const PRIORITY_LABEL = { high: "Alta", medium: "Média", low: "Baixa" };

function renderTasks(tasks) {
  el.tasksList.innerHTML = "";
  const pendingTasks = tasks.filter((task) => task.status === "pending");
  const failedTasks = tasks.filter((task) => task.status === "failed");
  const reviewTasks = tasks.filter((task) => task.status === "review");

  const stats = {
    all: tasks.length,
    pending: pendingTasks.length,
    active: tasks.filter(isTaskLocked).length,
    review: reviewTasks.length,
    failed: failedTasks.length,
    completed: tasks.filter((task) => task.status === "completed").length,
  };
  Object.entries(stats).forEach(([key, value]) => {
    const node = document.getElementById(`stat-${key}`);
    if (node) node.textContent = String(value);
  });
  el.taskSummary.querySelectorAll(".stat-pill").forEach((pill) => {
    pill.classList.toggle("active", pill.dataset.status === state.taskFilters.status);
  });

  const attention = pendingTasks.length + reviewTasks.length;
  el.tasksBadge.textContent = String(attention);
  el.tasksBadge.classList.toggle("hidden", attention === 0);
  el.tasksBadge.classList.toggle("warn", reviewTasks.length > 0 || failedTasks.length > 0);
  el.filtersDot.classList.toggle("hidden", state.taskFilters.priority === "all" && state.taskFilters.mode === "all");
  el.tasksCount.textContent = hasActiveTaskFilters()
    ? `${applyTaskFilters(tasks, state.taskFilters).length} de ${tasks.length}`
    : tasks.length ? `${tasks.length} tarefa(s)` : "";

  el.btnExecuteTasks.disabled = !pendingTasks.length;

  // Seleção: descarta ids de tarefas que sumiram ou que estão em execução.
  for (const id of [...state.selectedTaskIds]) {
    const current = tasks.find((task) => task.id === id);
    if (!current || isTaskLocked(current)) state.selectedTaskIds.delete(id);
  }

  if (!tasks.length) {
    el.tasksList.innerHTML = `<div class="tasks-empty">Nenhuma tarefa foi gerada nesta conversa.</div>`;
    updateTaskToolbar([], []);
    return;
  }

  const visibleTasks = applyTaskFilters(tasks, state.taskFilters);
  updateTaskToolbar(tasks, visibleTasks);

  if (!visibleTasks.length) {
    el.tasksList.innerHTML = `<div class="tasks-empty">Nenhuma tarefa corresponde aos filtros.</div>`;
    return;
  }

  visibleTasks.forEach((task) => {
    const card = document.createElement("article");
    const failed = task.status === "failed";
    const locked = isTaskLocked(task);
    const inReview = task.status === "review";
    const selected = state.selectedTaskIds.has(task.id);
    card.className =
      "task-card" + (failed ? " task-card-failed" : "") + (selected ? " task-card-selected" : "");
    card.dataset.taskId = String(task.id);
    const files = Array.isArray(task.files) ? task.files : [];
    const desc = normalizeTaskDescription(task.description);
    const snippet = String(task.code_snippet || "").trim();
    const long = desc.length > 320;
    const canPlan = task.status === "pending" || failed;
    const steps = Array.isArray(task.steps) ? task.steps : [];
    const stepsText = steps
      .map((step, i) => `${i + 1}. ${step.op}${step.op === "move_file" ? ` ${step.source} -> ${step.destination}` : `${step.path ? " " + step.path : ""}${step.branch ? " " + step.branch : ""}`}`)
      .join("\n");

    card.innerHTML = `
      <div class="task-card-head">
        <div class="task-card-titlewrap">
          <input type="checkbox" class="task-select" data-task-id="${task.id}" ${selected ? "checked" : ""} ${locked ? 'disabled title="Em execução"' : ""} aria-label="Selecionar tarefa #${task.id}" />
          <span class="task-card-id">#${task.id}</span>
          <h4 class="task-card-title">${escapeHtml(task.title || "Tarefa sem título")}</h4>
        </div>
        <div class="task-card-actions">
          <span class="task-status ${escapeHtml(task.status || "pending")}">${escapeHtml(STATUS_LABEL[task.status || "pending"] || task.status)}</span>
          <button class="btn-icon-task btn-edit-task" data-task-id="${task.id}" title="Editar">${ICON.pencil}</button>
          <button class="btn-icon-task btn-delete-task" data-task-id="${task.id}" title="Excluir">${ICON.trash}</button>
        </div>
      </div>
      ${desc ? `<div class="task-card-description md${long ? " clamped" : ""}">${renderContent(desc)}</div>` : ""}
      ${long ? `<button type="button" class="task-expand">Ver mais</button>` : ""}
      ${snippet ? `<details class="task-snippet"><summary>Código de referência</summary><pre><code>${escapeHtml(snippet)}</code></pre></details>` : ""}
      ${steps.length ? `<details class="task-snippet"><summary>Passos (${steps.length})</summary><pre><code>${escapeHtml(stepsText)}</code></pre></details>` : ""}
      ${task.last_error ? `<div class="task-error"><strong>${failed ? "Falhou" : "Última tentativa não terminou"}</strong><pre>${escapeHtml(task.last_error)}</pre></div>` : ""}
      ${files.length ? `
        <div class="task-files">
          ${files.map((file) => `<span class="task-file" title="${escapeHtml(file)}">${escapeHtml(file)}</span>`).join("")}
        </div>` : ""
      }
      ${inReview ? `<div class="task-diff" data-diff-for="${task.id}" hidden></div>` : ""}
      <div class="task-card-footer">
        <span class="task-meta"><span class="task-priority p-${escapeHtml(task.priority || "medium")}">${escapeHtml(PRIORITY_LABEL[task.priority || "medium"] || task.priority)}</span><span class="task-mode">${steps.length ? "determinística" : "modo livre"}</span></span>
        <span class="task-footer-right">
          ${canPlan ? `<button type="button" class="btn btn-ghost btn-sm btn-plan-task" data-task-id="${task.id}" title="O modelo local indica as linhas e o sistema monta e valida os passos">${steps.length ? "Replanejar" : "Planejar"}</button>` : ""}
          ${failed ? `<button type="button" class="btn btn-ghost btn-sm btn-retry-task" data-task-id="${task.id}">Reiniciar</button>` : ""}
          ${inReview ? `<button type="button" class="btn btn-ghost btn-sm btn-diff-task" data-task-id="${task.id}">Ver alterações</button><button type="button" class="btn btn-primary btn-sm btn-approve-task" data-task-id="${task.id}">Aprovar</button><button type="button" class="btn btn-ghost btn-sm btn-reject-task" data-task-id="${task.id}">Reprovar</button>` : ""}
        </span>
      </div>
    `;

    const expand = card.querySelector(".task-expand");
    if (expand) {
      expand.addEventListener("click", () => {
        const collapsed = card.querySelector(".task-card-description").classList.toggle("clamped");
        expand.textContent = collapsed ? "Ver mais" : "Ver menos";
      });
    }
    enhanceCodeBlocks(card);
    el.tasksList.appendChild(card);
  });
}

// ============================================================
// FILTROS E SELEÇÃO EM LOTE
// ============================================================

function isTaskLocked(task) {
  return task.status === "queued" || task.status === "running";
}

function taskMode(task) {
  return Array.isArray(task.steps) && task.steps.length ? "steps" : "ai";
}

function taskMatchesFilters(task, filters) {
  if (filters.status !== "all") {
    const current = task.status || "pending";
    const matches = filters.status === "active" ? current === "queued" || current === "running" : current === filters.status;
    if (!matches) return false;
  }
  if (filters.priority !== "all" && (task.priority || "medium") !== filters.priority) return false;
  if (filters.mode !== "all" && taskMode(task) !== filters.mode) return false;

  const query = String(filters.q || "").trim().toLowerCase();
  if (!query) return true;
  const haystack = [`#${task.id}`, task.title, task.description, ...(Array.isArray(task.files) ? task.files : [])]
    .join("\n")
    .toLowerCase();
  return haystack.includes(query);
}

function applyTaskFilters(tasks, filters) {
  return tasks.filter((task) => taskMatchesFilters(task, filters));
}

function hasActiveTaskFilters() {
  const f = state.taskFilters;
  return Boolean(String(f.q || "").trim()) || f.status !== "all" || f.priority !== "all" || f.mode !== "all";
}

function updateTaskToolbar(allTasks, visibleTasks) {
  const selectable = visibleTasks.filter((task) => !isTaskLocked(task));
  const selectedVisible = selectable.filter((task) => state.selectedTaskIds.has(task.id));
  const selectedTasks = allTasks.filter((task) => state.selectedTaskIds.has(task.id));
  const runnable = selectedTasks.filter((task) => task.status === "pending" || task.status === "failed");

  el.tasksSelectedCount.textContent = `${selectedTasks.length} selecionada${selectedTasks.length === 1 ? "" : "s"}`;
  el.taskSelectAll.disabled = !selectable.length;
  el.taskSelectAll.checked = selectable.length > 0 && selectedVisible.length === selectable.length;
  el.taskSelectAll.indeterminate = selectedVisible.length > 0 && selectedVisible.length < selectable.length;

  el.btnExecuteSelected.disabled = !runnable.length;
  el.btnExecuteSelected.textContent = runnable.length ? `Executar (${runnable.length})` : "Executar";
  el.btnDeleteSelected.disabled = !selectedTasks.length;
  el.btnDeleteSelected.textContent = selectedTasks.length ? `Excluir (${selectedTasks.length})` : "Excluir";

  el.bulkBar.classList.toggle("hidden", selectedTasks.length === 0);
  el.drawerFoot.classList.toggle("has-selection", selectedTasks.length > 0);
}

async function executeSelectedTasks() {
  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat?.thread_id) return;

  const selected = state.currentTasks
    .filter((task) => state.selectedTaskIds.has(task.id))
    .sort((a, b) => a.id - b.id);
  const runnable = selected.filter((task) => task.status === "pending" || task.status === "failed");
  const ignored = selected.length - runnable.length;

  if (!runnable.length) {
    alert("Nenhuma das tarefas selecionadas pode ser executada: só tarefas pendentes ou com falha.");
    return;
  }

  const lines = runnable.slice(0, 8).map((task) => `#${task.id} ${task.title}`).join("\n");
  const more = runnable.length > 8 ? `\n… e mais ${runnable.length - 8}` : "";
  const retryNote = runnable.some((task) => task.status === "failed")
    ? "\nTarefas com falha serão reiniciadas antes."
    : "";
  const ignoredNote = ignored ? `\n${ignored} selecionada(s) serão ignoradas (já concluídas ou em execução).` : "";
  const ok = confirm(
    `Executar ${runnable.length} tarefa(s) selecionada(s), em ordem de ID?\n\n${lines}${more}${retryNote}${ignoredNote}\n\n` +
      "Se uma tarefa com passos falhar, as seguintes continuam pendentes."
  );
  if (!ok) return;

  try {
    for (const task of runnable.filter((item) => item.status === "failed")) {
      await api(API.retryTask(task.id), { method: "POST" });
    }
    state.selectedTaskIds.clear();
    state.tasksSig = null;
    closeDrawerIfOverlay();
    await sendMessage(`@generate ${runnable.map((task) => task.id).join(" ")}`);
    await loadTasks(chat.thread_id);
  } catch (error) {
    alert("Não foi possível executar as tarefas selecionadas: " + error.message);
    state.tasksSig = null;
    loadTasks(chat.thread_id);
  }
}

async function deleteSelectedTasks() {
  const chat = state.chats.find((item) => item.id === state.activeId);
  const tasks = state.currentTasks.filter((task) => state.selectedTaskIds.has(task.id) && !isTaskLocked(task));
  if (!tasks.length) return;

  const lines = tasks.slice(0, 8).map((task) => `#${task.id} ${task.title}`).join("\n");
  const more = tasks.length > 8 ? `\n… e mais ${tasks.length - 8}` : "";
  if (!confirm(`Excluir ${tasks.length} tarefa(s)? Esta ação não pode ser desfeita.\n\n${lines}${more}`)) return;

  try {
    const result = await api(API.bulkDeleteTasks, {
      method: "POST",
      body: JSON.stringify({ ids: tasks.map((task) => task.id) }),
    });
    (result?.deleted || []).forEach((id) => state.selectedTaskIds.delete(id));
    if (result?.skipped?.length) {
      alert("Não foram excluídas:\n" + result.skipped.map((item) => `#${item.id}: ${item.reason}`).join("\n"));
    }
  } catch (error) {
    alert("Erro ao excluir em lote: " + error.message);
  }
  state.tasksSig = null;
  if (chat?.thread_id) await loadTasks(chat.thread_id);
}

function applyTaskFilterInputs() {
  state.taskFilters = {
    q: el.taskFilterSearch.value,
    status: state.taskFilters.status,
    priority: el.taskFilterPriority.value,
    mode: el.taskFilterMode.value,
  };
  renderTasks(state.currentTasks);
}

let taskFilterTimer = null;
function onTaskFilterChange() {
  clearTimeout(taskFilterTimer);
  taskFilterTimer = setTimeout(applyTaskFilterInputs, 120);
}

function clearTaskFilters() {
  el.taskFilterSearch.value = "";
  el.taskFilterPriority.value = "all";
  el.taskFilterMode.value = "all";
  state.taskFilters.status = "all";
  applyTaskFilterInputs();
}

function toggleSelectAllVisible(checked) {
  applyTaskFilters(state.currentTasks, state.taskFilters)
    .filter((task) => !isTaskLocked(task))
    .forEach((task) => (checked ? state.selectedTaskIds.add(task.id) : state.selectedTaskIds.delete(task.id)));
  renderTasks(state.currentTasks);
}

async function toggleTaskDiff(taskId, button) {
  const box = el.tasksList.querySelector(`[data-diff-for="${taskId}"]`);
  if (!box) return;
  if (!box.hidden) {
    box.hidden = true;
    button.textContent = "Ver alterações";
    return;
  }
  box.hidden = false;
  box.innerHTML = '<div class="task-diff-loading">Carregando alterações…</div>';
  try {
    const url = `${API.taskDiff(taskId)}?workspace=${encodeURIComponent(state.workspacePath || "")}`;
    const data = await api(url);
    const parts = [];
    if (data?.diff) parts.push(`<pre><code>${escapeHtml(data.diff)}</code></pre>`);
    (data?.new_files || []).forEach((file) => {
      parts.push(`<details open><summary>Arquivo novo: ${escapeHtml(file.path)}</summary><pre><code>${escapeHtml(file.content)}</code></pre></details>`);
    });
    if (!parts.length) parts.push('<div class="task-diff-loading">Nenhuma alteração detectada nos arquivos da tarefa.</div>');
    if (data?.truncated) parts.push('<div class="task-diff-loading">Saída truncada: veja o restante no git.</div>');
    box.innerHTML = parts.join("");
    button.textContent = "Ocultar alterações";
  } catch (error) {
    box.innerHTML = `<div class="task-error"><pre>${escapeHtml(error.message)}</pre></div>`;
  }
}

async function approveTask(taskId) {
  const chat = state.chats.find((item) => item.id === state.activeId);
  try {
    await api(API.updateTask(taskId), { method: "PUT", body: JSON.stringify({ status: "completed", last_error: null }) });
  } catch (error) {
    alert("Erro ao aprovar: " + error.message);
  }
  state.tasksSig = null;
  if (chat?.thread_id) await loadTasks(chat.thread_id);
}

async function rejectTask(taskId) {
  const chat = state.chats.find((item) => item.id === state.activeId);
  const task = state.currentTasks.find((item) => item.id === taskId);
  if (!task) return;
  const note = prompt("O que precisa ser corrigido? (será anexado à descrição e a tarefa volta para pendente)");
  if (note === null) return;
  const extra = note.trim() || "Reprovada na revisão, sem comentário.";
  if (confirm("Desfazer também as alterações que essa task fez nos arquivos?\n\nOK = desfazer tudo (volta ao estado de antes da task)\nCancelar = manter as alterações e só pedir o ajuste")) {
    try {
      const undone = await api(`${API.revertTask(taskId)}?workspace=${encodeURIComponent(state.workspacePath || "")}`, { method: "POST" });
      if (undone?.conflicts?.length) alert("Estes arquivos mudaram depois da task e NÃO foram desfeitos:\n" + undone.conflicts.join("\n"));
    } catch (error) {
      alert("Não foi possível desfazer: " + error.message);
    }
  }
  try {
    await api(API.updateTask(taskId), {
      method: "PUT",
      body: JSON.stringify({
        status: "pending",
        last_error: null,
        description: `${task.description || ""}\n\n**Correção pedida na revisão:** ${extra}`,
      }),
    });
  } catch (error) {
    alert("Erro ao reprovar: " + error.message);
  }
  state.tasksSig = null;
  if (chat?.thread_id) await loadTasks(chat.thread_id);
}

function openTaskModal(task = null) {
  if (task) {
    el.modalTitle.textContent = "Editar Tarefa";
    el.inputId.value = task.id;
    el.inputTitle.value = task.title || "";
    el.inputDesc.value = task.description || "";
    el.inputFiles.value = Array.isArray(task.files) ? task.files.join(", ") : "";
    el.inputSnippet.value = task.code_snippet || "";
  } else {
    el.modalTitle.textContent = "Nova Tarefa";
    el.inputId.value = "";
    el.inputTitle.value = "";
    el.inputDesc.value = "";
    el.inputFiles.value = "";
    el.inputSnippet.value = "";
  }
  el.taskModal.showModal();
}

async function deleteTaskAction(taskId) {
  if (!confirm("Tem certeza que deseja excluir esta tarefa?")) return;
  try {
    await api(API.deleteTask(taskId), { method: "DELETE" });
    const chat = state.chats.find((c) => c.id === state.activeId);
    if (chat?.thread_id) loadTasks(chat.thread_id);
  } catch (error) {
    alert("Erro ao deletar: " + error.message);
  }
}

async function retryTaskAction(taskId) {
  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat?.thread_id) return;
  try {
    await api(API.retryTask(taskId), { method: "POST" });
    await loadTasks(chat.thread_id);
    closeDrawerIfOverlay();
    await sendMessage(`@generate ${taskId}`);
    await loadTasks(chat.thread_id);
  } catch (error) {
    alert("Não foi possível reiniciar a tarefa: " + error.message);
    loadTasks(chat.thread_id);
  }
}

async function executePendingTasks() {
  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat?.thread_id) return;
  try {
    const tasks = await api(API.tasks(chat.thread_id));
    const pendingTasks = (Array.isArray(tasks) ? tasks : []).filter((task) => task.status === "pending");
    if (!pendingTasks.length) {
      renderTasks(tasks);
      return;
    }
    const taskIds = pendingTasks.map((task) => task.id).join(" ");
    const command = `@generate ${taskIds}`;
    closeDrawerIfOverlay();
    await sendMessage(command);
    await loadTasks(chat.thread_id);
  } catch (err) {}
}

// ============================================================
// CHAT MESSAGES & WEBSOCKET/POLLING
// ============================================================

async function openChat(id) {
  state.activeId = id;
  renderChatList();
  el.welcome.classList.add("hidden");
  el.chatView.classList.remove("hidden");
  el.btnToggleTasks.classList.remove("hidden");
  syncChips();
  autoResize();
  loadRagScope();
  el.messages.innerHTML = "";
  const chat = state.chats.find((item) => item.id === id);
  el.chatTitle.textContent = chat?.title || "Conversa";
  applyChatPin(chat);

  if (isMobile()) closeSidebar();

  if (!chat || !chat.thread_id) {
    if (!isMobile()) el.chatInput.focus();
    return;
  }
  const requestChatId = id;
  state.tasksSig = null;
  document.getElementById("btn-toggle-artifacts")?.classList.remove("hidden");
  await loadTasks(chat.thread_id);
  loadArtifacts(chat.thread_id);

  try {
    const data = await api(API.messages(chat.thread_id));
    if (state.activeId !== requestChatId) return;
    const messages = data?.messages ?? [];
    renderHistory(messages);
    refreshChatSize(chat);
    
    const aiCount = messages.filter(m => m.role === "assistant").length;
    if (state.expectedAiCount[requestChatId] && aiCount >= state.expectedAiCount[requestChatId]) {
      state.pendingChats.delete(requestChatId);
      state.expectedAiCount[requestChatId] = 0;
    }
    if (state.pendingChats.has(requestChatId)) appendTyping();
    scrollToBottom();
  } catch (err) {}
  
  if (state.activeId === requestChatId && !isMobile()) el.chatInput.focus();
}

function showWelcome() {
  el.chatView.classList.add("hidden");
  el.welcome.classList.remove("hidden");
  el.btnToggleTasks.classList.add("hidden");
  document.getElementById("btn-toggle-artifacts")?.classList.add("hidden");
  document.getElementById("btn-pin")?.classList.add("hidden");
  const chatTools_ = document.getElementById("chat-tools");
  if (chatTools_) chatTools_.style.display = "none";
  document.getElementById("chat-banner")?.classList.add("hidden");
  el.chatTitle.textContent = "Assistente Local";
  closeDrawer();
}

function renderHistory(messages) {
  el.messages.innerHTML = "";
  messages.forEach((m) => appendMessage(m.role, m.content, m.model, m));
  syncTaskTyping();
}

async function refreshMessages(chat) {
  try {
    const data = await api(API.messages(chat.thread_id));
    if (state.activeId === chat.id) renderHistory(data?.messages ?? []);
    return true;
  } catch (err) {
    return false;
  }
}

// Separa o texto digitado do bloco técnico "[Arquivos anexados]" (que só serve para o agente).
function splitAttachments(content) {
  const index = content.indexOf(ATTACHMENT_MARKER);
  if (index === -1) return { text: content, files: [] };
  const files = content.slice(index).split("\n").slice(1)
    .map((line) => line.trim())
    .filter((line) => line.startsWith("- "))
    .map((line) => line.slice(2).split("/").pop());
  return { text: content.slice(0, index).trimEnd(), files };
}

function renderUserContent({ text, files }) {
  const tag = text.match(/^\s*@(heavy|enhance)\b\s*/i);
  let badge = "";
  if (tag) {
    const kind = tag[1].toLowerCase();
    badge = `<span class="route-badge ${kind}">${kind === "heavy" ? ICON.bolt : ICON.spark}${kind === "heavy" ? "Heavy" : "Enhance"}</span>`;
    text = text.slice(tag[0].length);
  }
  const chips = files.length
    ? `<div class="msg-attachments">${files.map((name) =>
        `<span class="attachment-chip"><span class="attachment-name" title="${escapeHtml(name)}">📎 ${escapeHtml(name)}</span></span>`
      ).join("")}</div>`
    : "";
  return badge + escapeHtml(text) + chips;
}

function appendMessage(role, content, modelName = null, meta = {}) {
  const isUser = role === "user";
  const wrap = document.createElement("div");
  wrap.className = `msg ${isUser ? "user" : "assistant"}`;
  if (meta.id) wrap.dataset.messageId = meta.id;

  const roleName = isUser ? "Você" : (modelName ? `Assistente (${modelName})` : "Assistente");
  const renderedContent = isUser ? renderUserContent(splitAttachments(content)) : renderContent(content);
  const elapsed = isUser ? "" : formatElapsed(meta.elapsed_seconds);
  const metaText = [formatTime(meta.created_at), elapsed && `⏱ ${elapsed}`].filter(Boolean).join(" · ");

  const thoughts = !isUser && meta.thoughts
    ? `<details class="msg-thoughts"><summary>${ICON.brain}<span>Raciocínio</span></summary><div class="msg-thoughts-body">${renderContent(meta.thoughts)}</div></details>`
    : "";

  const footer = isUser
    ? (meta.id ? `<div class="msg-actions"><button class="msg-action btn-edit-msg" type="button" title="Editar mensagem">${ICON.pencil}</button></div>` : "")
    : `<div class="msg-footer-bar"><button class="msg-raw-toggle" type="button">Ver formato puro</button><button class="msg-raw-toggle btn-save-artifact" type="button" data-save-fmt="md" title="Salvar resposta como artefato Markdown">Salvar .md</button><button class="msg-raw-toggle btn-save-artifact" type="button" data-save-fmt="pdf" title="Salvar resposta como artefato PDF">Salvar .pdf</button></div><pre class="msg-raw hidden">${escapeHtml(content)}</pre>`;

  wrap.innerHTML = `
    <div class="msg-avatar">${isUser ? ICON.user : ICON.bot}</div>
    <div class="msg-body">
      <div class="msg-role">${escapeHtml(roleName)}${metaText ? `<span class="msg-meta">${escapeHtml(metaText)}</span>` : ""}</div>
      ${thoughts}
      <div class="msg-content">${renderedContent}</div>
      ${footer}
    </div>
  `;

  if (isUser) {
    const edit = wrap.querySelector(".btn-edit-msg");
    if (edit) edit.addEventListener("click", () => startEditMessage(wrap, meta.id, content));
  } else {
    const toggle = wrap.querySelector(".msg-raw-toggle");
    toggle.addEventListener("click", () => {
      const hidden = wrap.querySelector(".msg-raw").classList.toggle("hidden");
      toggle.textContent = hidden ? "Ver formato puro" : "Ocultar formato puro";
    });
    wrap.querySelectorAll(".btn-save-artifact").forEach((btn) => {
      btn.addEventListener("click", () => saveMessageAsArtifact(content, btn.dataset.saveFmt || "md", btn));
    });
  }
  el.messages.appendChild(wrap);
  if (!isUser) {
    enhanceCodeBlocks(wrap);
    enhanceArtifactLinks(wrap);
    enhanceTables(wrap);
  }
  return wrap;
}

function appendNotice(text) {
  const n = document.createElement("div");
  n.className = "msg-notice";
  n.textContent = text;
  el.messages.appendChild(n);
  scrollToBottom();
}

function appendTyping() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  wrap.dataset.typing = "1";
  wrap.dataset.start = String(Date.now());
  wrap.innerHTML = `<div class="msg-avatar">${ICON.bot}</div><div class="msg-body"><div class="msg-role">Assistente</div><div class="typing-row"><div class="typing"><span></span><span></span><span></span></div><span class="typing-timer">0 s</span></div></div>`;
  el.messages.appendChild(wrap);
  scrollToBottom();
  return wrap;
}

function taskStatusText(tasks) {
  const running = tasks.filter((task) => task.status === "running");
  const queued = tasks.filter((task) => task.status === "queued");
  const head = running[0] || queued[0];
  const extra = running.length + queued.length - 1;
  const prefix = running.length ? "Executando" : "Na fila:";
  return (prefix + " #" + head.id + " " + (head.title || "")).trim() + (extra > 0 ? " (+" + extra + ")" : "");
}

// Balão de "pensando" para tarefas que rodam no Celery (o POST já voltou, mas a task segue ativa).
function syncTaskTyping() {
  const busy = (state.currentTasks || []).filter(isTaskLocked);
  const existing = el.messages.querySelector('[data-typing="1"][data-kind="tasks"]');
  if (!busy.length || state.activeId == null) {
    if (existing) existing.remove();
    return;
  }
  const text = taskStatusText(busy);
  if (existing) {
    const current = existing.querySelector(".typing-label");
    if (current && current.textContent !== text) current.textContent = text;
    return;
  }
  if (el.messages.querySelector('[data-typing="1"]')) return;
  const wrap = appendTyping();
  wrap.dataset.kind = "tasks";
  const label = document.createElement("span");
  label.className = "typing-label";
  label.textContent = text;
  wrap.querySelector(".typing-row").appendChild(label);
}

function scrollToBottom() {
  requestAnimationFrame(() => { el.messages.scrollTop = el.messages.scrollHeight; });
}

function setSendButtonMode(isStop) {
  el.btnSend.innerHTML = isStop ? ICON.stop : ICON.send;
  el.btnSend.title = isStop ? "Interromper resposta" : "Enviar";
  el.btnSend.setAttribute("aria-label", isStop ? "Interromper resposta" : "Enviar");
  el.btnSend.classList.toggle("is-stop", isStop);
}

async function stopGeneration() {
  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!state.sending || !chat) return;
  state.stopRequested = true;
  try { await api(API.stop(chat.thread_id), { method: "POST" }); } catch (err) {}
}

function startEditMessage(wrap, messageId, original) {
  if (wrap.classList.contains("editing")) return;
  wrap.classList.add("editing");
  const contentEl = wrap.querySelector(".msg-content");
  const actions = wrap.querySelector(".msg-actions");
  const editor = document.createElement("div");
  editor.className = "msg-editor";
  editor.innerHTML = `<textarea rows="3"></textarea><div class="msg-editor-actions"><button type="button" class="btn btn-ghost btn-sm" data-act="cancel">Cancelar</button><button type="button" class="btn btn-primary btn-sm" data-act="save">Salvar e reenviar</button></div>`;
  const ta = editor.querySelector("textarea");
  ta.value = original;
  contentEl.classList.add("hidden");
  if (actions) actions.classList.add("hidden");
  contentEl.after(editor);
  ta.focus();

  const close = () => {
    editor.remove();
    contentEl.classList.remove("hidden");
    if (actions) actions.classList.remove("hidden");
    wrap.classList.remove("editing");
  };
  const save = () => {
    const text = ta.value.trim();
    if (text) resendEdited(messageId, text);
  };
  editor.querySelector('[data-act="cancel"]').addEventListener("click", close);
  editor.querySelector('[data-act="save"]').addEventListener("click", save);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.stopPropagation(); close(); }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
  });
}

async function resendEdited(messageId, text) {
  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat) return;
  if (state.sending) {
    await stopGeneration();
    for (let i = 0; i < 60 && state.sending; i++) await new Promise((r) => setTimeout(r, 50));
  }
  try {
    await api(API.rewind(chat.thread_id), { method: "POST", body: JSON.stringify({ message_id: messageId }) });
  } catch (err) {
    alert("Não foi possível editar a mensagem: " + err.message);
    return;
  }
  await refreshMessages(chat);
  await sendMessage(text);
}

// ============================================================
// ANEXOS
// ============================================================

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderAttachments() {
  el.attachments.innerHTML = "";
  el.attachments.classList.toggle("hidden", state.attachments.length === 0);
  el.attachments.classList.toggle("uploading", state.uploading);

  state.attachments.forEach((file, index) => {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    chip.innerHTML = `
      <span class="attachment-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
      <span class="attachment-size">${formatBytes(file.size)}</span>
      <button type="button" title="Remover anexo" aria-label="Remover anexo">×</button>
    `;
    chip.querySelector("button").addEventListener("click", () => {
      state.attachments.splice(index, 1);
      renderAttachments();
    });
    el.attachments.appendChild(chip);
  });
}

function addAttachments(fileList) {
  const rejected = [];
  for (const file of fileList) {
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!ATTACH_EXTENSIONS.includes(ext)) {
      rejected.push(`${file.name}: extensão não permitida`);
    } else if (file.size > ATTACH_MAX_BYTES) {
      rejected.push(`${file.name}: maior que ${formatBytes(ATTACH_MAX_BYTES)}`);
    } else if (file.size === 0) {
      rejected.push(`${file.name}: arquivo vazio`);
    } else if (state.attachments.length >= ATTACH_MAX_FILES) {
      rejected.push(`${file.name}: limite de ${ATTACH_MAX_FILES} anexos por mensagem`);
    } else {
      state.attachments.push(file);
    }
  }
  renderAttachments();
  if (rejected.length) alert("Alguns arquivos não foram anexados:\n" + rejected.join("\n"));
}

// Envia os anexos (no workspace ou na pasta global da conversa) e devolve o texto final.
async function composeWithAttachments(text) {
  if (state.activeId == null) {
    await createChat();
    if (state.activeId == null) return null;
  }
  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat) return null;

  state.uploading = true;
  renderAttachments();
  try {
    for (const file of state.attachments) {
      if (file.uploadedPath) continue; // já enviado numa tentativa anterior
      const form = new FormData();
      form.append("workspace_path", state.workspacePath || "");
      form.append("file", file);
      const res = await fetch(API.upload(chat.thread_id), { method: "POST", body: form });
      if (!res.ok) {
        let detail = "";
        try { detail = (await res.json())?.detail || ""; } catch {}
        throw new Error(`${file.name}: ${detail || "HTTP " + res.status}`);
      }
      file.uploadedPath = (await res.json()).path;
    }
  } catch (err) {
    alert("Falha ao enviar anexo: " + err.message);
    return null;
  } finally {
    state.uploading = false;
    renderAttachments();
  }

  const paths = state.attachments.map((file) => file.uploadedPath);
  const isGlobal = paths.every((p) => String(p || "").startsWith("@global/"));
  state.attachments = [];
  renderAttachments();

  const base = text.trim() || "Analise os arquivos anexados.";
  const hint = isGlobal
    ? "leia com read_attachment"
    : "leia com read_file_content, read_file_chunk, read_attachment ou search_in_file";
  return `${base}\n\n${ATTACHMENT_MARKER} (${hint}):\n` +
    paths.map((path) => `- ${path}`).join("\n");
}

// ---- Tamanho do chat, botão "novo chat com resumo" e aviso de chat encerrado/aguardando ----
function chatTools() {
  let box = document.getElementById("chat-tools");
  if (box) return box;
  const actions = document.querySelector(".topbar-actions");
  if (!actions) return null;
  box = document.createElement("div");
  box.id = "chat-tools";
  box.style.cssText = "display:none;align-items:center;gap:6px;";
  box.innerHTML =
    '<span id="chat-size" style="font-size:12px;color:var(--muted);white-space:nowrap"></span>' +
    '<button id="btn-new-chat-summary" class="top-btn" type="button" title="Continuar em um chat novo, com um resumo desta conversa">↪<span class="top-btn-label">Novo chat com resumo</span></button>';
  actions.insertBefore(box, actions.firstChild);
  box.querySelector("#btn-new-chat-summary").addEventListener("click", continueInNewChat);
  return box;
}

function chatBanner() {
  let banner = document.getElementById("chat-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "chat-banner";
    banner.className = "msg-notice hidden";
    banner.style.cssText = "margin:8px 16px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:center;";
    el.messages.parentNode.insertBefore(banner, el.messages);
  }
  return banner;
}

function bannerButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-sm btn-primary";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

async function refreshChatSize(chat) {
  if (!chat?.thread_id) return;
  const tools = chatTools();
  const banner = chatBanner();
  try {
    const info = await api(API.size(chat.thread_id));
    if (state.activeId !== chat.id) return;
    if (tools) tools.style.display = "flex";
    const sizeEl = document.getElementById("chat-size");
    if (sizeEl) {
      const limit = info.limit_tokens || 0;
      const pct = limit > 0 ? Math.round((100 * info.tokens) / limit) : 0;
      sizeEl.textContent = limit > 0 ? `≈${Math.round(info.tokens / 1000)}k/${Math.round(limit / 1000)}k` : `${info.turns} msgs`;
      sizeEl.style.color = pct >= 80 ? "var(--warn)" : "var(--muted)";
      sizeEl.title = limit > 0 ? `Tamanho estimado da conversa: ${pct}% do limite para trocar de chat.` : "Mensagens nesta conversa.";
    }
    banner.innerHTML = "";
    if (info.rotated_to) {
      banner.append(`Esta conversa foi encerrada. Continue em "${info.rotated_to.title}".`);
      banner.append(bannerButton("Abrir o chat novo", async () => {
        await loadChats();
        const next = state.chats.find((item) => item.id === info.rotated_to.id || item.thread_id === info.rotated_to.thread_id);
        if (next) await openChat(next.id);
      }));
      banner.classList.remove("hidden");
    } else if (info.full && info.active_tasks.length) {
      const ids = info.active_tasks.map((task) => `#${task.id}`).join(", ");
      banner.append(`Chat cheio: vai continuar em um chat novo quando as tasks ${ids} terminarem.`);
      banner.append(bannerButton("Liberar tasks presas", async () => {
        if (!confirm("Use só se o worker caiu e as tasks ficaram presas. Elas serão marcadas como falhas; se editaram arquivos, confira o diff e use Reprovar.")) return;
        try {
          await api(API.releaseTasks(chat.thread_id), { method: "POST" });
          await loadTasks(chat.thread_id);
          refreshChatSize(chat);
        } catch (err) { alert(err.message || "Não foi possível liberar as tasks."); }
      }));
      banner.classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
    }
  } catch (err) { /* sem medidor: segue sem ele */ }
}

async function continueInNewChat() {
  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat?.thread_id || state.sending) return;
  if (!confirm("Continuar esta conversa em um chat novo, com um resumo de tudo? As tasks em aberto vão junto.")) return;
  try {
    const data = await api(API.newChat(chat.thread_id), { method: "POST", body: JSON.stringify({ workspace_path: state.workspacePath }) });
    await switchToNewChat(chat, data);
  } catch (err) {
    alert(err.message || "Não foi possível criar o chat novo.");
  }
}

// Chat cheio: o backend criou um chat novo (mesmo nome com número na frente, com resumo e as tasks em aberto).
// Abre o chat novo e reenvia nele a mensagem que disparou a troca.
async function switchToNewChat(oldChat, data) {
  const target = data.new_chat || {};
  await loadChats();
  const next = state.chats.find((item) => item.id === target.id || item.thread_id === target.thread_id);
  if (!next) return false;
  const mode = state.routeModes[String(oldChat.id)];
  if (mode) { state.routeModes[String(next.id)] = mode; saveRouteModes(); }
  await openChat(next.id);
  appendNotice(`Conversa anterior cheia: você foi levado para "${next.title}", que começa com um resumo de tudo.`);
  const carry = data.carry_message;
  if (carry) setTimeout(() => sendMessage(carry), 0); // roda depois de o envio atual liberar state.sending
  return true;
}

// ---- Raciocínio ao vivo: balão "Pensando…" que se atualiza enquanto os modelos trabalham ----
function liveThoughtsText(segments, maxChars = 12000) {
  const text = (segments || []).map((seg) => {
    const lines = ["▸ " + (seg.label || "Modelo") + (seg.done ? "" : " …")];
    if (seg.thought) lines.push(seg.thought);
    if (seg.text) lines.push(seg.text);
    (seg.tools || []).forEach((line) => lines.push(line));
    if (seg.result) lines.push("← " + seg.result);
    return lines.join("\n");
  }).join("\n\n");
  return text.length > maxChars ? "…" + text.slice(-maxChars) : text;
}

function startLiveThoughts(chat, typing) {
  const body = typing && typing.querySelector(".msg-body");
  const row = typing && typing.querySelector(".typing-row");
  if (!body || !row) return { stop() {} };
  const box = document.createElement("details");
  box.className = "msg-thoughts live-thoughts";
  box.open = true;
  box.hidden = true;
  box.innerHTML = `<summary>${ICON.brain}<span class="live-title">Pensando…</span></summary><div class="msg-thoughts-body live-body" style="white-space:pre-wrap;max-height:320px;overflow:auto;font-size:13px;"></div>`;
  body.insertBefore(box, row);
  const out = box.querySelector(".live-body");
  const title = box.querySelector(".live-title");
  let seq = -1;
  let stopped = false;
  let timer = null;

  const tick = async () => {
    if (stopped) return;
    try {
      const data = await api(API.live(chat.thread_id) + "?after=" + seq);
      if (!stopped && data && data.changed !== false) {
        seq = data.seq;
        const segs = data.segments || [];
        if (segs.length) {
          const nearBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
          box.hidden = false;
          out.textContent = liveThoughtsText(segs);
          const last = segs[segs.length - 1];
          title.textContent = (last.label || "Pensando") + "…";
          if (nearBottom) out.scrollTop = out.scrollHeight;
          scrollToBottom();
        }
      }
    } catch (err) { /* sem balão ao vivo nesta rodada; a resposta final chega normalmente */ }
    if (!stopped) timer = setTimeout(tick, 800);
  };
  timer = setTimeout(tick, 400);
  return { stop() { stopped = true; clearTimeout(timer); } };
}

async function sendMessage(text) {
  if (!text.trim() || state.sending) return;
  if (state.activeId == null) {
    await createChat();
    if (state.activeId == null) return;
  }
  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat) return;

  state.sending = true;
  state.stopRequested = false;
  setSendButtonMode(true);
  state.pendingChats.add(chat.id);
  appendMessage("user", text, null, { created_at: new Date().toISOString() });
  scrollToBottom();
  const typing = appendTyping();
  const live = startLiveThoughts(chat, typing);

  try {
    const data = await api(API.send, { method: "POST", body: JSON.stringify({ thread_id: chat.thread_id, message: text, workspace_path: state.workspacePath, preset: getChatPreset() }) });
    if (state.activeId !== chat.id) return;
    typing.remove();
    if (data?.new_chat && (await switchToNewChat(chat, data))) return;
    if (data?.cancelled) {
      await refreshMessages(chat);
      appendNotice("Resposta interrompida. Você pode editar sua mensagem e enviar de novo.");
    } else if (!(await refreshMessages(chat))) {
      appendMessage("assistant", data?.content ?? data?.message ?? "", data?.name ?? data?.model, data || {});
    }
    if (data?.chat_full) appendNotice("Esta conversa está ficando longa: ela continua em um chat novo (com resumo) assim que as tarefas terminarem.");
    if (data?.title_pending) scheduleTitleRefresh(chat);
  } catch (err) {
    if (state.activeId === chat.id) {
      typing.remove();
      if (state.stopRequested) {
        await refreshMessages(chat);
        appendNotice("Resposta interrompida.");
      } else {
        appendMessage("assistant", "Erro ao contatar o servidor.");
      }
    }
  } finally {
    live.stop();
    state.sending = false;
    state.stopRequested = false;
    setSendButtonMode(false);
    state.pendingChats.delete(chat.id);
    if (state.activeId === chat.id) {
      scrollToBottom();
      if (!isMobile()) el.chatInput.focus();
      refreshChatSize(chat);
    }
  }
}

// O backend titula o chat em segundo plano depois da 1ª resposta: busca o título novo e atualiza a barra lateral.
function scheduleTitleRefresh(chat) {
  [6000, 16000].forEach((ms) => setTimeout(async () => {
    try {
      await loadChats();
      const fresh = state.chats.find((item) => item.id === chat.id);
      if (fresh && state.activeId === chat.id) el.chatTitle.textContent = fresh.title;
    } catch (err) { /* segue sem atualizar */ }
  }, ms));
}

async function sendBatch() {
  const raw = el.batchInput.value.trim();
  const tasks = raw.split(/\n\s*\n/).map(t => t.trim()).filter(Boolean);
  if (!tasks.length) return;

  if (state.activeId == null) {
    await createChat();
    if (state.activeId == null) return;
  }
  const chat = state.chats.find(c => c.id === state.activeId);
  
  el.batchStatus.textContent = "Enviando...";
  tasks.forEach(task => appendMessage("user", task));
  const currentAiCount = el.messages.querySelectorAll('.msg.assistant:not([data-typing="1"])').length;
  state.expectedAiCount[chat.id] = (state.expectedAiCount[chat.id] || currentAiCount) + tasks.length;
  appendTyping();
  scrollToBottom();
  state.pendingChats.add(chat.id);

  try {
    const data = await api(API.batch, { method: "POST", body: JSON.stringify({ thread_id: chat.thread_id, prompts: tasks, workspace_path: state.workspacePath }) });
    el.batchStatus.textContent = data?.message || "Enviado para a fila.";
    el.batchInput.value = "";
  } catch (err) {
    el.batchStatus.textContent = "Falha ao enfileirar.";
    state.pendingChats.delete(chat.id);
  }
}

function startPolling() {
  if (state.pollingInterval) clearInterval(state.pollingInterval);
  state.pollingInterval = setInterval(async () => {
    if (document.hidden) return; // Não polla se a aba estiver fechada/oculta
    if (!state.activeId || state.sending) return;
    const chat = state.chats.find(c => c.id === state.activeId);
    if (!chat || !chat.thread_id) return;

    try {
      await loadTasks(chat.thread_id);
      syncTaskTyping();
      const data = await api(API.messages(chat.thread_id));
      if (state.activeId !== chat.id) return;
      const msgs = data?.messages ?? [];
      const visibleMsgs = el.messages.querySelectorAll('.msg:not([data-typing="1"])');
      const aiCount = msgs.filter(m => m.role === "assistant").length;
      
      if (state.expectedAiCount[chat.id] && aiCount >= state.expectedAiCount[chat.id]) {
        state.pendingChats.delete(chat.id);
        state.expectedAiCount[chat.id] = 0;
      }
      if (msgs.length > visibleMsgs.length) {
        renderHistory(msgs);
        if (state.pendingChats.has(chat.id)) appendTyping();
        scrollToBottom();
      } else if (!state.pendingChats.has(chat.id)) {
        const typingEl = el.messages.querySelector('[data-typing="1"]:not([data-kind="tasks"])');
        if (typingEl) typingEl.remove();
      }
    } catch (e) {}
  }, 3000); 
}

// ============================================================
// INPUT, TAGS & AUTO-RESIZE (Restaurados!)
// ============================================================

function autoResize() {
  el.chatInput.style.height = "auto";
  el.chatInput.style.height = Math.min(el.chatInput.scrollHeight, 200) + "px";
}

// Modo de roteamento fixo: vale para TODAS as mensagens da conversa até ser solto.
const ROUTE_TAGS = { auto: "", heavy: "@heavy", enhance: "@enhance", audit: "@audit" };
const ROUTE_LABEL = { heavy: "Heavy", enhance: "Enhance", audit: "Auditoria" };
// Pedido de auditoria já escrito em português ("Audite o arquivo x"): no modo Auditoria não leva a etiqueta @audit na frente.
const AUDIT_NL_RE = /^\s*(?:por favor[,\s]+)?(?:(?:pode|poderia|consegue)\s+)?(?:audite|auditar|(?:fa[çc]a|fazer|rode|rodar|execute|executar)\s+(?:uma\s+)?auditoria)\b/i;
const ROUTE_STORE = "assistant_route_modes";

function loadRouteModes() {
  try { state.routeModes = JSON.parse(localStorage.getItem(ROUTE_STORE) || "{}") || {}; }
  catch { state.routeModes = {}; }
}

function saveRouteModes() {
  try { localStorage.setItem(ROUTE_STORE, JSON.stringify(state.routeModes)); } catch {}
}

function getRouteMode() {
  const mode = state.routeModes[String(state.activeId)];
  return mode && Object.prototype.hasOwnProperty.call(ROUTE_TAGS, mode) ? mode : "auto";
}

function setRouteMode(mode) {
  if (state.activeId == null) return;
  if (mode === "auto") delete state.routeModes[String(state.activeId)];
  else state.routeModes[String(state.activeId)] = mode;
  saveRouteModes();
  syncChips();
  if (!isMobile()) el.chatInput.focus();
}

function toggleRouteMode(mode) { setRouteMode(getRouteMode() === mode ? "auto" : mode); }

// Aplica a etiqueta do modo fixo, sem duplicar se o usuário já digitou uma e sem tocar em comandos (@generate).
function applyRouteMode(text) {
  const tag = ROUTE_TAGS[getRouteMode()];
  if (!tag || !text.trim()) return text;
  if (/^\s*@(?:zip|commit|pack|primer|generate|heavy|enhance|audit(?:oria)?)\b/i.test(text) || /(^|\s)@(?:heavy|enhance)(\s|$)/i.test(text)) return text;
  if (getRouteMode() === "audit" && AUDIT_NL_RE.test(text)) return text;
  return `${tag} ${text.replace(/^\s+/, "")}`;
}

function syncChips() {
  const mode = getRouteMode();
  [[el.btnAuto, "auto"], [el.btnHeavy, "heavy"], [el.btnEnhance, "enhance"], [el.btnAudit, "audit"]].forEach(([button, name]) => {
    if (!button) return;
    const on = mode === name;
    button.classList.toggle("active", on);
    button.setAttribute("aria-checked", String(on));
  });
  el.composer.dataset.mode = mode;
  const fixed = mode !== "auto";
  el.composerFoot.classList.toggle("fixed", fixed);
  el.composerFoot.innerHTML = fixed
    ? `Modo <b>${ROUTE_LABEL[mode]}</b> fixo nesta conversa · toque de novo para soltar`
    : "Enter envia · Shift+Enter quebra a linha";
  el.chatInput.placeholder = fixed ? `Pergunte (${ROUTE_LABEL[mode]})…` : "Pergunte alguma coisa…";
}

async function startWith(prompt, mode) {
  await createChat();
  if (state.activeId == null) return;
  setRouteMode(mode || "auto");
  el.chatInput.value = prompt || "";
  autoResize();
  el.chatInput.focus();
}

// ============================================================
// FONTES DE CONHECIMENTO (RAG): quais fontes o agente consulta neste projeto
// ============================================================
const RAG = { ok: false, own: null, linked: new Set(), sources: [], workspace: "" };

function ragProjectName() {
  return RAG.workspace ? RAG.workspace.split(/[\\/]/).filter(Boolean).pop() || RAG.workspace : "";
}

async function loadRagScope() {
  if (!el.btnSources) return;
  RAG.workspace = state.workspacePath || "";
  try {
    const data = await api(`${API.ragScope}?path=${encodeURIComponent(RAG.workspace)}`);
    RAG.ok = true;
    RAG.own = data.own || null;
    RAG.linked = new Set(data.linked_ids || []);
    RAG.sources = data.sources || [];
  } catch {
    RAG.ok = false;
    RAG.own = null;
    RAG.linked = new Set();
    RAG.sources = [];
  }
  renderSources();
}

function sourceRow(source, checked, locked, label) {
  const off = locked || !RAG.workspace;
  return `<label class="src-row${locked ? " locked" : ""}">
    <input type="checkbox" data-source="${source.id}" ${checked ? "checked" : ""} ${off ? "disabled" : ""} />
    <span class="src-name">${escapeHtml(source.name)}</span>
    <span class="src-kind">${escapeHtml(label || source.kind)}</span>
    <small class="src-meta">${source.files ?? 0} arquivos</small>
  </label>`;
}

function renderSources() {
  const visible = RAG.ok && RAG.sources.length > 0;
  el.btnSources.classList.toggle("hidden", !visible);
  if (!visible) {
    closeSourcesMenu();
    return;
  }

  el.sourcesCount.textContent = String((RAG.own ? 1 : 0) + RAG.linked.size);
  el.btnSources.classList.toggle("has-extra", RAG.linked.size > 0);

  const project = ragProjectName();
  el.sourcesNote.innerHTML = project
    ? (state.pin
      ? `📌 Fixado nesta conversa: projeto <b>${escapeHtml(project)}</b> e estas fontes. Mudar aqui atualiza o que está fixado.`
      : `Vale para o projeto <b>${escapeHtml(project)}</b>, em todas as conversas dele. Você também pode pedir uma fonte pelo nome na pergunta.`)
    : "Selecione um projeto na aba Projeto para escolher as fontes.";

  const html = [];
  if (project) {
    html.push('<div class="src-group">Do projeto</div>');
    const ownFull = RAG.own && RAG.sources.find((source) => source.id === RAG.own.id);
    html.push(
      ownFull
        ? sourceRow(ownFull, true, true, "projeto")
        : `<div class="src-row src-off"><span class="src-name">${escapeHtml(project)}</span><span class="src-kind">projeto</span><small class="src-meta">não indexado</small></div>`
    );
  }
  const others = RAG.sources.filter((source) => !RAG.own || source.id !== RAG.own.id);
  if (others.length) {
    html.push('<div class="src-group">Também consultar</div>');
    others.forEach((source) => html.push(sourceRow(source, RAG.linked.has(source.id), false)));
  }
  el.sourcesList.innerHTML = html.join("");
}

async function toggleSourceLink(id, checked) {
  if (!RAG.workspace) return;
  const previous = RAG.linked;
  const next = new Set(previous);
  if (checked) next.add(id);
  else next.delete(id);
  RAG.linked = next;
  renderSources();
  try {
    const result = await api(API.ragLinks, {
      method: "PUT",
      body: JSON.stringify({ path: RAG.workspace, source_ids: [...next] }),
    });
    RAG.linked = new Set(result.source_ids || []);
    schedulePinSave();
  } catch (error) {
    RAG.linked = previous;
    alert("Não foi possível salvar as fontes: " + error.message);
  }
  renderSources();
}

function openSourcesMenu() {
  el.sourcesMenu.classList.remove("hidden");
  el.btnSources.setAttribute("aria-expanded", "true");
  loadRagScope(); // atualiza ao abrir: novas fontes indexadas aparecem na hora
}

function closeSourcesMenu() {
  if (!el.sourcesMenu) return;
  el.sourcesMenu.classList.add("hidden");
  el.btnSources.setAttribute("aria-expanded", "false");
}

// ============================================================
// FIXAR PROJETO E FONTES NA CONVERSA (📌)
// Cada conversa pode lembrar o projeto e as fontes do RAG. O vínculo fica no servidor,
// então vale no PC e no celular: ao reabrir a conversa, o projeto e as fontes voltam sozinhos.
// ============================================================

state.pin = null; // vínculo da conversa aberta (null = não fixada)
let pinTimer = null;
let pinRestoring = false;

const pinUrl = (threadId) => `/api/pins/${encodeURIComponent(threadId)}`;

function pinThreadId() {
  const chat = state.chats.find((item) => item.id === state.activeId);
  return chat?.thread_id || null;
}

function syncPinButton() {
  const button = document.getElementById("btn-pin");
  if (button) {
    const pinned = !!state.pin;
    button.classList.toggle("hidden", state.activeId == null);
    button.classList.toggle("active", pinned);
    button.setAttribute("aria-pressed", String(pinned));
    button.title = pinned
      ? `Fixado nesta conversa: ${state.pin.workspace_path}. Toque para soltar.`
      : "Fixar o projeto e as fontes atuais nesta conversa";
  }
  try { renderSources(); } catch (error) { /* o menu de fontes ainda não existe */ }
}

// Ao abrir uma conversa fixada, traz de volta o projeto e as fontes dela.
async function applyChatPin(chat) {
  state.pin = null;
  syncPinButton();
  if (!chat?.thread_id) return;
  let pin;
  try { pin = await api(pinUrl(chat.thread_id)); } catch (error) { return; }
  if (state.activeId !== chat.id || !pin?.pinned) return; // trocou de conversa enquanto carregava
  state.pin = pin;
  pinRestoring = true;
  try {
    if (pin.workspace_path) {
      if (!state.workspaces.includes(pin.workspace_path)) state.workspaces.push(pin.workspace_path);
      if (state.workspacePath !== pin.workspace_path) {
        state.workspacePath = pin.workspace_path;
        saveWorkspaces();
        renderWorkspaces();
      }
      await loadRagScope();
      if (state.activeId !== chat.id) return;
      const wanted = [...(pin.source_ids || [])].sort((a, b) => a - b);
      const current = [...RAG.linked].sort((a, b) => a - b);
      if (RAG.ok && JSON.stringify(wanted) !== JSON.stringify(current)) {
        const result = await api(API.ragLinks, { method: "PUT", body: JSON.stringify({ path: pin.workspace_path, source_ids: wanted }) });
        RAG.linked = new Set(result?.source_ids || []);
      }
    }
  } catch (error) {
    console.warn("Não foi possível restaurar o que estava fixado:", error);
  } finally {
    pinRestoring = false;
    syncPinButton();
  }
}

async function togglePin() {
  const threadId = pinThreadId();
  if (!threadId) return;
  if (state.pin) {
    try { await api(pinUrl(threadId), { method: "DELETE" }); }
    catch (error) { alert("Não foi possível soltar: " + error.message); return; }
    state.pin = null;
    syncPinButton();
    return;
  }
  if (!state.workspacePath) { alert("Escolha um projeto na aba Projeto antes de fixar."); return; }
  try {
    state.pin = await api(pinUrl(threadId), {
      method: "PUT",
      body: JSON.stringify({ workspace_path: state.workspacePath, source_ids: [...RAG.linked] }),
    });
  } catch (error) { alert("Não foi possível fixar: " + error.message); }
  syncPinButton();
}

// Com a conversa fixada, trocar de projeto ou de fontes atualiza o que está fixado.
function schedulePinSave() {
  if (!state.pin || pinRestoring) return;
  const threadId = pinThreadId();
  if (!threadId) return;
  clearTimeout(pinTimer);
  pinTimer = setTimeout(async () => {
    if (pinThreadId() !== threadId || !state.workspacePath) return;
    try {
      state.pin = await api(pinUrl(threadId), {
        method: "PUT",
        body: JSON.stringify({ workspace_path: state.workspacePath, source_ids: [...RAG.linked] }),
      });
      syncPinButton();
    } catch (error) { console.warn("Não foi possível atualizar o que está fixado:", error); }
  }, 500);
}

document.getElementById("btn-pin")?.addEventListener("click", togglePin);

function syncWorkspaceChip() {
  if (!el.workspaceChipLabel) return;
  const path = state.workspacePath || "";
  el.workspaceChipLabel.textContent = path ? path.split(/[\\/]/).filter(Boolean).pop() || path : "Sem projeto";
  el.btnWorkspaceChip.title = path || "Nenhum diretório de trabalho selecionado";
}

// ============================================================
// LISTENERS GERAIS E INICIALIZAÇÃO
// ============================================================

el.btnNewChat.addEventListener("click", createChat);
el.btnAuto.addEventListener("click", () => setRouteMode("auto"));
el.btnHeavy.addEventListener("click", () => toggleRouteMode("heavy"));
el.btnEnhance.addEventListener("click", () => toggleRouteMode("enhance"));
if (el.btnAudit) el.btnAudit.addEventListener("click", () => toggleRouteMode("audit"));

// Restauração do Evento Input e Enter
el.chatInput.addEventListener("input", () => {
  autoResize();
  syncChips();
});

el.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (state.sending) return; // Enter não interrompe; use o botão ou Esc
    el.chatForm.requestSubmit();
  }
});

el.chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.sending) { stopGeneration(); return; }
  if (state.uploading) return;
  let text = el.chatInput.value;
  if (state.attachments.length) {
    const composed = await composeWithAttachments(text);
    if (composed === null) return; // mantém texto e anexos para tentar de novo
    text = composed;
  }
  text = applyRouteMode(text);
  el.chatInput.value = "";
  autoResize();
  syncChips();
  sendMessage(text);
});

el.btnAttach.addEventListener("click", () => el.attachInput.click());
el.attachInput.addEventListener("change", () => {
  addAttachments(Array.from(el.attachInput.files || []));
  el.attachInput.value = "";
});

document.querySelectorAll(".drawer .tab").forEach((tab) => {
  tab.addEventListener("click", () => setDrawerTab(tab.dataset.tab));
});
el.btnCloseDrawer.addEventListener("click", closeDrawer);
el.btnSidebarClose.addEventListener("click", closeSidebar);
el.scrim.addEventListener("click", () => {
  if (isMobile()) el.sidebar.classList.remove("open");
  closeDrawerIfOverlay();
  updateScrim();
});
el.taskSummary.addEventListener("click", (event) => {
  const pill = event.target.closest(".stat-pill");
  if (!pill) return;
  state.taskFilters.status = pill.dataset.status;
  renderTasks(state.currentTasks);
});
el.btnTaskFilters.addEventListener("click", () => {
  const open = !el.taskFiltersAdv.classList.toggle("hidden");
  el.btnTaskFilters.setAttribute("aria-expanded", String(open));
});
el.chatSearch.addEventListener("input", () => {
  state.chatQuery = el.chatSearch.value;
  renderChatList();
  scheduleGlobalChatSearch(state.chatQuery);
});
el.btnWorkspaceChip.addEventListener("click", () => openDrawer("project"));
el.btnSources.addEventListener("click", (event) => {
  event.stopPropagation();
  if (el.sourcesMenu.classList.contains("hidden")) openSourcesMenu();
  else closeSourcesMenu();
});
el.sourcesMenu.addEventListener("click", (event) => event.stopPropagation());
el.sourcesList.addEventListener("change", (event) => {
  const box = event.target.closest?.("[data-source]");
  if (box) toggleSourceLink(Number(box.dataset.source), box.checked);
});
document.addEventListener("click", closeSourcesMenu);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeSourcesMenu(); });
document.querySelectorAll(".suggest").forEach((card) => {
  card.addEventListener("click", () => startWith(card.dataset.prompt, card.dataset.mode));
});
el.btnSendBatch.addEventListener("click", sendBatch);
el.sidebarToggle.addEventListener("click", toggleSidebar);

el.btnToggleTasks.addEventListener("click", async () => {
  if (el.app.classList.contains("drawer-open")) {
    closeDrawer();
    return;
  }
  openDrawer("tasks");
  const chat = state.chats.find((c) => c.id === state.activeId);
  if (chat?.thread_id) await loadTasks(chat.thread_id);
});
el.btnExecuteTasks.addEventListener("click", executePendingTasks);
el.taskFilterSearch.addEventListener("input", onTaskFilterChange);
[el.taskFilterPriority, el.taskFilterMode].forEach((select) =>
  select.addEventListener("change", onTaskFilterChange)
);
el.btnClearTaskFilters.addEventListener("click", clearTaskFilters);
el.taskSelectAll.addEventListener("change", () => toggleSelectAllVisible(el.taskSelectAll.checked));
el.btnExecuteSelected.addEventListener("click", executeSelectedTasks);
el.btnDeleteSelected.addEventListener("click", deleteSelectedTasks);

// Marcar/desmarcar um card sem redesenhar a lista (preserva detalhes abertos).
document.addEventListener("change", (event) => {
  const box = event.target?.closest?.(".task-select");
  if (!box) return;
  const taskId = parseInt(box.getAttribute("data-task-id"));
  if (!taskId) return;
  if (box.checked) state.selectedTaskIds.add(taskId);
  else state.selectedTaskIds.delete(taskId);
  box.closest(".task-card")?.classList.toggle("task-card-selected", box.checked);
  updateTaskToolbar(state.currentTasks, applyTaskFilters(state.currentTasks, state.taskFilters));
});
el.btnAddWorkspace.addEventListener("click", addWorkspace);
if (el.btnBrowseWorkspace) {
  el.btnBrowseWorkspace.addEventListener("click", () => toggleWorkspaceBrowser());
  el.wbClose.addEventListener("click", () => toggleWorkspaceBrowser(false));
  el.wbUse.addEventListener("click", useBrowsedWorkspace);
  el.wbList.addEventListener("click", (event) => {
    const item = event.target.closest("[data-path]");
    if (item) loadWorkspaceBrowser(item.dataset.path);
  });
}
el.workspacePath.addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); addWorkspace(); }
});

// Delegação de Eventos dos Botões do Modal
if (el.btnAddTask) el.btnAddTask.addEventListener("click", () => openTaskModal());
if (el.btnCancelModal) el.btnCancelModal.addEventListener("click", () => el.taskModal.close());

if (el.taskForm) {
  el.taskForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    const id = el.inputId.value;
    const title = el.inputTitle.value.trim();
    const description = el.inputDesc.value.trim();
    const filesStr = el.inputFiles.value.trim();
    const files = filesStr ? filesStr.split(",").map(f => f.trim()).filter(Boolean) : [];
    
    const code_snippet = el.inputSnippet.value.trim() || null;
    const payload = { title, description, files, code_snippet, priority: "medium", status: "pending" };
    
    const chat = state.chats.find(c => c.id === state.activeId);
    if (!chat || !chat.thread_id) return;

    try {
      if (id) {
        await api(API.updateTask(id), { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await api(API.createTask(chat.thread_id), { method: "POST", body: JSON.stringify(payload) });
      }
      el.taskModal.close();
      loadTasks(chat.thread_id);
    } catch (error) {
      alert("Erro ao salvar tarefa: " + error.message);
    }
  });
}

// Planejador local: o modelo indica linhas e texto novo, o sistema monta os passos (old exato) e valida por dry-run.
async function planTaskAction(taskId, button) {
  const task = state.currentTasks.find((t) => t.id === taskId);
  if (!task) return;
  if (!state.workspacePath) {
    alert("Escolha um projeto na aba Projeto antes de planejar.");
    return;
  }
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Planejando…";
  try {
    const result = await api(API.handoffPlan, {
      method: "POST",
      body: JSON.stringify({
        path: state.workspacePath,
        task: {
          title: task.title,
          description: task.description,
          reason: task.reason || "",
          files: task.files || [],
          priority: task.priority || "medium",
          steps: task.steps || [],
          verify: task.verify || [],
        },
        task_id: task.id,
        save: true,
      }),
    });
    if (result.ok && result.saved) {
      alert(`Plano pronto (${result.repaired && result.repaired.length ? "âncoras reparadas por código" : result.attempts + " tentativa(s)"}): ${result.task.steps.length} passo(s) validados no dry-run. A tarefa agora é determinística; execute normalmente.`);
    } else if (result.ok) {
      alert("O plano passou no dry-run, mas não foi salvo (a tarefa mudou de estado). Atualize a lista e tente de novo.");
    } else {
      const reason = String(result.error || result.report || "O planejador não conseguiu montar um plano.");
      alert(`Não foi possível planejar (${result.attempts} tentativa(s)):\n\n${reason.slice(0, 1200)}`);
    }
    await loadTasks();
  } catch (error) {
    alert("Erro ao planejar: " + error.message);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

// Delegar cliques de edição e exclusão dentro da lista de tasks
document.addEventListener('click', (event) => {
  const btnEdit = event.target.closest('.btn-edit-task');
  if (btnEdit) {
    const taskId = parseInt(btnEdit.getAttribute('data-task-id'));
    const task = state.currentTasks.find(t => t.id === taskId);
    if (task) openTaskModal(task);
    return;
  }
  
  const btnPlan = event.target.closest('.btn-plan-task');
  if (btnPlan) {
    const taskId = parseInt(btnPlan.getAttribute('data-task-id'));
    if (taskId) planTaskAction(taskId, btnPlan);
    return;
  }

  const btnRetry = event.target.closest('.btn-retry-task');
  if (btnRetry) {
    const taskId = parseInt(btnRetry.getAttribute('data-task-id'));
    if (taskId) retryTaskAction(taskId);
    return;
  }

  const btnDiff = event.target.closest('.btn-diff-task');
  if (btnDiff) {
    toggleTaskDiff(parseInt(btnDiff.getAttribute('data-task-id')), btnDiff);
    return;
  }

  const btnApprove = event.target.closest('.btn-approve-task');
  if (btnApprove) {
    approveTask(parseInt(btnApprove.getAttribute('data-task-id')));
    return;
  }

  const btnReject = event.target.closest('.btn-reject-task');
  if (btnReject) {
    rejectTask(parseInt(btnReject.getAttribute('data-task-id')));
    return;
  }

  const btnDelete = event.target.closest('.btn-delete-task');
  if (btnDelete) {
    const taskId = parseInt(btnDelete.getAttribute('data-task-id'));
    if (taskId) deleteTaskAction(taskId);
    return;
  }
});

// Commit automático (toggle na topbar)
const AUTOCOMMIT_KEY = "assistant_autocommit_enabled";
state.autocommit = false;

function renderAutocommitButton() {
  const btn = document.getElementById("btn-autocommit");
  const lbl = document.getElementById("autocommit-label");
  if (!btn) return;
  const on = Boolean(state.autocommit);
  btn.classList.toggle("active", on);
  btn.setAttribute("aria-pressed", String(on));
  btn.title = on ? "Commit automático LIGADO (clique para desativar)" : "Commit automático DESLIGADO (clique para ativar)";
  if (lbl) lbl.textContent = on ? "Auto-commit: On" : "Auto-commit: Off";
}

async function initAutocommit() {
  try {
    const res = await api(API.autocommit);
    state.autocommit = Boolean(res?.enabled);
  } catch (err) {
    console.warn("Falha ao consultar autocommit:", err);
  }
  renderAutocommitButton();
}

async function toggleAutocommit() {
  const next = !state.autocommit;
  try {
    const res = await api(API.autocommit, { method: "PUT", body: JSON.stringify({ enabled: next }) });
    state.autocommit = Boolean(res?.enabled);
    try { localStorage.setItem(AUTOCOMMIT_KEY, state.autocommit ? "1" : "0"); } catch {}
  } catch (err) {
    alert("Não foi possível alterar o commit automático: " + err.message);
  }
  renderAutocommitButton();
}

document.getElementById("btn-autocommit")?.addEventListener("click", toggleAutocommit);
initAutocommit();

// Iniciar app
el.btnTheme.addEventListener("click", toggleTheme);
applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
setSendButtonMode(false);
loadChats();
loadWorkspaces();
autoResize();
loadRouteModes();
if (!isMobile() && localStorage.getItem(SB_KEY) === "1") el.app.classList.add("sb-collapsed");
el.sidebarToggle.setAttribute("aria-expanded", String(sidebarIsOpen()));
setDrawerTab("tasks");
syncChips();
syncWorkspaceChip();
startPolling();
// ============================================================
// ANEXOS DAS TAREFAS + PROMPT PARA GERAR MICROTASKS
// ============================================================

const TASKS_PROMPT_TEMPLATE = "Você vai gerar MICROTASKS em JSON para o meu assistente de IA local. Ele possui dois modos de execução: DETERMINÍSTICO (padrão) e DINÂMICO (via LLM).\n\nREGRAS DE OURO PARA MODO DETERMINÍSTICO (Edições e Operações de Arquivo)\n- Na maioria das vezes, ele executa as tarefas de forma determinística: aplica exatamente o que você escrever e roda as verificações. Ele não interpreta nem corrige. Cada passo precisa ter o texto/código FINAL e EXATO.\n- Para alterar um arquivo existente (replace_text), preciso que você tenha o conteúdo atual dele. Se eu não colei, PEÇA o trecho em vez de adivinhar. O campo \"old\" tem que ser copiado EXATAMENTE (espaços, indentação, aspas).\n- Caminhos sempre RELATIVOS à raiz do projeto, com \"/\". Nunca mexa em .git, .env, node_modules, venv ou __pycache__. Para remover arquivos obsoletos use delete_file (com rollback automático).\n\nREGRAS PARA MODO DINÂMICO / LLM (Documentação, Refatoração, Análise)\n- O assistente TEM capacidade de leitura, interpretação e geração de código/texto por conta própria.\n- Se a tarefa exigir análise de arquivos que acabaram de ser modificados, geração de documentação, ou refatoração complexa onde um \"replace_text\" determinístico seria inviável, DEIXE O ARRAY \"steps\" VAZIO: \"steps\": [].\n- Quando \"steps\" estiver vazio, o assistente usará o texto que você colocar no campo \"description\" como um prompt para executar a tarefa usando sua própria inteligência (LLM). Descreva EXATAMENTE o que ele deve ler e o que deve gerar.\n- DOCUMENTAÇÃO QUE VAI PARA OUTRA PESSOA: prefira o modo determinístico com write_markdown e o texto FINAL escrito por você a partir do código real que eu colei. Se usar o modo dinâmico, liste em \"files\" TODOS os arquivos-fonte e inclua em \"verify\" a checagem literals_grounded.\n- O modo dinâmico monta o contexto sozinho (git diff, arquivos, constantes referenciadas) e confere por código se os valores citados existem nas fontes.\n\nFORMATO DO JSON\n- Responda SOMENTE com um array JSON válido (sem comentários e sem texto fora do JSON). Entregue-o FORMATADO e legível: indentado com 2 espaços, uma propriedade por linha e um objeto por tarefa, dentro de UM único bloco de código ```json (nunca em uma linha só, sem prosa antes ou depois do bloco).\n- Quebras de linha dentro do JSON são \"\\n\" e aspas internas são \\\".\n- Formato de cada objeto no array:\n{\n  \"title\": \"título curto\",\n  \"description\": \"o que a tarefa faz (se for dinâmica, seja extremamente detalhista aqui)\",\n  \"reason\": \"por que fazer\",\n  \"files\": [\"arquivos envolvidos (inclua os que serão criados/copiados/lidos)\"],\n  \"priority\": \"low | medium | high\",\n  \"steps\": [ ...operações (ou vazio [] para tarefas dinâmicas)... ],\n  \"verify\": [ ...checagens... ]\n}\n\nOPERAÇÕES DE \"steps\" (campo \"op\" - USE APENAS EM MODO DETERMINÍSTICO)\n- create_file: { \"op\": \"create_file\", \"path\": \"...\", \"content\": \"conteúdo COMPLETO\" }\n- replace_text: { \"op\": \"replace_text\", \"path\": \"...\", \"old\": \"trecho exato atual\", \"new\": \"trecho novo\", \"occurrences\": \"one\" | \"all\" }\n- append: { \"op\": \"append\", \"path\": \"...\", \"content\": \"texto adicionado ao final\" }\n- write_markdown: { \"op\": \"write_markdown\", \"path\": \"x.md\", \"content\": \"...\", \"overwrite\": false }\n- create_pdf: { \"op\": \"create_pdf\", \"path\": \"x.pdf\", \"title\": \"...\", \"content\": \"markdown\", \"overwrite\": false }\n- copy_upload: { \"op\": \"copy_upload\", \"path\": \"public/favicon.png\", \"source\": \"favicon.png\", \"overwrite\": false }\n- extract_zip: { \"op\": \"extract_zip\", \"path\": \"pasta/destino\", \"source\": \"codigo.zip\", \"on_conflict\": \"skip\" | \"overwrite\", \"strip_top_folder\": true }\n- move_file: { \"op\": \"move_file\", \"source\": \"caminho/antigo.py\", \"destination\": \"caminho/novo.py\", \"overwrite\": false }\n- delete_file: { \"op\": \"delete_file\", \"path\": \"caminho/obsoleto.py\" } (remove arquivo com rollback automático se a task falhar)\n\nCHECAGENS DE \"verify\" (campo \"type\")\n- file_exists: { \"type\": \"file_exists\", \"path\": \"...\" }\n- file_not_exists: { \"type\": \"file_not_exists\", \"path\": \"...\" } (confirma que arquivo movido/apagado não existe mais)\n- ts_check: { \"type\": \"ts_check\", \"path\": \"dashboard/app/page.tsx\" } (roda tsc --noEmit no projeto TypeScript/Next.js)\n- contains: { \"type\": \"contains\", \"path\": \"...\", \"text\": \"trecho que deve existir\" }\n- not_contains: { \"type\": \"not_contains\", \"path\": \"...\", \"text\": \"trecho que NÃO pode existir\" }\n- python_syntax: { \"type\": \"python_syntax\", \"path\": \"arquivo.py\" }\n- pytest: { \"type\": \"pytest\", \"path\": \"tests/test_x.py\" } (roda o arquivo de teste; use quando a task criar ou alterar testes)\n- literals_grounded: { \"type\": \"literals_grounded\", \"path\": \"doc.md\", \"sources\": [\"app/views.py\"], \"allow\": [] } (confere por código se valores entre aspas, headers e códigos HTTP do documento existem nas fontes)\n\nARQUIVOS ANEXADOS DISPONÍVEIS AGORA (use o nome exato em \"source\"):\n{{ANEXOS}}\n\nEXEMPLOS\n\nTarefa Determinística (Edição exata):\n[\n  {\n    \"title\": \"Aumentar fonte do título\",\n    \"description\": \"Aumenta a variável --title-size em style.css.\",\n    \"reason\": \"O título está pequeno em telas grandes.\",\n    \"files\": [\"app/style.css\"],\n    \"priority\": \"medium\",\n    \"steps\": [\n      { \"op\": \"replace_text\", \"path\": \"app/style.css\", \"old\": \"--title-size: 22px;\", \"new\": \"--title-size: 28px;\", \"occurrences\": \"one\" }\n    ],\n    \"verify\": [\n      { \"type\": \"contains\", \"path\": \"app/style.css\", \"text\": \"--title-size: 28px;\" }\n    ]\n  }\n]\n\nTarefa Dinâmica (Análise/Geração usando IA do assistente):\n[\n  {\n    \"title\": \"Documentar API\",\n    \"description\": \"Leia o arquivo app/views.py e crie um arquivo README.md detalhando os endpoints encontrados, métodos HTTP, payloads e retornos.\",\n    \"reason\": \"Facilitar o consumo da API pelo frontend.\",\n    \"files\": [\"app/views.py\", \"README.md\"],\n    \"priority\": \"medium\",\n    \"steps\": [],\n    \"verify\": [\n      { \"type\": \"file_exists\", \"path\": \"README.md\" }\n    ]\n  }\n]\n\nMINHA SOLICITAÇÃO:\n(descreva aqui o que você quer que seja feito no projeto)\n";

const TASK_ATTACH_EXTENSIONS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".zip", ".md", ".txt", ".py", ".json", ".csv", ".pdf", ".docx"];
state.taskUploads = [];

function activeChatOrNull() {
  return state.chats.find((c) => c.id === state.activeId) || null;
}

function renderTaskUploads() {
  const box = document.getElementById("task-uploads");
  if (!box) return;
  box.innerHTML = "";
  if (!state.taskUploads.length) {
    box.innerHTML = '<span class="task-uploads-empty">Nenhum anexo nesta conversa. Nos steps, use o NOME do arquivo em "source".</span>';
    return;
  }
  state.taskUploads.forEach((file) => {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    chip.innerHTML = `<span class="attachment-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span><span class="attachment-size">${formatBytes(file.size)}</span>`;
    box.appendChild(chip);
  });
}

async function refreshTaskUploads() {
  const chat = activeChatOrNull();
  state.taskUploads = [];
  if (chat) {
    try {
      const res = await fetch(`${API.upload(chat.thread_id)}?workspace_path=${encodeURIComponent(state.workspacePath || "")}`);
      if (res.ok) state.taskUploads = await res.json();
    } catch (err) {
      console.error("Falha ao listar anexos:", err);
    }
  }
  renderTaskUploads();
}

async function uploadTaskFiles(fileList) {
  const chat = activeChatOrNull();
  if (!chat) { alert("Nenhuma conversa ativa encontrada."); return; }
  const errors = [];
  for (const file of fileList) {
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    const limit = ext === ".zip" ? 50 * 1024 * 1024 : ATTACH_MAX_BYTES;
    if (!TASK_ATTACH_EXTENSIONS.includes(ext)) { errors.push(`${file.name}: extensão não permitida`); continue; }
    if (file.size > limit) { errors.push(`${file.name}: maior que ${formatBytes(limit)}`); continue; }
    const form = new FormData();
    form.append("workspace_path", state.workspacePath);
    form.append("file", file);
    try {
      const res = await fetch(API.upload(chat.thread_id), { method: "POST", body: form });
      if (!res.ok) {
        let detail = "";
        try { detail = (await res.json())?.detail || ""; } catch {}
        errors.push(`${file.name}: ${detail || "HTTP " + res.status}`);
      }
    } catch (err) {
      errors.push(`${file.name}: ${err.message}`);
    }
  }
  await refreshTaskUploads();
  if (errors.length) alert("Alguns arquivos não foram enviados:\n" + errors.join("\n"));
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch {}
    area.remove();
    return ok;
  }
}

document.getElementById("btn-task-attach").addEventListener("click", () => {
  document.getElementById("task-attach-input").click();
});

document.getElementById("task-attach-input").addEventListener("change", async (event) => {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (files.length) await uploadTaskFiles(files);
});

document.getElementById("btn-copy-prompt").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  await refreshTaskUploads();
  const names = state.taskUploads.length
    ? state.taskUploads.map((f) => `- ${f.name}`).join("\n")
    : "(nenhum anexo enviado)";
  const ok = await copyText(TASKS_PROMPT_TEMPLATE.replace("{{ANEXOS}}", () => names));
  const original = "Copiar prompt para IA";
  button.textContent = ok ? "Prompt copiado!" : "Não foi possível copiar";
  setTimeout(() => { button.textContent = original; }, 2000);
});

// ============================================================
// LÓGICA DO MODAL DE IMPORTAÇÃO DE TAREFAS
// ============================================================

el.btnImportTasks.addEventListener('click', () => {
  // Limpa o textarea antes de abrir o modal
  el.inputImportJson.value = '';
  updateImportPreview();
  // Abre o modal
  el.importTasksModal.showModal();
  refreshTaskUploads();
});

async function dryRunImportedTasks(tasks, threadId) {
  // Valida as tasks recém-importadas numa cópia temporária (executor real) e avisa o que vai falhar.
  if (!state.workspacePath) return;
  const runnable = (tasks || []).filter((t) => Array.isArray(t.steps) && t.steps.length);
  if (!runnable.length) return;
  try {
    const result = await api(API.handoffDryrun, {
      method: "POST",
      body: JSON.stringify({ path: state.workspacePath, tasks: runnable, thread_id: threadId }),
    });
    if (!result.ok) {
      alert(`Dry-run das tasks importadas: ${result.summary.failed} com falha e ${result.summary.blocked} bloqueada(s).\n\n${String(result.report || "").slice(0, 1500)}`);
    }
  } catch (error) {
    console.warn("Dry-run após importar falhou:", error);
  }
}

el.btnCancelImport.addEventListener('click', () => {
  // Fecha o modal
  el.importTasksModal.close();
});

function extractJsonText(raw) {
  // Aceita JSON colado dentro de bloco ```json e com texto antes/depois: pega do primeiro [ ou { ao último ] ou }.
  const text = String(raw || "").trim();
  // JSON puro (como no arquivo .json) nunca passa por heurística: o conteúdo das tasks tem ``` dentro das strings
  try { JSON.parse(text); return text; } catch { /* segue para a extração tolerante */ }
  // só trata como bloco de código se o texto COMEÇAR com a cerca (``` no meio de uma string não conta)
  const fenced = text.match(/^```(?:json)?\s*([\s\S]*?)```\s*$/i);
  const body = (fenced ? fenced[1] : text).trim();
  const start = body.search(/[\[{]/);
  const end = Math.max(body.lastIndexOf("]"), body.lastIndexOf("}"));
  return start >= 0 && end > start ? body.slice(start, end + 1) : body;
}

// ---- Importação tolerante: arquivo .json, correção automática, erro com linha/coluna, prévia e importação parcial ----
function repairJsonText(text) {
  let out = String(text).replace(/^﻿/, "").replace(/[​-‍⁠]/g, "");
  // aspas curvas usadas como delimitadores (depois de [ { , : ou antes de : , ] })
  out = out.replace(/([\[{,:]\s*)[“”]/g, '$1"').replace(/[“”](\s*[:,\]}])/g, '"$1');
  // quebras de linha/tab reais dentro de strings viram \n e \t
  let res = "";
  let inString = false;
  let escaped = false;
  for (const ch of out) {
    if (!inString) {
      if (ch === '"') inString = true;
      res += ch;
      continue;
    }
    if (escaped) { escaped = false; res += ch; continue; }
    if (ch === "\\") { escaped = true; res += ch; continue; }
    if (ch === '"') { inString = false; res += ch; continue; }
    if (ch === "\n") { res += "\\n"; continue; }
    if (ch === "\r") continue;
    if (ch === "\t") { res += "\\t"; continue; }
    res += ch;
  }
  // vírgula sobrando antes de ] ou }
  return res.replace(/,(\s*[\]}])/g, "$1");
}

function describeJsonError(text, error) {
  const msg = String((error && error.message) || error);
  let pos = null;
  const byPos = msg.match(/position (\d+)/i);
  const byLine = msg.match(/line (\d+) column (\d+)/i);
  if (byPos) pos = Number(byPos[1]);
  else if (byLine) {
    const lines = text.split("\n");
    pos = lines.slice(0, Number(byLine[1]) - 1).reduce((acc, l) => acc + l.length + 1, 0) + Number(byLine[2]) - 1;
  }
  if (pos == null || pos > text.length) return "JSON inválido: " + msg;
  const before = text.slice(0, pos);
  const line = before.split("\n").length;
  const col = pos - before.lastIndexOf("\n");
  const snippet = (text.slice(Math.max(0, pos - 40), pos) + "⟦aqui⟧" + text.slice(pos, pos + 40)).replace(/\n/g, " ");
  return `JSON inválido na linha ${line}, coluna ${col}: ${msg}\n…${snippet}…`;
}

function parseImportJson(raw) {
  const text = extractJsonText(raw);
  let data;
  let repaired = false;
  try {
    data = JSON.parse(text);
  } catch (first) {
    try {
      data = JSON.parse(repairJsonText(text));
      repaired = true;
    } catch (second) {
      throw new Error(describeJsonError(text, first));
    }
  }
  if (data && !Array.isArray(data) && Array.isArray(data.tasks)) data = data.tasks;
  const tasks = (Array.isArray(data) ? data : [data]).filter((t) => t && typeof t === "object" && !Array.isArray(t));
  if (!tasks.length) throw new Error("O JSON não tem nenhuma tarefa (objetos com title, steps, verify...).");
  return { tasks, repaired };
}

function describeApiError(item, taskNumber) {
  const loc = (item.loc || []).filter((x) => x !== "body");
  const out = [];
  let i = 0;
  if (typeof loc[0] === "number") { out.push(`task ${taskNumber != null ? taskNumber : loc[0] + 1}`); i = 1; }
  while (i < loc.length) {
    const part = loc[i];
    if ((part === "steps" || part === "verify") && typeof loc[i + 1] === "number") {
      let label = `${part === "steps" ? "passo" : "verificação"} ${loc[i + 1] + 1}`;
      i += 2;
      if (typeof loc[i] === "string" && i < loc.length - 1) { label += ` (${loc[i]})`; i += 1; }
      out.push(label);
      continue;
    }
    out.push(String(part));
    i += 1;
  }
  return `${out.join(", ")}: ${item.msg}`;
}

function formatApiError(body, taskNumber) {
  const detail = body && body.detail;
  if (Array.isArray(detail)) return detail.slice(0, 5).map((d) => "• " + describeApiError(d, taskNumber)).join("\n");
  return typeof detail === "string" ? detail : "";
}

function updateImportPreview() {
  const box = document.getElementById("import-preview");
  if (!box) return;
  const raw = el.inputImportJson.value.trim();
  if (!raw) { box.textContent = ""; return; }
  try {
    const { tasks, repaired } = parseImportJson(raw);
    box.style.color = "var(--ok)";
    const list = tasks.map((t, i) => `${i + 1}. ${t.title || "sem título"} [${Array.isArray(t.steps) && t.steps.length ? t.steps.length + " passo(s)" : "livre/IA"}]`);
    box.textContent = `✓ ${tasks.length} tarefa(s)${repaired ? " (JSON corrigido automaticamente)" : ""}\n` + list.join("\n");
  } catch (error) {
    box.style.color = "var(--danger)";
    box.textContent = "✗ " + error.message;
  }
}

(function setupImportHelpers() {
  const area = el.inputImportJson;
  if (!area) return;
  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px;";
  const pick = document.createElement("button");
  pick.type = "button";
  pick.className = "btn btn-ghost btn-sm";
  pick.textContent = "Escolher arquivo .json";
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".json,.txt,application/json,text/plain";
  input.hidden = true;
  const load = async (file) => {
    if (!file) return;
    area.value = await file.text();
    updateImportPreview();
  };
  pick.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => { await load(input.files[0]); input.value = ""; });
  bar.append(pick, input);
  area.parentNode.insertBefore(bar, area);
  const preview = document.createElement("div");
  preview.id = "import-preview";
  preview.style.cssText = "margin-top:6px;font-size:12.5px;white-space:pre-wrap;max-height:140px;overflow:auto;";
  area.insertAdjacentElement("afterend", preview);
  area.addEventListener("input", updateImportPreview);
  area.addEventListener("dragover", (event) => event.preventDefault());
  area.addEventListener("drop", async (event) => {
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (!file) return;
    event.preventDefault();
    await load(file);
  });
})();

el.importTasksForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  const chat = state.chats.find(c => c.id === state.activeId);
  if (!chat) {
    alert('Nenhuma conversa ativa encontrada.');
    return;
  }

  let parsed;
  try {
    parsed = parseImportJson(el.inputImportJson.value);
  } catch (error) {
    alert(error.message);
    return;
  }
  const tasks = parsed.tasks;

  const post = async (list) => {
    const response = await fetch(API.createTasksBatch(chat.thread_id), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(list)
    });
    let body = null;
    try { body = await response.json(); } catch {}
    return { ok: response.ok, body };
  };

  try {
    let imported = tasks;
    const failures = [];
    const all = await post(tasks);
    if (!all.ok) {
      if (tasks.length < 2) {
        alert('Erro ao importar tarefas.\n\n' + formatApiError(all.body, 1));
        return;
      }
      // o lote foi recusado: importa as boas uma a uma e relata só as que têm problema
      imported = [];
      for (let i = 0; i < tasks.length; i++) {
        const one = await post([tasks[i]]);
        if (one.ok) imported.push(tasks[i]);
        else failures.push(`#${i + 1} "${tasks[i].title || 'sem título'}":\n${formatApiError(one.body, i + 1) || 'erro desconhecido'}`);
      }
      if (!imported.length) {
        alert('Nenhuma tarefa foi importada.\n\n' + failures.join('\n\n'));
        return;
      }
    }
    loadTasks(chat.thread_id);
    el.importTasksModal.close();
    if (failures.length) {
      alert(`${imported.length} tarefa(s) importada(s) e ${failures.length} com erro (corrija e importe só essas):\n\n` + failures.join('\n\n'));
    }
    dryRunImportedTasks(imported, chat.thread_id);
  } catch (error) {
    alert('Não foi possível enviar as tarefas ao servidor.');
    console.error('Erro na importação:', error);
  }
});

// ============================================================
// ARTEFATOS DA CONVERSA E MODAL DE VISUALIZAÇÃO (.txt / .md)
// ============================================================

state.artifacts = [];
state.activeArtifact = null;

function extractPackFilename(href) {
  const match = String(href || "").match(/\/api\/handoff\/packs\/([\w.-]+\.(?:txt|md|pdf))(?:$|[?#])/i);
  return match ? match[1] : null;
}

function enhanceArtifactLinks(container) {
  if (!container) return;
  container.querySelectorAll('a[href*="/api/handoff/packs/"]').forEach((anchor) => {
    const filename = extractPackFilename(anchor.getAttribute("href"));
    if (!filename) return;
    const kind = filename.split(".").pop().toUpperCase();
    const card = document.createElement("button");
    card.type = "button";
    card.className = "artifact-card";
    card.dataset.artifactName = filename;
    card.title = "Clique para visualizar o conteúdo completo, copiar ou baixar";
    card.innerHTML = `
      <span class="artifact-card-ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg></span>
      <span class="artifact-card-info">
        <b class="artifact-card-name">${escapeHtml(filename)}</b>
        <small>Clique para abrir, copiar ou baixar</small>
      </span>
      <span class="artifact-kind-badge ${kind.toLowerCase()}">${escapeHtml(kind)}</span>
    `;
    anchor.replaceWith(card);
  });
}

function collectArtifactsFromDom() {
  const found = [];
  el.messages.querySelectorAll("[data-artifact-name]").forEach((node) => {
    const filename = node.dataset.artifactName;
    if (filename && !found.some((item) => item.filename === filename)) {
      found.push({
        filename,
        kind: filename.split(".").pop().toLowerCase(),
        title: filename,
        size_bytes: 0,
        exists: true,
        url: API.packDownload(filename),
      });
    }
  });
  return found;
}

async function loadArtifacts(threadId = null) {
  const chat = state.chats.find((c) => c.id === state.activeId);
  const thread = threadId ?? chat?.thread_id;
  if (!thread) {
    state.artifacts = [];
    renderArtifacts([]);
    return;
  }
  let remote = [];
  try {
    const data = await api(API.threadArtifacts(thread));
    remote = Array.isArray(data?.artifacts) ? data.artifacts : [];
  } catch {}
  const fromMessages = collectArtifactsFromDom();
  const merged = [...remote];
  for (const item of fromMessages) {
    if (!merged.some((r) => r.filename === item.filename)) merged.push(item);
  }
  state.artifacts = merged;
  renderArtifacts(merged);
}

function renderArtifacts(items) {
  const list = document.getElementById("artifacts-list");
  const badge = document.getElementById("artifacts-badge");
  const count = items.length;
  if (badge) {
    badge.textContent = String(count);
    badge.classList.toggle("hidden", count === 0);
  }
  if (!list) return;
  if (!count) {
    list.innerHTML = '<div class="tasks-empty">Nenhum artefato (.txt, .md ou .pdf) gerado nesta conversa ainda.</div>';
    return;
  }
  list.innerHTML = items.map((item) => {
    const kind = String(item.kind || "txt").toUpperCase();
    const size = item.size_bytes ? formatBytes(item.size_bytes) : "";
    const expired = item.exists === false;
    return `
      <article class="artifact-item" data-artifact-name="${escapeHtml(item.filename)}">
        <div class="artifact-item-top">
          <span class="artifact-kind-badge ${escapeHtml(kind.toLowerCase())}">${escapeHtml(kind)}</span>
          <b class="artifact-item-name" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</b>
          ${size ? `<small class="artifact-item-size">${escapeHtml(size)}</small>` : ""}
        </div>
        <div class="artifact-item-actions">
          <button type="button" class="btn btn-primary btn-sm" data-art-act="open" data-artifact-name="${escapeHtml(item.filename)}" ${expired ? "disabled" : ""}>${expired ? "Expirado" : "Abrir"}</button>
          ${kind === "PDF" ? "" : `<button type="button" class="btn btn-ghost btn-sm" data-art-act="copy" data-artifact-name="${escapeHtml(item.filename)}" ${expired ? "disabled" : ""}>Copiar</button>`}
          <a class="btn btn-ghost btn-sm" href="${escapeHtml(API.packDownload(item.filename))}" download="${escapeHtml(item.filename)}">Baixar</a>
        </div>
      </article>
    `;
  }).join("");
}

async function openArtifactModal(filename) {
  const modal = document.getElementById("artifact-modal");
  const titleEl = document.getElementById("artifact-modal-title");
  const badgeEl = document.getElementById("artifact-modal-badge");
  const metaEl = document.getElementById("artifact-modal-meta");
  const preEl = document.getElementById("artifact-modal-pre");
  const codeEl = document.getElementById("artifact-modal-code");
  const pdfEl = document.getElementById("artifact-modal-pdf");
  const wrapBtn = document.getElementById("btn-artifact-wrap");
  const copyBtn = document.getElementById("btn-artifact-copy");
  const dlEl = document.getElementById("btn-artifact-download");
  if (!modal || !codeEl) return;

  const kind = filename.split(".").pop().toUpperCase();
  const isPdf = kind === "PDF";
  state.activeArtifact = { filename, content: "", isPdf };
  titleEl.textContent = filename;
  badgeEl.textContent = kind;
  badgeEl.className = `artifact-kind-badge ${kind.toLowerCase()}`;
  metaEl.textContent = "Carregando conteúdo…";
  codeEl.textContent = "";
  preEl?.classList.toggle("hidden", isPdf);
  wrapBtn?.classList.toggle("hidden", isPdf);
  copyBtn?.classList.toggle("hidden", isPdf);
  if (pdfEl) {
    pdfEl.classList.toggle("hidden", !isPdf);
    pdfEl.src = isPdf ? `${API.packDownload(filename)}?inline=1` : "about:blank";
  }
  if (dlEl) {
    dlEl.href = API.packDownload(filename);
    dlEl.setAttribute("download", filename);
  }
  if (!modal.open) modal.showModal();

  try {
    const data = await api(API.packContent(filename));
    if (isPdf) {
      metaEl.textContent = `Documento PDF · ${formatBytes(data?.size_bytes ?? 0)}`;
      return;
    }
    const content = String(data?.content ?? "");
    state.activeArtifact = { filename, content, isPdf: false };
    metaEl.textContent = `${data?.lines ?? 0} linha(s) · ${formatBytes(data?.size_bytes ?? content.length)}`;
    codeEl.textContent = content;
  } catch (err) {
    metaEl.textContent = "Erro ao carregar";
    if (isPdf && pdfEl) pdfEl.classList.add("hidden");
    preEl?.classList.remove("hidden");
    codeEl.textContent = err.message || "Não foi possível ler o arquivo.";
  }
}

async function copyArtifactByName(filename, button = null) {
  try {
    let content = state.activeArtifact?.filename === filename ? state.activeArtifact.content : null;
    if (content == null) {
      const data = await api(API.packContent(filename));
      content = String(data?.content ?? "");
    }
    const ok = await copyText(content);
    if (button) {
      const prev = button.textContent;
      button.textContent = ok ? "Copiado ✓" : "Falhou";
      setTimeout(() => { button.textContent = prev; }, 1600);
    }
  } catch (err) {
    alert("Não foi possível copiar o conteúdo: " + err.message);
  }
}

document.getElementById("btn-toggle-artifacts")?.addEventListener("click", async () => {
  if (el.app.classList.contains("drawer-open") && state.drawerTab === "artifacts") {
    closeDrawer();
    return;
  }
  openDrawer("artifacts");
  await loadArtifacts();
});

document.getElementById("btn-artifact-close")?.addEventListener("click", () => {
  document.getElementById("artifact-modal")?.close();
});

document.getElementById("btn-artifact-copy")?.addEventListener("click", (event) => {
  if (state.activeArtifact?.filename) {
    copyArtifactByName(state.activeArtifact.filename, event.currentTarget);
  }
});

document.getElementById("btn-artifact-wrap")?.addEventListener("click", (event) => {
  const pre = document.getElementById("artifact-modal-pre");
  if (!pre) return;
  const wrapped = pre.classList.toggle("wrapped");
  event.currentTarget.setAttribute("aria-pressed", String(wrapped));
});

document.getElementById("artifact-modal")?.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});

document.addEventListener("click", (event) => {
  const actBtn = event.target.closest("[data-art-act]");
  if (actBtn) {
    const filename = actBtn.dataset.artifactName;
    if (!filename) return;
    if (actBtn.dataset.artAct === "open") openArtifactModal(filename);
    else if (actBtn.dataset.artAct === "copy") copyArtifactByName(filename, actBtn);
    return;
  }
  const card = event.target.closest(".artifact-card");
  if (card && card.dataset.artifactName) {
    event.preventDefault();
    openArtifactModal(card.dataset.artifactName);
  }
});

const _origRefreshMessages = refreshMessages;
refreshMessages = async function (chat) {
  const ok = await _origRefreshMessages(chat);
  if (ok && chat?.thread_id) loadArtifacts(chat.thread_id);
  return ok;
};

// ============================================================
// SALVAR RESPOSTA COMO ARTEFATO (.md / .pdf) E MODAL DE CONFIGURAÇÕES & VRAM
// ============================================================

async function saveMessageAsArtifact(content, format = "md", button = null) {
  const chat = activeChatOrNull();
  if (!chat?.thread_id) return;
  const prev = button ? button.textContent : "";
  if (button) { button.disabled = true; button.textContent = "Salvando…"; }
  try {
    const data = await api(API.saveArtifact(chat.thread_id), {
      method: "POST",
      body: JSON.stringify({ content: String(content || ""), title: chat.title || "", format }),
    });
    await loadArtifacts(chat.thread_id);
    if (button) {
      button.textContent = "Salvo ✓";
      setTimeout(() => { button.textContent = prev; button.disabled = false; }, 1600);
    }
    if (data?.filename) openArtifactModal(data.filename);
  } catch (err) {
    if (button) { button.textContent = prev; button.disabled = false; }
    alert("Não foi possível salvar como artefato: " + err.message);
  }
}

function formatGb(bytes) {
  const n = Number(bytes || 0);
  if (n <= 0) return "0 MB";
  if (n < 1024 * 1024 * 1024) return `${Math.round(n / (1024 * 1024))} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

async function loadSettingsModal() {
  const status = document.getElementById("settings-status");
  if (status) status.textContent = "Carregando…";
  try {
    const data = await api(API.settings);
    const cfg = data?.settings || {};
    const elWeb = document.getElementById("cfg-web-search");
    const elMem = document.getElementById("cfg-memory");
    const elAuto = document.getElementById("cfg-autocommit");
    const elTimeout = document.getElementById("cfg-audit-timeout");
    const elChunk = document.getElementById("cfg-audit-chunk");
    if (elWeb) elWeb.checked = Boolean(cfg.web_search_enabled);
    if (elMem) elMem.checked = Boolean(cfg.assistant_memory_enabled);
    if (elAuto) elAuto.checked = Boolean(cfg.autocommit_enabled);
    if (elTimeout) elTimeout.value = String(cfg.audit_tool_timeout ?? 180);
    if (elChunk) elChunk.value = String(cfg.audit_chunk_size ?? 40);
    if (status) status.textContent = "";
  } catch (err) {
    if (status) status.textContent = "Erro: " + err.message;
  }
  loadOllamaStatus();
}

function renderOllamaStatus(data) {
  const summary = document.getElementById("ollama-summary");
  const list = document.getElementById("ollama-models-list");
  const unloadAllBtn = document.getElementById("btn-ollama-unload-all");
  if (!list || !summary) return;
  if (!data?.online) {
    summary.textContent = `Ollama indisponível (${data?.base_url || "localhost:11434"})`;
    list.innerHTML = `<div class="tasks-empty">${escapeHtml(data?.error || "Sem resposta do Ollama.")}</div>`;
    if (unloadAllBtn) unloadAllBtn.disabled = true;
    return;
  }
  const models = Array.isArray(data.models) ? data.models : [];
  if (unloadAllBtn) unloadAllBtn.disabled = models.length === 0;
  if (!models.length) {
    summary.textContent = "Online · Nenhum modelo carregado na VRAM";
    list.innerHTML = '<div class="tasks-empty">VRAM livre: nenhum modelo ativo no Ollama agora.</div>';
    return;
  }
  summary.textContent = `${models.length} modelo(s) ativo(s) · VRAM: ${formatGb(data.total_vram_bytes)} · Total: ${formatGb(data.total_size_bytes)}`;
  list.innerHTML = models.map((m) => {
    const meta = [m.parameter_size, m.quantization_level, `VRAM: ${formatGb(m.size_vram)}`].filter(Boolean).join(" · ");
    return `
      <div class="ollama-model-row">
        <div class="ollama-model-info">
          <b>${escapeHtml(m.name)}</b>
          <small>${escapeHtml(meta)}</small>
        </div>
        <button type="button" class="btn btn-ghost btn-sm btn-ollama-unload-one" data-model="${escapeHtml(m.name)}">Descarregar</button>
      </div>
    `;
  }).join("");
}

async function loadOllamaStatus() {
  const summary = document.getElementById("ollama-summary");
  if (summary) summary.textContent = "Consultando Ollama…";
  try {
    const data = await api(API.ollamaPs);
    renderOllamaStatus(data);
  } catch (err) {
    renderOllamaStatus({ online: false, error: err.message });
  }
}

async function unloadOllamaModel(modelName = null, button = null) {
  const prev = button ? button.textContent : "";
  if (button) { button.disabled = true; button.textContent = "Liberando…"; }
  try {
    const res = await api(API.ollamaUnload, {
      method: "POST",
      body: JSON.stringify({ model: modelName }),
    });
    if (res?.ollama) renderOllamaStatus(res.ollama);
    else await loadOllamaStatus();
  } catch (err) {
    alert("Não foi possível descarregar da VRAM: " + err.message);
  } finally {
    if (button) { button.disabled = false; button.textContent = prev; }
  }
}

document.getElementById("btn-settings")?.addEventListener("click", () => {
  if (isMobile()) closeSidebar();
  const modal = document.getElementById("settings-modal");
  if (modal && !modal.open) modal.showModal();
  loadSettingsModal();
});

document.getElementById("btn-settings-close")?.addEventListener("click", () => {
  document.getElementById("settings-modal")?.close();
});

document.getElementById("settings-modal")?.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});

document.getElementById("settings-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("settings-status");
  if (status) status.textContent = "Salvando…";
  try {
    const res = await api(API.settings, {
      method: "PUT",
      body: JSON.stringify({
        web_search_enabled: Boolean(document.getElementById("cfg-web-search")?.checked),
        assistant_memory_enabled: Boolean(document.getElementById("cfg-memory")?.checked),
        autocommit_enabled: Boolean(document.getElementById("cfg-autocommit")?.checked),
        audit_tool_timeout: Number(document.getElementById("cfg-audit-timeout")?.value ?? 180),
        audit_chunk_size: Number(document.getElementById("cfg-audit-chunk")?.value ?? 40),
      }),
    });
    state.autocommit = Boolean(res?.settings?.autocommit_enabled);
    renderAutocommitButton();
    if (status) {
      status.textContent = "Preferências salvas ✓";
      setTimeout(() => { if (status.textContent === "Preferências salvas ✓") status.textContent = ""; }, 2000);
    }
  } catch (err) {
    if (status) status.textContent = "Erro: " + err.message;
  }
});

document.getElementById("btn-ollama-refresh")?.addEventListener("click", loadOllamaStatus);
document.getElementById("btn-ollama-unload-all")?.addEventListener("click", (e) => unloadOllamaModel(null, e.currentTarget));
document.getElementById("ollama-models-list")?.addEventListener("click", (event) => {
  const btn = event.target.closest(".btn-ollama-unload-one");
  if (btn?.dataset.model) unloadOllamaModel(btn.dataset.model, btn);
});

// ============================================================
// FASE 2: PASTAS/TAGS, FIXAR CONVERSA, BUSCA GLOBAL E PERFIS RÁPIDOS
// ============================================================

state.chatFolderFilter = "all";
state.chatTagFilter = "";
state.chatPresets = {};
const PRESET_EXAMPLES = {
  default: "Uso livre: tire dúvidas, peça explicações ou converse normalmente.",
  tutor: "Ex.: \"Me explique como funciona async/await\" — explica os fundamentos e faz perguntas guiadas sem entregar tudo pronto.",
  revisor: "Ex.: Cole um e-mail ou texto e peça \"revise este texto\" — devolve pronto para copiar + resumo dos ajustes.",
  planejador: "Ex.: \"Organize um plano de estudos de 2 semanas\" — divide em etapas priorizadas, riscos e checklist.",
  direto: "Ex.: \"Qual comando para desfazer o último commit?\" — resposta curta, sem introduções nem rodeios.",
};

state.presetCatalog = [
  { id: "default", label: "Padrão", short_label: "Padrão", description: "Comportamento equilibrado padrão do assistente." },
  { id: "tutor", label: "Tutor Socrático", short_label: "Tutor", description: "Ensina pelos fundamentos com perguntas guiadas, sem entregar tudo pronto de cara." },
  { id: "revisor", label: "Revisor de Texto", short_label: "Revisor", description: "Melhora clareza, gramática, concisão e tom de e-mails, mensagens e documentos." },
  { id: "planejador", label: "Planejador", short_label: "Planejador", description: "Quebra ideias e metas em etapas priorizadas, prazos, riscos e checklists." },
  { id: "direto", label: "Direto ao Ponto", short_label: "Direto", description: "Respostas curtas e objetivas, sem rodeios nem introduções longas." },
];

const PRESET_STORE = "assistant_chat_presets";
let globalSearchTimer = null;
let globalSearchSeq = 0;

function loadSavedPresets() {
  try { state.chatPresets = JSON.parse(localStorage.getItem(PRESET_STORE) || "{}") || {}; }
  catch { state.chatPresets = {}; }
}

function saveChatPresets() {
  try { localStorage.setItem(PRESET_STORE, JSON.stringify(state.chatPresets)); } catch {}
}

function getChatPreset() {
  const key = state.activeId != null ? String(state.activeId) : "__draft__";
  return state.chatPresets[key] || "default";
}

function setChatPreset(presetId) {
  const key = state.activeId != null ? String(state.activeId) : "__draft__";
  if (!presetId || presetId === "default") delete state.chatPresets[key];
  else state.chatPresets[key] = presetId;
  saveChatPresets();
  syncPresetUI();
}

function renderPresetMenu() {
  const list = document.getElementById("preset-list");
  if (!list) return;
  const current = getChatPreset();
  list.innerHTML = state.presetCatalog.map((p) => {
    const active = p.id === current;
    const tip = PRESET_EXAMPLES[p.id] || "";
    return `
      <button type="button" class="preset-option${active ? " active" : ""}" data-preset-id="${escapeHtml(p.id)}">
        <span class="preset-opt-head">
          <b>${escapeHtml(p.label)}</b>
          ${active ? `<span class="preset-opt-check">${ICON.check}</span>` : ""}
        </span>
        ${p.description ? `<small class="preset-opt-desc">${escapeHtml(p.description)}</small>` : ""}
        ${tip ? `<small class="preset-opt-tip">${escapeHtml(tip)}</small>` : ""}
      </button>
    `;
  }).join("");
}

function closePresetMenu() {
  const menu = document.getElementById("preset-menu");
  const btn = document.getElementById("btn-preset");
  if (menu) menu.classList.add("hidden");
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function togglePresetMenu() {
  const menu = document.getElementById("preset-menu");
  const btn = document.getElementById("btn-preset");
  if (!menu || !btn) return;
  const opening = menu.classList.contains("hidden");
  closeSourcesMenu();
  menu.classList.toggle("hidden", !opening);
  btn.setAttribute("aria-expanded", String(opening));
  if (opening) renderPresetMenu();
}

function syncPresetUI() {
  const btn = document.getElementById("btn-preset");
  const lbl = document.getElementById("preset-btn-label");
  const current = getChatPreset();
  const meta = state.presetCatalog.find((p) => p.id === current) || state.presetCatalog[0];
  if (btn) {
    btn.classList.toggle("active", current !== "default");
    btn.title = meta ? `${meta.label}: ${meta.description || ""}` : "Perfil de resposta";
  }
  if (lbl && meta) lbl.textContent = meta.short_label || meta.label;
  renderPresetMenu();
  if (getRouteMode() === "auto" && el.composerFoot) {
    if (current !== "default" && meta) {
      el.composerFoot.classList.add("fixed");
      el.composerFoot.innerHTML = `Perfil <b>${escapeHtml(meta.label)}</b> ativo nesta conversa · ${escapeHtml(meta.description || "")}`;
    } else {
      el.composerFoot.classList.remove("fixed");
      el.composerFoot.textContent = "Enter envia · Shift+Enter quebra a linha";
    }
  }
}

async function initPresetCatalog() {
  loadSavedPresets();
  try {
    const data = await api(API.chatPresets);
    if (Array.isArray(data?.presets) && data.presets.length) {
      state.presetCatalog = data.presets;
    }
  } catch {}
  syncPresetUI();
}

document.getElementById("btn-preset")?.addEventListener("click", (event) => {
  event.stopPropagation();
  togglePresetMenu();
});
document.getElementById("preset-menu")?.addEventListener("click", (event) => {
  event.stopPropagation();
  const opt = event.target.closest("[data-preset-id]");
  if (!opt) return;
  setChatPreset(opt.dataset.presetId);
  closePresetMenu();
});
document.addEventListener("click", closePresetMenu);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closePresetMenu(); });

const _origSyncChipsPhase2 = syncChips;
syncChips = function () {
  _origSyncChipsPhase2();
  syncPresetUI();
};

function renderFolderBar() {
  const bar = document.getElementById("chat-folder-bar");
  if (!bar) return;
  const folders = [...new Set(state.chats.map((c) => String(c.folder || "").trim()).filter(Boolean))].sort();
  const hasPinned = state.chats.some((c) => c.pinned);
  const hasTag = Boolean(state.chatTagFilter);
  if (!folders.length && !hasPinned && !hasTag) {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  bar.classList.remove("hidden");
  const pills = [
    `<button type="button" class="folder-pill${state.chatFolderFilter === "all" && !hasTag ? " active" : ""}" data-folder-filter="all">Todas</button>`,
  ];
  if (hasPinned) {
    pills.push(`<button type="button" class="folder-pill${state.chatFolderFilter === "__pinned__" ? " active" : ""}" data-folder-filter="__pinned__">📌 Fixadas</button>`);
  }
  folders.forEach((folder) => {
    const on = state.chatFolderFilter === folder;
    pills.push(`<button type="button" class="folder-pill${on ? " active" : ""}" data-folder-filter="${escapeHtml(folder)}">${escapeHtml(folder)}</button>`);
  });
  if (hasTag) {
    pills.push(`<button type="button" class="folder-pill active tag-clear" data-clear-tag="1">#${escapeHtml(state.chatTagFilter)} ×</button>`);
  }
  bar.innerHTML = pills.join("");
}

document.getElementById("chat-folder-bar")?.addEventListener("click", (event) => {
  const clearBtn = event.target.closest("[data-clear-tag]");
  if (clearBtn) {
    state.chatTagFilter = "";
    renderChatList();
    return;
  }
  const btn = event.target.closest("[data-folder-filter]");
  if (!btn) return;
  state.chatFolderFilter = btn.dataset.folderFilter || "all";
  if (state.chatFolderFilter === "all") state.chatTagFilter = "";
  renderChatList();
});

async function toggleChatSidebarPin(chatId) {
  const chat = state.chats.find((c) => c.id === chatId);
  if (!chat) return;
  const nextPinned = !chat.pinned;
  try {
    const updated = await api(API.chat(chatId), {
      method: "PUT",
      body: JSON.stringify({ pinned: nextPinned }),
    });
    Object.assign(chat, updated || { pinned: nextPinned });
    renderChatList();
  } catch (err) {
    alert("Não foi possível fixar a conversa: " + err.message);
  }
}

function openChatOrgModal(chat) {
  const modal = document.getElementById("chat-org-modal");
  if (!modal || !chat) return;
  document.getElementById("org-chat-id").value = String(chat.id);
  document.getElementById("org-chat-folder").value = chat.folder || "";
  document.getElementById("org-chat-tags").value = (chat.tags || []).join(", ");
  document.getElementById("org-chat-pinned").checked = Boolean(chat.pinned);
  if (!modal.open) modal.showModal();
}

document.getElementById("btn-org-cancel")?.addEventListener("click", () => {
  document.getElementById("chat-org-modal")?.close();
});

document.getElementById("chat-org-modal")?.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});

document.getElementById("org-quick-folders")?.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-folder]");
  if (!btn) return;
  const input = document.getElementById("org-chat-folder");
  if (input) input.value = btn.dataset.folder || "";
});

document.getElementById("chat-org-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const chatId = Number(document.getElementById("org-chat-id")?.value);
  const chat = state.chats.find((c) => c.id === chatId);
  if (!chat) return;
  const folder = String(document.getElementById("org-chat-folder")?.value || "").trim();
  const tagsRaw = String(document.getElementById("org-chat-tags")?.value || "");
  const tags = tagsRaw.split(",").map((t) => t.trim()).filter(Boolean);
  const pinned = Boolean(document.getElementById("org-chat-pinned")?.checked);
  try {
    const updated = await api(API.chat(chatId), {
      method: "PUT",
      body: JSON.stringify({ folder, tags, pinned }),
    });
    Object.assign(chat, updated || { folder, tags, pinned });
    renderChatList();
    document.getElementById("chat-org-modal")?.close();
  } catch (err) {
    alert("Não foi possível salvar organização: " + err.message);
  }
});

function scheduleGlobalChatSearch(rawQuery) {
  clearTimeout(globalSearchTimer);
  const box = document.getElementById("chat-search-results");
  const query = String(rawQuery || "").trim();
  if (!box) return;
  if (query.length < 2) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  const reqSeq = ++globalSearchSeq;
  globalSearchTimer = setTimeout(async () => {
    box.classList.remove("hidden");
    box.innerHTML = '<div class="search-res-head">Buscando nas mensagens…</div>';
    try {
      const data = await api(`${API.chatSearch}?q=${encodeURIComponent(query)}`);
      if (reqSeq !== globalSearchSeq) return;
      const matches = (data?.results || []).filter((item) => item.match_in === "message");
      if (!matches.length) {
        box.innerHTML = '<div class="search-res-head">Nenhuma ocorrência dentro das mensagens.</div>';
        return;
      }
      box.innerHTML = `
        <div class="search-res-head">Mensagens encontradas (${matches.length})</div>
        ${matches.slice(0, 12).map((item) => `
          <button type="button" class="search-res-item" data-chat-id="${item.chat_id}" data-message-id="${escapeHtml(item.message_id || "")}">
            <span class="search-res-title">${escapeHtml(item.title || "Conversa")} <small>${item.role === "user" ? "Você" : "Assistente"}</small></span>
            <span class="search-res-snippet">${escapeHtml(item.snippet || "")}</span>
          </button>
        `).join("")}
      `;
    } catch (err) {
      if (reqSeq !== globalSearchSeq) return;
      box.innerHTML = `<div class="search-res-head">Falha na busca: ${escapeHtml(err.message)}</div>`;
    }
  }, 320);
}

document.getElementById("chat-search-results")?.addEventListener("click", async (event) => {
  const btn = event.target.closest(".search-res-item");
  if (!btn) return;
  const chatId = Number(btn.dataset.chatId);
  const msgId = btn.dataset.messageId;
  if (!chatId) return;
  await openChat(chatId);
  if (msgId) {
    const target = [...el.messages.querySelectorAll("[data-message-id]")].find((n) => n.dataset.messageId === msgId);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("msg-flash");
      setTimeout(() => target.classList.remove("msg-flash"), 2000);
    }
  }
});

initPresetCatalog();

// ============================================================
// FASE 3: GERENCIADOR VISUAL DE MEMÓRIAS
// ============================================================

state.memories = [];
state.memoriesEnabled = true;
state.memoriesFilter = "";

function renderMemoriesList() {
  const list = document.getElementById("memories-list");
  const meta = document.getElementById("memories-meta");
  if (meta) {
    const statusNote = state.memoriesEnabled ? "ativa" : "desligada nas Configurações";
    meta.textContent = `${state.memories.length} memória(s) · ${statusNote}`;
  }
  if (!list) return;
  const q = String(state.memoriesFilter || "").trim().toLowerCase();
  const visible = state.memories
    .filter((item) => !q || String(item.text || "").toLowerCase().includes(q))
    .slice()
    .reverse();
  if (!visible.length) {
    list.innerHTML = `<div class="tasks-empty">${q ? "Nenhuma memória corresponde ao filtro." : "Nenhuma memória salva ainda."}</div>`;
    return;
  }
  list.innerHTML = visible.map((item) => `
    <article class="memory-row" data-memory-id="${item.id}">
      <div class="memory-row-main">
        <span class="memory-id">#${item.id}</span>
        <p class="memory-text">${escapeHtml(item.text)}</p>
      </div>
      <div class="memory-row-actions">
        <button type="button" class="btn btn-ghost btn-sm" data-mem-act="edit" data-memory-id="${item.id}">Editar</button>
        <button type="button" class="btn btn-ghost btn-sm btn-danger-soft" data-mem-act="delete" data-memory-id="${item.id}">Apagar</button>
      </div>
    </article>
  `).join("");
}

async function loadMemoriesModal() {
  const meta = document.getElementById("memories-meta");
  if (meta) meta.textContent = "Carregando…";
  try {
    const data = await api(API.memories);
    state.memories = Array.isArray(data?.items) ? data.items : [];
    state.memoriesEnabled = Boolean(data?.enabled);
    renderMemoriesList();
  } catch (err) {
    if (meta) meta.textContent = "Erro: " + err.message;
  }
}

document.getElementById("btn-memories")?.addEventListener("click", () => {
  if (isMobile()) closeSidebar();
  const modal = document.getElementById("memories-modal");
  if (modal && !modal.open) modal.showModal();
  loadMemoriesModal();
});

document.getElementById("btn-memories-close")?.addEventListener("click", () => {
  document.getElementById("memories-modal")?.close();
});

document.getElementById("memories-modal")?.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});

document.getElementById("memory-filter")?.addEventListener("input", (event) => {
  state.memoriesFilter = event.currentTarget.value;
  renderMemoriesList();
});

document.getElementById("memory-add-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("memory-new-input");
  const text = String(input?.value || "").trim();
  if (!text) return;
  try {
    const res = await api(API.memories, { method: "POST", body: JSON.stringify({ text }) });
    state.memories = Array.isArray(res?.items) ? res.items : state.memories;
    if (input) input.value = "";
    renderMemoriesList();
  } catch (err) {
    alert("Não foi possível adicionar memória: " + err.message);
  }
});

document.getElementById("memories-list")?.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-mem-act]");
  if (!btn) return;
  const id = Number(btn.dataset.memoryId);
  const item = state.memories.find((m) => m.id === id);
  if (!item) return;
  if (btn.dataset.memAct === "edit") {
    const next = prompt("Editar memória:", item.text);
    if (next === null || !next.trim()) return;
    try {
      const res = await api(API.memoryItem(id), { method: "PUT", body: JSON.stringify({ text: next.trim() }) });
      state.memories = Array.isArray(res?.items) ? res.items : state.memories;
      renderMemoriesList();
    } catch (err) {
      alert("Não foi possível editar memória: " + err.message);
    }
  } else if (btn.dataset.memAct === "delete") {
    if (!confirm(`Apagar a memória #${id}?`)) return;
    try {
      const res = await api(API.memoryItem(id), { method: "DELETE" });
      state.memories = Array.isArray(res?.items) ? res.items : state.memories.filter((m) => m.id !== id);
      renderMemoriesList();
    } catch (err) {
      alert("Não foi possível apagar memória: " + err.message);
    }
  }
});

// ============================================================
// TABELAS MARKDOWN RESPONSIVAS
// ============================================================

function enhanceTables(container) {
  if (!container) return;
  container.querySelectorAll(".msg-content table, .md table").forEach((table) => {
    if (table.parentElement?.classList.contains("table-wrap")) return;
    const wrapper = document.createElement("div");
    wrapper.className = "table-wrap";
    table.parentNode.insertBefore(wrapper, table);
    wrapper.appendChild(table);
  });
}

// ============================================================
// ABA MONITOR: DOCKER COMPOSE WATCHER + TESTADOR DE ROTAS
// ============================================================

state.lastRouteReport = null;

async function refreshMonitorStatus() {
  const badge = document.getElementById("mon-badge");
  const buildInfo = document.getElementById("mon-build-info");
  const logsEl = document.getElementById("mon-logs");
  const btnStart = document.getElementById("btn-mon-start");
  const btnStop = document.getElementById("btn-mon-stop");
  if (!badge || !logsEl) return;

  if (!state.workspacePath) {
    badge.textContent = "Sem projeto";
    badge.className = "mon-badge off";
    if (btnStart) btnStart.disabled = true;
    if (btnStop) btnStop.disabled = true;
    logsEl.textContent = "Escolha um projeto na aba Projeto para monitorar o Docker Compose.";
    return;
  }

  try {
    const data = await api(`${API.monitorStatus}?workspace_path=${encodeURIComponent(state.workspacePath)}`);
    const mon = data?.active;
    const running = Boolean(mon?.running);
    badge.textContent = mon?.building ? "Buildando…" : (running ? "Escutando" : "Parado");
    badge.className = "mon-badge " + (mon?.building ? "warn" : (running ? "on" : "off"));
    if (btnStart) btnStart.disabled = running;
    if (btnStop) btnStop.disabled = !running;
    if (buildInfo) {
      buildInfo.textContent = mon?.last_build_seconds != null
        ? `Último build: ${mon.last_build_seconds} s (${mon.last_build_ok ? "OK" : "Falhou"})`
        : (mon ? `${mon.lines_seen || 0} linhas · ${mon.errors_detected || 0} erro(s)` : "Nenhum build medido");
    }
    if (mon?.recent_logs?.length) {
      logsEl.textContent = mon.recent_logs.join("\n");
      logsEl.scrollTop = logsEl.scrollHeight;
    } else if (!running) {
      logsEl.textContent = "Monitor parado. Clique em Iniciar Monitor para acompanhar os logs em tempo real.";
    }
  } catch (err) {
    logsEl.textContent = "Erro ao consultar monitor: " + err.message;
  }
}

document.getElementById("btn-mon-start")?.addEventListener("click", async () => {
  const chat = activeChatOrNull();
  if (!state.workspacePath) return alert("Selecione um projeto na aba Projeto primeiro.");
  try {
    await api(API.monitorStart, {
      method: "POST",
      body: JSON.stringify({ workspace_path: state.workspacePath, thread_id: chat?.thread_id || "", auto_diagnose: true }),
    });
    await refreshMonitorStatus();
  } catch (err) {
    alert("Falha ao iniciar monitor: " + err.message);
  }
});

document.getElementById("btn-mon-stop")?.addEventListener("click", async () => {
  if (!state.workspacePath) return;
  try {
    await api(API.monitorStop, { method: "POST", body: JSON.stringify({ workspace_path: state.workspacePath }) });
    await refreshMonitorStatus();
  } catch (err) {
    alert("Falha ao parar monitor: " + err.message);
  }
});

document.getElementById("btn-mon-build")?.addEventListener("click", async () => {
  const chat = activeChatOrNull();
  if (!state.workspacePath) return alert("Selecione um projeto na aba Projeto primeiro.");
  try {
    const res = await api(API.monitorBuild, {
      method: "POST",
      body: JSON.stringify({ workspace_path: state.workspacePath, thread_id: chat?.thread_id || "", auto_diagnose: true }),
    });
    if (res?.message) appendNotice(res.message);
    await refreshMonitorStatus();
  } catch (err) {
    alert("Falha ao iniciar build: " + err.message);
  }
});

document.getElementById("btn-rt-run")?.addEventListener("click", async (event) => {
  const btn = event.currentTarget;
  const baseUrl = String(document.getElementById("rt-base-url")?.value || "").trim();
  const routes = String(document.getElementById("rt-routes")?.value || "").trim();
  const box = document.getElementById("rt-results");
  const diagBtn = document.getElementById("btn-rt-diagnose");
  if (!baseUrl || !box) return;

  btn.disabled = true;
  btn.textContent = "Testando…";
  box.innerHTML = '<div class="tasks-empty">Testando rotas locais…</div>';
  diagBtn?.classList.add("hidden");
  try {
    const res = await api(API.monitorTestRoutes, {
      method: "POST",
      body: JSON.stringify({ base_url: baseUrl, routes }),
    });
    state.lastRouteReport = res;
    const rows = [
      ...(res.failed || []).map((i) => `<div class="rt-row fail"><b>HTTP ${i.status}</b><code>${escapeHtml(i.path)}</code><small>${escapeHtml(i.detail || "")}</small></div>`),
      ...(res.passed || []).map((i) => `<div class="rt-row ok"><b>HTTP ${i.status}</b><code>${escapeHtml(i.path)}</code><small>${i.ms} ms</small></div>`),
    ];
    box.innerHTML = `<div class="rt-summary">${res.passed.length} passou · ${res.failed.length} falhou (${escapeHtml(res.discovered_via)})</div>` + rows.join("");
    if (res.failed?.length) diagBtn?.classList.remove("hidden");
  } catch (err) {
    box.innerHTML = `<div class="task-error"><pre>${escapeHtml(err.message)}</pre></div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Testar rotas";
  }
});

document.getElementById("btn-rt-diagnose")?.addEventListener("click", async () => {
  if (!state.lastRouteReport?.failed?.length) return;
  const prompt = (
    "Testei as rotas locais e encontrei estas falhas. Leia os logs do Docker/código relevante, " +
    "explique a causa de cada erro, sugira a correção e pergunte se quero gerar tasks:\n\n" +
    state.lastRouteReport.markdown
  );
  closeDrawerIfOverlay();
  await sendMessage(prompt);
});

const _origSetDrawerTabMon = setDrawerTab;
setDrawerTab = function (tab) {
  _origSetDrawerTabMon(tab);
  if (tab === "monitor") refreshMonitorStatus();
};
