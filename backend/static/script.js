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
  createTasksBatch: (threadId) => `/api/tasks/${threadId}`,
  send: "/api/ai/",
  batch: "/api/ai/batch/",
};

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
  btnHeavy: document.getElementById("btn-heavy"),
  btnEnhance: document.getElementById("btn-enhance"),
  btnToggleBatch: document.getElementById("btn-toggle-batch"),
  batchPanel: document.getElementById("batch-panel"),
  batchInput: document.getElementById("batch-input"),
  btnSendBatch: document.getElementById("btn-send-batch"),
  batchStatus: document.getElementById("batch-status"),
  btnToggleTasks: document.getElementById("btn-toggle-tasks"),
  tasksPanel: document.getElementById("tasks-panel"),
  tasksList: document.getElementById("tasks-list"),
  tasksCount: document.getElementById("tasks-count"),
  btnExecuteTasks: document.getElementById("btn-execute-tasks"),
  workspacePath: document.getElementById("workspace-path"),
  btnAddWorkspace: document.getElementById("btn-add-workspace"),
  workspaceList: document.getElementById("workspace-list"),
  
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
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>`,
};

// ============================================================
// ESTADO
// ============================================================

const state = {
  chats: [],
  activeId: null,
  sending: false,
  pendingChats: new Set(),
  pollingInterval: null,
  expectedAiCount: {},
  workspacePath: "",
  workspaces: [],
  currentTasks: [], // Guarda as tarefas exibidas em tela para edição rápida
};

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

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

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
// MOBILE SIDEBAR
// ============================================================

function isMobile() { return window.matchMedia("(max-width: 780px)").matches; }
function openSidebar() { el.sidebar.classList.add("open"); el.sidebarToggle.setAttribute("aria-expanded", "true"); }
function closeSidebar() { el.sidebar.classList.remove("open"); el.sidebarToggle.setAttribute("aria-expanded", "false"); }
function toggleSidebar() { if (el.sidebar.classList.contains("open")) closeSidebar(); else openSidebar(); }

window.addEventListener("resize", () => { if (!isMobile()) closeSidebar(); });
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && isMobile() && el.sidebar.classList.contains("open")) closeSidebar();
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

function renderChatList() {
  el.chatList.innerHTML = "";
  state.chats.forEach((chat) => {
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
    state.currentTasks = Array.isArray(tasks) ? tasks : [];
    renderTasks(state.currentTasks);
  } catch (err) {
    state.currentTasks = [];
    renderTasks([]);
    el.tasksCount.textContent = "Não foi possível carregar as tarefas.";
  }
}

function renderTasks(tasks) {
  el.tasksList.innerHTML = "";
  const pendingTasks = tasks.filter((task) => task.status === "pending");
  el.tasksCount.textContent = pendingTasks.length
    ? `${pendingTasks.length} tarefa(s) pendente(s)`
    : "Nenhuma tarefa pendente.";
  
  el.btnExecuteTasks.disabled = !pendingTasks.length;

  if (!tasks.length) {
    el.tasksList.innerHTML = `<div class="tasks-empty">Nenhuma tarefa foi gerada nesta conversa.</div>`;
    return;
  }

  tasks.forEach((task) => {
    const card = document.createElement("article");
    card.className = "task-card";
    const files = Array.isArray(task.files) ? task.files : [];

    card.innerHTML = `
      <div class="task-card-head">
        <h4 class="task-card-title">${escapeHtml(task.title || "Tarefa sem título")}</h4>
        <div class="task-card-actions">
          <button class="btn-icon-task btn-edit-task" data-task-id="${task.id}" title="Editar">${ICON.pencil}</button>
          <button class="btn-icon-task btn-delete-task" data-task-id="${task.id}" title="Excluir">${ICON.trash}</button>
        </div>
      </div>
      <p class="task-card-description">${escapeHtml(task.description || "")}</p>
      ${files.length ? `
        <div class="task-files">
          ${files.map((file) => `<span class="task-file" title="${escapeHtml(file)}">${escapeHtml(file)}</span>`).join("")}
        </div>` : ""
      }
      <div class="task-card-footer">
        <span class="task-priority">${escapeHtml(task.priority || "medium")}</span>
        <span class="task-status ${escapeHtml(task.status || "pending")}">${escapeHtml(task.status || "pending")}</span>
      </div>
    `;
    el.tasksList.appendChild(card);
  });
}

function openTaskModal(task = null) {
  if (task) {
    el.modalTitle.textContent = "Editar Tarefa";
    el.inputId.value = task.id;
    el.inputTitle.value = task.title || "";
    el.inputDesc.value = task.description || "";
    el.inputFiles.value = Array.isArray(task.files) ? task.files.join(", ") : "";
  } else {
    el.modalTitle.textContent = "Nova Tarefa";
    el.inputId.value = "";
    el.inputTitle.value = "";
    el.inputDesc.value = "";
    el.inputFiles.value = "";
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
    el.tasksPanel.classList.add("hidden");
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
  el.messages.innerHTML = "";
  const chat = state.chats.find((item) => item.id === id);
  el.chatTitle.textContent = chat?.title || "Conversa";

  if (isMobile()) closeSidebar();

  if (!chat || !chat.thread_id) {
    if (!isMobile()) el.chatInput.focus();
    return;
  }
  const requestChatId = id;
  await loadTasks(chat.thread_id);

  try {
    const data = await api(API.messages(chat.thread_id));
    if (state.activeId !== requestChatId) return;
    const messages = data?.messages ?? [];
    messages.forEach((message) => appendMessage(message.role, message.content, message.model));
    
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
}

function appendMessage(role, content, modelName = null) {
  const isUser = role === "user";
  const wrap = document.createElement("div");
  wrap.className = `msg ${isUser ? "user" : "assistant"}`;
  let roleName = isUser ? "Você" : (modelName ? `Assistente (${modelName})` : "Assistente");
  const renderedContent = isUser ? escapeHtml(content) : renderContent(content);

  wrap.innerHTML = `
    <div class="msg-avatar">${isUser ? ICON.user : ICON.bot}</div>
    <div class="msg-body">
      <div class="msg-role">${escapeHtml(roleName)}</div>
      <div class="msg-content">${renderedContent}</div>
      ${!isUser ? `<button class="msg-raw-toggle" type="button">Ver formato puro</button><pre class="msg-raw hidden">${escapeHtml(content)}</pre>` : ""}
    </div>
  `;
  if (!isUser) {
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

function appendTyping() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  wrap.dataset.typing = "1";
  wrap.innerHTML = `<div class="msg-avatar">${ICON.bot}</div><div class="msg-body"><div class="msg-role">Assistente</div><div class="typing"><span></span><span></span><span></span></div></div>`;
  el.messages.appendChild(wrap);
  scrollToBottom();
  return wrap;
}

function scrollToBottom() {
  requestAnimationFrame(() => { el.messages.scrollTop = el.messages.scrollHeight; });
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
  state.pendingChats.add(chat.id);
  appendMessage("user", text);
  scrollToBottom();
  const typing = appendTyping();

  try {
    const data = await api(API.send, { method: "POST", body: JSON.stringify({ thread_id: chat.thread_id, message: text, workspace_path: state.workspacePath }) });
    if (state.activeId !== chat.id) return;
    typing.remove();
    appendMessage("assistant", data?.content ?? data?.message, data?.name ?? data?.model);
  } catch (err) {
    if (state.activeId === chat.id) {
      typing.remove();
      appendMessage("assistant", "Erro ao contatar o servidor.");
    }
  } finally {
    state.sending = false;
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
        el.messages.innerHTML = "";
        msgs.forEach(m => appendMessage(m.role, m.content, m.model));
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

function insertHeavy() {
  let value = el.chatInput.value;
  if (!/(^|\s)@heavy(\s|$)/.test(value)) {
    value = value.replace(/(^|\s)@enhance(\s|$)/g, ' '); 
    el.chatInput.value = "@heavy " + value.replace(/^\s+/, "");
  }
  el.chatInput.focus();
  autoResize();
  syncChips();
}

function insertEnhance() {
  let value = el.chatInput.value;
  if (!/(^|\s)@enhance(\s|$)/.test(value)) {
    value = value.replace(/(^|\s)@heavy(\s|$)/g, ' '); 
    el.chatInput.value = "@enhance " + value.replace(/^\s+/, "");
  }
  el.chatInput.focus();
  autoResize();
  syncChips();
}

function syncChips() {
  const value = el.chatInput.value;
  el.btnHeavy.classList.toggle("active", /(^|\s)@heavy(\s|$)/.test(value));
  if (el.btnEnhance) {
    el.btnEnhance.classList.toggle("active", /(^|\s)@enhance(\s|$)/.test(value));
  }
}

// ============================================================
// LISTENERS GERAIS E INICIALIZAÇÃO
// ============================================================

el.btnNewChat.addEventListener("click", createChat);
el.btnHeavy.addEventListener("click", insertHeavy);
if (el.btnEnhance) el.btnEnhance.addEventListener("click", insertEnhance);

// Restauração do Evento Input e Enter
el.chatInput.addEventListener("input", () => {
  autoResize();
  syncChips();
});

el.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    el.chatForm.requestSubmit();
  }
});

el.chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = el.chatInput.value;
  el.chatInput.value = "";
  autoResize();
  syncChips();
  sendMessage(text);
});

el.btnToggleBatch.addEventListener("click", () => el.batchPanel.classList.toggle("hidden"));
el.btnSendBatch.addEventListener("click", sendBatch);
el.sidebarToggle.addEventListener("click", toggleSidebar);

el.btnToggleTasks.addEventListener("click", async () => {
  el.tasksPanel.classList.toggle("hidden");
  const chat = state.chats.find((c) => c.id === state.activeId);
  if (!el.tasksPanel.classList.contains("hidden") && chat?.thread_id) {
    await loadTasks(chat.thread_id);
  }
});
el.btnExecuteTasks.addEventListener("click", executePendingTasks);
el.btnAddWorkspace.addEventListener("click", addWorkspace);
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
    
    const payload = { title, description, files, priority: "medium", status: "pending" };
    
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

// Delegar cliques de edição e exclusão dentro da lista de tasks
document.addEventListener('click', (event) => {
  const btnEdit = event.target.closest('.btn-edit-task');
  if (btnEdit) {
    const taskId = parseInt(btnEdit.getAttribute('data-task-id'));
    const task = state.currentTasks.find(t => t.id === taskId);
    if (task) openTaskModal(task);
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
loadChats();
loadWorkspaces();
autoResize();
syncChips();
startPolling();
// ============================================================
// LÓGICA DO MODAL DE IMPORTAÇÃO DE TAREFAS
// ============================================================

el.btnImportTasks.addEventListener('click', () => {
  // Limpa o textarea antes de abrir o modal
  el.inputImportJson.value = '';
  // Abre o modal
  el.importTasksModal.showModal();
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
    const chat = state.chats.find(c => c.thread_id === state.activeId);
    
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
      alert('Erro ao importar tarefas. Verifique o console para mais detalhes.');
      console.error('Erro na importação:', response);
    }
  } catch (error) {
    alert('Erro ao fazer parse do JSON. Verifique se o formato está correto.');
    console.error('Erro de parsing:', error);
  }
});