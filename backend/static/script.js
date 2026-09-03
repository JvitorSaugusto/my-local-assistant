/* ============================================================
   Assistente IA Local — cliente
   Desktop + Mobile
   ============================================================ */

const API = {
  chats: "/api/chats/",
  chat: (id) => `/api/chats/${id}`,
  messages: (thread_id) => `/api/ai/${thread_id}/messages`,
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
  btnEnhance: document.getElementById("btn-enhance"), // <-- NOVO BOTÃO

  btnToggleBatch: document.getElementById("btn-toggle-batch"),
  batchPanel: document.getElementById("batch-panel"),
  batchInput: document.getElementById("batch-input"),
  btnSendBatch: document.getElementById("btn-send-batch"),
  batchStatus: document.getElementById("batch-status"),
};


// ============================================================
// ÍCONES SVG
// ============================================================

const ICON = {
  bubble: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.6A8.5 8.5 0 0 1 4 11.5 8.38 8.38 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5Z"/>
    </svg>
  `,

  trash: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M3 6h18"/>
      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/>
      <path d="M18 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>
    </svg>
  `,

  pencil: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 20h9"/>
      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>
    </svg>
  `,

  user: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
      <circle cx="12" cy="7" r="4"/>
    </svg>
  `,

  bot: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="4" y="8" width="16" height="12" rx="3"/>
      <path d="M12 8V4"/>
      <path d="M8 2h8"/>
      <circle cx="9" cy="14" r="1"/>
      <circle cx="15" cy="14" r="1"/>
    </svg>
  `,

  copy: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="12" height="12" rx="2"/>
      <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
    </svg>
  `,

  check: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M20 6 9 17l-5-5"/>
    </svg>
  `,
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
};


// ============================================================
// MARKDOWN
// ============================================================

if (typeof marked === "undefined") {
  console.error("[Markdown] marked.js não foi carregado.");
}

if (typeof DOMPurify === "undefined") {
  console.error("[Markdown] DOMPurify não foi carregado.");
}

if (typeof marked !== "undefined") {
  marked.use({
    gfm: true,
    breaks: true,
  });
}

function escapeHtml(str = "") {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderContent(text = "") {
  const source = String(text);

  if (typeof marked === "undefined") {
    return `<p>${escapeHtml(source)}</p>`;
  }

  const html = marked.parse(source);

  if (typeof DOMPurify === "undefined") {
    return html;
  }

  return DOMPurify.sanitize(html, {
    ADD_ATTR: [
      "class",
      "target",
      "rel",
    ],
  });
}

function enhanceCodeBlocks(container) {
  if (typeof hljs === "undefined") {
    console.warn("[Highlight] highlight.js não foi carregado.");
    return;
  }

  const blocks = container.querySelectorAll("pre code");

  blocks.forEach((block) => {
    if (!block.dataset.highlighted) {
      hljs.highlightElement(block);
      block.dataset.highlighted = "true";
    }

    const pre = block.parentElement;

    if (!pre || pre.querySelector(".code-copy")) {
      return;
    }

    const btn = document.createElement("button");

    btn.type = "button";
    btn.className = "code-copy";
    btn.title = "Copiar código";
    btn.setAttribute("aria-label", "Copiar código");
    btn.innerHTML = ICON.copy;

    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(
          block.textContent || ""
        );
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
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!res.ok) {
    let detail = "";
    try {
      const errorData = await res.json();
      detail = errorData?.detail || errorData?.message || "";
    } catch {
      // resposta não era JSON
    }
    throw new Error(
      detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status}`
    );
  }

  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

function setSidebarMsg(msg = "", isError = false) {
  el.sidebarMsg.textContent = msg;
  el.sidebarMsg.style.color = isError ? "var(--danger)" : "var(--faint)";
}


// ============================================================
// MOBILE SIDEBAR
// ============================================================

function isMobile() {
  return window.matchMedia("(max-width: 780px)").matches;
}

function openSidebar() {
  el.sidebar.classList.add("open");
  el.sidebarToggle.setAttribute("aria-expanded", "true");
}

function closeSidebar() {
  el.sidebar.classList.remove("open");
  el.sidebarToggle.setAttribute("aria-expanded", "false");
}

function toggleSidebar() {
  if (el.sidebar.classList.contains("open")) {
    closeSidebar();
  } else {
    openSidebar();
  }
}

