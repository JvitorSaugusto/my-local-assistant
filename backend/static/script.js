/* ============================================================
   Assistente IA Local — cliente
   Desktop + Mobile
   ============================================================ */

const API = {
  chats: "/api/chats/",
  chat: (id) => `/api/chats/${id}`,
  messages: (thread_id) => `/api/ai/${thread_id}/messages`,
  tasks: (thread_id) => `/api/tasks/${thread_id}/tasks`,
  createTask: (threadId) => `/api/tasks/${threadId}`,
  updateTask: (taskId) => `/api/tasks/${taskId}`,
  deleteTask: (taskId) => `/api/tasks/${taskId}`,
  retryTask: (taskId) => `/api/tasks/${taskId}/retry`,
  taskDiff: (taskId) => `/api/tasks/${taskId}/diff`,
  bulkDeleteTasks: "/api/tasks/bulk/delete",
  handoffPlan: "/api/handoff/plan",
  ragScope: "/api/rag/scope",
  ragLinks: "/api/rag/links",
  createTasksBatch: (threadId) => `/api/tasks/${threadId}`,
  send: "/api/ai/",
  stop: (threadId) => `/api/ai/${threadId}/stop`,
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
    if (active && state.workspaces.includes(active)) {
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
}

function renderWorkspaces() {
  syncWorkspaceChip();
  loadRagScope();
  el.workspaceList.innerHTML = "";
  if (!state.workspaces.length) {
    el.workspaceList.innerHTML = `<div class="workspace-empty">Nenhum diretório adicionado.</div>`;
    el.workspacePath.value = "";
    return;
  }
  state.workspaces.forEach((workspace) => {
    const item = document.createElement("div");
    item.className = "workspace-item" + (workspace === state.workspacePath ? " active" : "");
    item.innerHTML = `
      <button type="button" class="workspace-select" title="Usar este diretório">${escapeHtml(workspace)}</button>
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
  el.chatList.innerHTML = "";
  const query = state.chatQuery.trim().toLowerCase();
  const chats = state.chats
    .filter((chat) => !query || String(chat.title || "").toLowerCase().includes(query))
    .sort((a, b) => (Date.parse(b.created_at) || Date.now()) - (Date.parse(a.created_at) || Date.now()));

  if (!chats.length && query) {
    const empty = document.createElement("li");
    empty.className = "chat-group";
    empty.textContent = "Nenhuma conversa encontrada";
    el.chatList.appendChild(empty);
    return;
  }

  let lastGroup = null;
  chats.forEach((chat) => {
    const group = chatGroupLabel(chat.created_at);
    if (group !== lastGroup) {
      const header = document.createElement("li");
      header.className = "chat-group";
      header.textContent = group;
      el.chatList.appendChild(header);
      lastGroup = group;
    }
    const li = document.createElement("li");
    li.className = "chat-item" + (chat.id === state.activeId ? " active" : "");
    li.dataset.id = chat.id;
    li.innerHTML = `
      ${ICON.bubble}
      <span class="chat-item-title">${escapeHtml(chat.title || "Nova conversa")}</span>
      <span class="chat-edit" title="Editar título" role="button">${ICON.pencil}</span>
      <span class="chat-del" title="Excluir" role="button">${ICON.trash}</span>
    `;
    li.addEventListener("click", (event) => {
      if (event.target.closest(".chat-del") || event.target.closest(".chat-edit")) return;
      openChat(chat.id);
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
      .map((step, i) => `${i + 1}. ${step.op}${step.path ? " " + step.path : ""}${step.branch ? " " + step.branch : ""}`)
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

  if (isMobile()) closeSidebar();

  if (!chat || !chat.thread_id) {
    if (!isMobile()) el.chatInput.focus();
    return;
  }
  const requestChatId = id;
  state.tasksSig = null;
  await loadTasks(chat.thread_id);

  try {
    const data = await api(API.messages(chat.thread_id));
    if (state.activeId !== requestChatId) return;
    const messages = data?.messages ?? [];
    renderHistory(messages);
    
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
  el.chatTitle.textContent = "Assistente Local";
  closeDrawer();
}

function renderHistory(messages) {
  el.messages.innerHTML = "";
  messages.forEach((m) => appendMessage(m.role, m.content, m.model, m));
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
    : `<button class="msg-raw-toggle" type="button">Ver formato puro</button><pre class="msg-raw hidden">${escapeHtml(content)}</pre>`;

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
  }
  el.messages.appendChild(wrap);
  if (!isUser) enhanceCodeBlocks(wrap);
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

// Envia os anexos ao workspace e devolve o texto final da mensagem (ou null se falhar).
async function composeWithAttachments(text) {
  if (!state.workspacePath) {
    alert("Defina um diretório de trabalho para poder anexar arquivos.");
    return null;
  }
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
      form.append("workspace_path", state.workspacePath);
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
  state.attachments = [];
  renderAttachments();

  const base = text.trim() || "Analise os arquivos anexados.";
  return `${base}\n\n${ATTACHMENT_MARKER} (leia com read_file_content, read_file_chunk ou search_in_file):\n` +
    paths.map((path) => `- ${path}`).join("\n");
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

  try {
    const data = await api(API.send, { method: "POST", body: JSON.stringify({ thread_id: chat.thread_id, message: text, workspace_path: state.workspacePath }) });
    if (state.activeId !== chat.id) return;
    typing.remove();
    if (data?.cancelled) {
      await refreshMessages(chat);
      appendNotice("Resposta interrompida. Você pode editar sua mensagem e enviar de novo.");
    } else if (!(await refreshMessages(chat))) {
      appendMessage("assistant", data?.content ?? data?.message ?? "", data?.name ?? data?.model, data || {});
    }
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
    state.sending = false;
    state.stopRequested = false;
    setSendButtonMode(false);
    state.pendingChats.delete(chat.id);
    if (state.activeId === chat.id) {
      scrollToBottom();
      if (!isMobile()) el.chatInput.focus();
    }
  }
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
        const typingEl = el.messages.querySelector('[data-typing="1"]');
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
const ROUTE_TAGS = { auto: "", heavy: "@heavy", enhance: "@enhance" };
const ROUTE_LABEL = { heavy: "Heavy", enhance: "Enhance" };
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
  if (/^\s*@(?:generate|heavy|enhance)\b/i.test(text) || /(^|\s)@(?:heavy|enhance)(\s|$)/i.test(text)) return text;
  return `${tag} ${text.replace(/^\s+/, "")}`;
}

function syncChips() {
  const mode = getRouteMode();
  [[el.btnAuto, "auto"], [el.btnHeavy, "heavy"], [el.btnEnhance, "enhance"]].forEach(([button, name]) => {
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
    ? `Vale para o projeto <b>${escapeHtml(project)}</b>, em todas as conversas dele. Você também pode pedir uma fonte pelo nome na pergunta.`
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
        },
        task_id: task.id,
        save: true,
      }),
    });
    if (result.ok && result.saved) {
      alert(`Plano pronto (${result.attempts} tentativa(s)): ${result.task.steps.length} passo(s) validados no dry-run. A tarefa agora é determinística; execute normalmente.`);
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

const TASKS_PROMPT_TEMPLATE = "Você vai gerar MICROTASKS em JSON para o meu assistente de IA local. Ele possui dois modos de execução: DETERMINÍSTICO (padrão) e DINÂMICO (via LLM).\n\nREGRAS DE OURO PARA MODO DETERMINÍSTICO (Edições e Operações de Arquivo)\n- Na maioria das vezes, ele executa as tarefas de forma determinística: aplica exatamente o que você escrever e roda as verificações. Ele não interpreta nem corrige. Cada passo precisa ter o texto/código FINAL e EXATO.\n- Para alterar um arquivo existente (replace_text), preciso que você tenha o conteúdo atual dele. Se eu não colei, PEÇA o trecho em vez de adivinhar. O campo \"old\" tem que ser copiado EXATAMENTE (espaços, indentação, aspas).\n- Caminhos sempre RELATIVOS à raiz do projeto, com \"/\". Nunca mexa em .git, .env, node_modules, venv ou __pycache__. Não existe operação de apagar arquivos.\n\nREGRAS PARA MODO DINÂMICO / LLM (Documentação, Refatoração, Análise)\n- O assistente TEM capacidade de leitura, interpretação e geração de código/texto por conta própria.\n- Se a tarefa exigir análise de arquivos que acabaram de ser modificados, geração de documentação, ou refatoração complexa onde um \"replace_text\" determinístico seria inviável, DEIXE O ARRAY \"steps\" VAZIO: \"steps\": [].\n- Quando \"steps\" estiver vazio, o assistente usará o texto que você colocar no campo \"description\" como um prompt para executar a tarefa usando sua própria inteligência (LLM). Descreva EXATAMENTE o que ele deve ler e o que deve gerar.\n- DOCUMENTAÇÃO QUE VAI PARA OUTRA PESSOA: prefira o modo determinístico com write_markdown e o texto FINAL escrito por você a partir do código real que eu colei. Se usar o modo dinâmico, liste em \"files\" TODOS os arquivos-fonte e inclua em \"verify\" a checagem literals_grounded.\n- O modo dinâmico monta o contexto sozinho (git diff, arquivos, constantes referenciadas) e confere por código se os valores citados existem nas fontes.\n\nFORMATO DO JSON\n- Responda SOMENTE com um array JSON válido (sem comentários, sem Markdown fora do JSON).\n- Quebras de linha dentro do JSON são \"\\n\" e aspas internas são \\\".\n- Formato de cada objeto no array:\n{\n  \"title\": \"título curto\",\n  \"description\": \"o que a tarefa faz (se for dinâmica, seja extremamente detalhista aqui)\",\n  \"reason\": \"por que fazer\",\n  \"files\": [\"arquivos envolvidos (inclua os que serão criados/copiados/lidos)\"],\n  \"priority\": \"low | medium | high\",\n  \"steps\": [ ...operações (ou vazio [] para tarefas dinâmicas)... ],\n  \"verify\": [ ...checagens... ]\n}\n\nOPERAÇÕES DE \"steps\" (campo \"op\" - USE APENAS EM MODO DETERMINÍSTICO)\n- create_file: { \"op\": \"create_file\", \"path\": \"...\", \"content\": \"conteúdo COMPLETO\" }\n- replace_text: { \"op\": \"replace_text\", \"path\": \"...\", \"old\": \"trecho exato atual\", \"new\": \"trecho novo\", \"occurrences\": \"one\" | \"all\" }\n- append: { \"op\": \"append\", \"path\": \"...\", \"content\": \"texto adicionado ao final\" }\n- write_markdown: { \"op\": \"write_markdown\", \"path\": \"x.md\", \"content\": \"...\", \"overwrite\": false }\n- create_pdf: { \"op\": \"create_pdf\", \"path\": \"x.pdf\", \"title\": \"...\", \"content\": \"markdown\", \"overwrite\": false }\n- copy_upload: { \"op\": \"copy_upload\", \"path\": \"public/favicon.png\", \"source\": \"favicon.png\", \"overwrite\": false }\n- extract_zip: { \"op\": \"extract_zip\", \"path\": \"pasta/destino\", \"source\": \"codigo.zip\", \"on_conflict\": \"skip\" | \"overwrite\", \"strip_top_folder\": true }\n\nCHECAGENS DE \"verify\" (campo \"type\")\n- file_exists: { \"type\": \"file_exists\", \"path\": \"...\" }\n- contains: { \"type\": \"contains\", \"path\": \"...\", \"text\": \"trecho que deve existir\" }\n- not_contains: { \"type\": \"not_contains\", \"path\": \"...\", \"text\": \"trecho que NÃO pode existir\" }\n- python_syntax: { \"type\": \"python_syntax\", \"path\": \"arquivo.py\" }\n- literals_grounded: { \"type\": \"literals_grounded\", \"path\": \"doc.md\", \"sources\": [\"app/views.py\"], \"allow\": [] } (confere por código se valores entre aspas, headers e códigos HTTP do documento existem nas fontes)\n\nARQUIVOS ANEXADOS DISPONÍVEIS AGORA (use o nome exato em \"source\"):\n{{ANEXOS}}\n\nEXEMPLOS\n\nTarefa Determinística (Edição exata):\n[\n  {\n    \"title\": \"Aumentar fonte do título\",\n    \"description\": \"Aumenta a variável --title-size em style.css.\",\n    \"reason\": \"O título está pequeno em telas grandes.\",\n    \"files\": [\"app/style.css\"],\n    \"priority\": \"medium\",\n    \"steps\": [\n      { \"op\": \"replace_text\", \"path\": \"app/style.css\", \"old\": \"--title-size: 22px;\", \"new\": \"--title-size: 28px;\", \"occurrences\": \"one\" }\n    ],\n    \"verify\": [\n      { \"type\": \"contains\", \"path\": \"app/style.css\", \"text\": \"--title-size: 28px;\" }\n    ]\n  }\n]\n\nTarefa Dinâmica (Análise/Geração usando IA do assistente):\n[\n  {\n    \"title\": \"Documentar API\",\n    \"description\": \"Leia o arquivo app/views.py e crie um arquivo README.md detalhando os endpoints encontrados, métodos HTTP, payloads e retornos.\",\n    \"reason\": \"Facilitar o consumo da API pelo frontend.\",\n    \"files\": [\"app/views.py\", \"README.md\"],\n    \"priority\": \"medium\",\n    \"steps\": [],\n    \"verify\": [\n      { \"type\": \"file_exists\", \"path\": \"README.md\" }\n    ]\n  }\n]\n\nMINHA SOLICITAÇÃO:\n(descreva aqui o que você quer que seja feito no projeto)\n";

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
  if (chat && state.workspacePath) {
    try {
      const res = await fetch(`${API.upload(chat.thread_id)}?workspace_path=${encodeURIComponent(state.workspacePath)}`);
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
  if (!state.workspacePath) { alert("Defina um diretório de trabalho para poder anexar arquivos."); return; }
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
  // Abre o modal
  el.importTasksModal.showModal();
  refreshTaskUploads();
});

el.btnCancelImport.addEventListener('click', () => {
  // Fecha o modal
  el.importTasksModal.close();
});

el.importTasksForm.addEventListener('submit', async (event) => {
  // Previne o envio padrão do formulário
  event.preventDefault();
  
  try {
    // Tenta fazer o parse do JSON
    const parsed = JSON.parse(el.inputImportJson.value);
    
    // Garante que seja um array
    const tasksArray = Array.isArray(parsed) ? parsed : [parsed];
    
    // Pega o thread_id ativo
    const chat = state.chats.find(c => c.id === state.activeId);
    
    if (!chat) {
      alert('Nenhuma conversa ativa encontrada.');
      return;
    }
    
    // Faz o POST para criar as tarefas em batch
    const response = await fetch(API.createTasksBatch(chat.thread_id), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(tasksArray)
    });
    
    if (response.ok) {
      // Carrega as tarefas atualizadas
      loadTasks(chat.thread_id);
      // Fecha o modal
      el.importTasksModal.close();
    } else {
      let detail = '';
      try {
        const body = await response.json();
        detail = Array.isArray(body?.detail)
          ? body.detail.slice(0, 3).map((d) => `• ${(d.loc || []).filter((x) => x !== 'body').join('.')}: ${d.msg}`).join('\n')
          : (body?.detail || '');
      } catch {}
      alert('Erro ao importar tarefas.' + (detail ? '\n\n' + detail : ''));
      console.error('Erro na importação:', response);
    }
  } catch (error) {
    alert('Erro ao fazer parse do JSON. Verifique se o formato está correto.');
    console.error('Erro de parsing:', error);
  }
});