window.addEventListener("resize", () => {
  if (!isMobile()) {
    closeSidebar();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && isMobile() && el.sidebar.classList.contains("open")) {
    closeSidebar();
  }
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
    console.error("[Chats] loadChats:", err);
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
      <span class="chat-item-title">
        ${escapeHtml(chat.title || "Nova conversa")}
      </span>
      <span class="chat-edit" title="Editar título" role="button" aria-label="Editar título">
        ${ICON.pencil}
      </span>
      <span class="chat-del" title="Excluir" role="button" aria-label="Excluir conversa">
        ${ICON.trash}
      </span>
    `;

    /* --- clique no chat (exceto nos botões) --- */
    li.addEventListener("click", (event) => {
      if (event.target.closest(".chat-del") || event.target.closest(".chat-edit")) return;
      openChat(chat.id);
    });

    /* --- botão de excluir --- */
    const deleteButton = li.querySelector(".chat-del");
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteChat(chat.id);
    });

    /* --- botão de editar --- */
    const editButton = li.querySelector(".chat-edit");
    editButton.addEventListener("click", (event) => {
      event.stopPropagation();          // evita o clique no li
      editChat(chat.id, chat.title);    // passamos o título atual
    });

    el.chatList.appendChild(li);
  });
}



// ============================================================
// CRIAR CHAT
// ============================================================

async function createChat() {
  try {
    const chat = await api(API.chats, {
      method: "POST",
      body: JSON.stringify({ title: "Nova conversa" }),
    });

    if (chat?.id != null) {
      state.chats.unshift(chat);
      renderChatList();
      await openChat(chat.id);
    } else {
      await loadChats();
    }
  } catch (err) {
    console.error("[Chats] createChat:", err);
    setSidebarMsg("Falha ao criar conversa.", true);
  }
}


// ============================================================
// EXCLUIR CHAT
// ============================================================

async function deleteChat(id) {
  try {
    await api(API.chat(id), { method: "DELETE" });
  } catch (err) {
    console.error("[Chats] deleteChat:", err);
  }

  state.chats = state.chats.filter((chat) => chat.id !== id);

  if (state.activeId === id) {
    state.activeId = null;
    showWelcome();
  }
  renderChatList();
}

// ============================================================
// EDITAR CHAT
// ============================================================

async function editChat(id, oldTitle) {
  // 1️⃣ Pergunta ao usuário o novo título
  const newTitle = prompt("Novo título", oldTitle);

  // Se o usuário cancelou ou não digitou nada, abortamos
  if (newTitle === null || newTitle.trim() === "") return;

  try {
    // 2️⃣ Envia o PUT com o corpo correto
    const res = await fetch(API.chat(id), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle.trim() })
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    // 3️⃣ Atualiza o estado local (sem remover o chat)
    const chat = state.chats.find(c => c.id === id);
    if (chat) chat.title = newTitle.trim();

    // 4️⃣ Se o chat estiver ativo, atualiza o título na tela principal
    if (state.activeId === id) {
      // supondo que exista um elemento que exibe o título do chat ativo
      const titleEl = document.querySelector(".chat-header-title");
      if (titleEl) titleEl.textContent = newTitle.trim();
    }

    // 5️⃣ Re‑renderiza a lista
    renderChatList();

  } catch (err) {
    console.error("[Chats] editChat:", err);
    alert("Não foi possível atualizar o título. Tente novamente.");
  }
}


// ============================================================
// ABRIR CHAT
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

  try {
    const data = await api(API.messages(chat.thread_id));
    if (state.activeId !== requestChatId) return;

    const messages = data?.messages ?? [];

    messages.forEach((message) => {
      appendMessage(message.role, message.content, message.model);
    });

    // Bate a meta ao abrir o chat
    const aiCount = messages.filter(m => m.role === "assistant").length;
    const target = state.expectedAiCount[requestChatId];
    if (target && aiCount >= target) {
      state.pendingChats.delete(requestChatId);
      state.expectedAiCount[requestChatId] = 0;
    }

    if (state.pendingChats.has(requestChatId)) {
      appendTyping();
    }

    scrollToBottom();
  } catch (err) {
    console.error("[Chats] openChat:", err);
    if (state.activeId === requestChatId) {
      appendMessage("assistant", "Não foi possível carregar o histórico.");
    }
  }

  if (state.activeId === requestChatId && !isMobile()) {
    el.chatInput.focus();
  }
}


// ============================================================
// WELCOME
// ============================================================

function showWelcome() {
  el.chatView.classList.add("hidden");
  el.welcome.classList.remove("hidden");
}


// ============================================================
// MENSAGENS
// ============================================================

function appendMessage(role, content, modelName = null) {
  const isUser = role === "user";
  const wrap = document.createElement("div");

  wrap.className = `msg ${isUser ? "user" : "assistant"}`;
  let roleName = isUser ? "Você" : "Assistente";

  if (!isUser && modelName) {
    roleName = `Assistente (${modelName})`;
  }

  const renderedContent = isUser ? escapeHtml(content) : renderContent(content);

  wrap.innerHTML = `
    <div class="msg-avatar">
      ${isUser ? ICON.user : ICON.bot}
    </div>
    <div class="msg-body">
      <div class="msg-role">${escapeHtml(roleName)}</div>
      <div class="msg-content">${renderedContent}</div>
      ${
        !isUser
          ? `
            <button class="msg-raw-toggle" type="button">
              Ver formato puro
            </button>
            <pre class="msg-raw hidden">${escapeHtml(content)}</pre>
          `
          : ""
      }
    </div>
  `;

  if (!isUser) {
    const toggle = wrap.querySelector(".msg-raw-toggle");
    const raw = wrap.querySelector(".msg-raw");

    toggle.addEventListener("click", () => {
      const hidden = raw.classList.toggle("hidden");
      toggle.textContent = hidden ? "Ver formato puro" : "Ocultar formato puro";
    });
  }

  el.messages.appendChild(wrap);

  if (!isUser) enhanceCodeBlocks(wrap);

  return wrap;
}


// ============================================================
// TYPING
// ============================================================

function appendTyping() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  wrap.dataset.typing = "1";

  wrap.innerHTML = `
    <div class="msg-avatar">${ICON.bot}</div>
    <div class="msg-body">
      <div class="msg-role">Assistente</div>
      <div class="typing">
        <span></span><span></span><span></span>
      </div>
    </div>
  `;

  el.messages.appendChild(wrap);
  scrollToBottom();
  return wrap;
}


// ============================================================
// SCROLL
// ============================================================

function scrollToBottom() {
  requestAnimationFrame(() => {
    el.messages.scrollTop = el.messages.scrollHeight;
  });
}


// ============================================================
// ENVIAR MENSAGEM
// ============================================================

async function sendMessage(text) {
  if (!text.trim() || state.sending) return;

  if (state.activeId == null) {
    await createChat();
    if (state.activeId == null) return;
  }

  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat) return;

  const requestChatId = chat.id;
  const requestThreadId = chat.thread_id;
  state.sending = true;

  state.pendingChats.add(requestChatId);

  appendMessage("user", text);
  scrollToBottom();
  const typing = appendTyping();

  try {
    const data = await api(API.send, {
      method: "POST",
      body: JSON.stringify({
        thread_id: requestThreadId,
        message: text,
      }),
    });

    const reply = data?.content ?? data?.message ?? "(sem resposta)";
    const modelName = data?.name ?? data?.model ?? null;

    if (state.activeId !== requestChatId) return;

    const typingEl = el.messages.querySelector('[data-typing="1"]');
    if (typingEl) typingEl.remove();
    
    appendMessage("assistant", reply, modelName);

  } catch (err) {
    console.error("[Mensagem] sendMessage:", err);
    if (state.activeId === requestChatId) {
      typing.remove();
      appendMessage("assistant", "Erro ao contatar o servidor.");
    }
  } finally {
    state.sending = false;
    
    if (!state.expectedAiCount[requestChatId]) {
      state.pendingChats.delete(requestChatId);
    }
    if (state.activeId === requestChatId) {
      scrollToBottom();
      if (!isMobile()) el.chatInput.focus();
    }
  }
}


// ============================================================
// FILA CELERY
// ============================================================

async function sendBatch() {
  const raw = el.batchInput.value.trim();
  if (!raw) return;

  const tasks = raw
    .split(/\n\s*\n/)
    .map((task) => task.trim())
    .filter(Boolean);

  if (!tasks.length) return;

  if (state.activeId == null) {
    await createChat();
    if (state.activeId == null) return;
  }

  const chat = state.chats.find((item) => item.id === state.activeId);
  if (!chat) return;

  el.batchStatus.textContent = "Enviando...";

  // 1️⃣ ATUALIZAÇÃO OTIMISTA: Mostra as tarefas na tela
  tasks.forEach(task => {
    appendMessage("user", task);
  });
  
  // 2️⃣ Define o ALVO de respostas que queremos alcançar
  const currentAiCount = el.messages.querySelectorAll('.msg.assistant:not([data-typing="1"])').length;
  const expected = state.expectedAiCount[chat.id] || currentAiCount;
  state.expectedAiCount[chat.id] = expected + tasks.length; // Soma as novas tarefas ao alvo!

  // 3️⃣ Coloca a bolinha e avisa o estado
  appendTyping();
  scrollToBottom();
  state.pendingChats.add(chat.id);

  try {
    const data = await api(API.batch, {
      method: "POST",
      body: JSON.stringify({
        thread_id: chat.thread_id,
        prompts: tasks,
      }),
    });

    el.batchStatus.textContent = data?.message || "Enviado para a fila.";
    el.batchInput.value = "";
    
  } catch (err) {
    console.error("[Batch] sendBatch:", err);
    el.batchStatus.textContent = "Falha ao enfileirar.";
    
    // Se der erro de conexão, removemos a bolinha e tiramos da lista de espera
    if (state.activeId === chat.id) {
      const typingEl = el.messages.querySelector('[data-typing="1"]');
      if (typingEl) typingEl.remove();
    }
    state.pendingChats.delete(chat.id);
  }
}


// ============================================================
// POLLING (ATUALIZAÇÃO EM BACKGROUND PARA O CELERY)
// ============================================================

function startPolling() {
  if (state.pollingInterval) clearInterval(state.pollingInterval);
  
  state.pollingInterval = setInterval(async () => {
    if (!state.activeId || state.sending) return;

    const chat = state.chats.find(c => c.id === state.activeId);
    if (!chat || !chat.thread_id) return;

    try {
      const data = await api(API.messages(chat.thread_id));
      if (state.activeId !== chat.id) return;

      const msgs = data?.messages ?? [];
      const visibleMsgs = el.messages.querySelectorAll('.msg:not([data-typing="1"])');
      
      // --- A MÁGICA NOVA: Bateu a meta de respostas? ---
      const aiCount = msgs.filter(m => m.role === "assistant").length;
      const target = state.expectedAiCount[chat.id];

      if (target && aiCount >= target) {
        state.pendingChats.delete(chat.id);
        state.expectedAiCount[chat.id] = 0; // Fila concluída, zera o alvo!
      }
      // -------------------------------------------------

      if (msgs.length > visibleMsgs.length) {
        el.messages.innerHTML = "";
        msgs.forEach(m => appendMessage(m.role, m.content, m.model));
        
        if (state.pendingChats.has(chat.id)) {
          appendTyping(); // Mantém a bolinha se não bateu a meta
        }
        
        scrollToBottom();
      } else {
        // Se a tela não teve mensagens novas, mas a meta já foi batida
        if (!state.pendingChats.has(chat.id)) {
          const typingEl = el.messages.querySelector('[data-typing="1"]');
          if (typingEl) typingEl.remove();
        }
      }
    } catch (e) {
    }
  }, 3000); 
}

// ============================================================
// INPUT & TAGS (Lógica de Exclusividade)
// ============================================================

function autoResize() {
  el.chatInput.style.height = "auto";
  el.chatInput.style.height = Math.min(el.chatInput.scrollHeight, 200) + "px";
}

function insertHeavy() {
  let value = el.chatInput.value;
  
  if (!/(^|\s)@heavy(\s|$)/.test(value)) {
    value = value.replace(/(^|\s)@enhance(\s|$)/g, ' '); // Remove enhance
    el.chatInput.value = "@heavy " + value.replace(/^\s+/, "");
  }

  el.chatInput.focus();
  autoResize();
  syncChips();
}

function insertEnhance() {
  let value = el.chatInput.value;
  
  if (!/(^|\s)@enhance(\s|$)/.test(value)) {
    value = value.replace(/(^|\s)@heavy(\s|$)/g, ' '); // Remove heavy
    el.chatInput.value = "@enhance " + value.replace(/^\s+/, "");
  }

  el.chatInput.focus();
  autoResize();
  syncChips();
}

function syncChips() {
  const value = el.chatInput.value;
  const hasHeavy = /(^|\s)@heavy(\s|$)/.test(value);
  const hasEnhance = /(^|\s)@enhance(\s|$)/.test(value);

  el.btnHeavy.classList.toggle("active", hasHeavy);
  if (el.btnEnhance) {
    el.btnEnhance.classList.toggle("active", hasEnhance);
  }
}


// ============================================================
// LISTENERS
// ============================================================

el.btnNewChat.addEventListener("click", createChat);
el.btnHeavy.addEventListener("click", insertHeavy);

if (el.btnEnhance) {
  el.btnEnhance.addEventListener("click", insertEnhance);
}

el.chatInput.addEventListener("input", () => {
  autoResize();
  syncChips();
});

el.chatInput.addEventListener("keydown", (event) => {
  if (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.isComposing &&
    event.keyCode !== 229
  ) {
    event.preventDefault();
    el.chatForm.requestSubmit();
  }
});

el.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();

  const text = el.chatInput.value;
  el.chatInput.value = "";

  autoResize();
  syncChips();

  sendMessage(text);
});

el.btnToggleBatch.addEventListener("click", () => {
  el.batchPanel.classList.toggle("hidden");
});

el.btnSendBatch.addEventListener("click", sendBatch);
el.sidebarToggle.addEventListener("click", toggleSidebar);


// ============================================================
// INICIALIZAÇÃO
// ============================================================

loadChats();
autoResize();
syncChips();
startPolling();