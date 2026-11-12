/* tips.js - caixa "Dicas" do chat: exemplos de pedidos, comandos e atalhos.

   Usa o botão #btn-tips e o painel #tips-menu do index.html. "Usar" coloca o exemplo na caixa de mensagem
   (e seleciona o primeiro trecho entre < > para você trocar); "Copiar" copia o texto.
   Para adicionar ou editar dicas, mexa só na lista GROUPS abaixo. */
(function () {
  "use strict";

  var GROUPS = [
    {
      title: "Conversa e código (modo Auto)",
      tips: [
        { kind: "insert", title: "Dúvida normal", when: "Pergunta geral, sem precisar do projeto.",
          text: "Explique a diferença entre threads e asyncio em Python e dê um exemplo curto de cada." },
        { kind: "insert", title: "Código pontual", when: "Uma função, um bug ou um erro isolado. Cole o erro completo.",
          text: "Escreva uma função em Python que valide um CPF e inclua testes com unittest." },
        { kind: "insert", title: "Corrigir um erro", when: "Cole o traceback e o código envolvido.",
          text: "Corrija este erro e explique a causa em 2 linhas:\n<cole o traceback e o código aqui>" },
        { kind: "insert", title: "Criar uma nota", when: "Documentação para consultar depois. Use \"crie uma nota\" ou \"documente\".",
          text: "Crie uma nota sobre injeção de dependência no FastAPI para eu consultar depois." },
        { kind: "insert", title: "Refinar o pedido (@enhance)", when: "Reescreve um pedido informal como instrução clara e segue com ela.",
          text: "@enhance <seu pedido do jeito que vier na cabeça>" }
      ]
    },
    {
      title: "Ler o repositório (escolha o projeto na aba Projeto)",
      tips: [
        { kind: "insert", title: "Entender um fluxo (@heavy)", when: "Análise profunda: o assistente lê os arquivos reais antes de responder.",
          text: "@heavy Explique como uma mensagem enviada para /api/ai/ percorre o grafo até a resposta. Cite os arquivos e as funções de cada etapa." },
        { kind: "insert", title: "Achar a causa de um bug", when: "Quanto mais exato o erro e os nomes de arquivos, melhor.",
          text: "@heavy Erro: <cole a mensagem exata>. Ache a causa no código (arquivo e função), diga se há outras causas possíveis e proponha a menor correção." },
        { kind: "insert", title: "Mapa da estrutura", when: "Pedidos de \"mapa\" ou \"estrutura\" recebem a árvore visual 📁/📄 gerada por código.",
          text: "@heavy Mostre o mapa da pasta <nome da pasta> e explique em 3 linhas como ela está organizada." },
        { kind: "insert", title: "Gerar tasks de uma funcionalidade", when: "Funcionalidade inteira vira de 6 a 10 tasks pequenas e numeradas [1/N]. Tasks com arquivo inexistente são descartadas.",
          text: "@heavy Gere tasks para implementar <funcionalidade> neste projeto. Use só arquivos e pastas que existem." },
        { kind: "info", title: "Perguntas de acompanhamento", when: "Pode continuar com perguntas curtas (\"e se for no Docker?\"): o assistente considera as últimas mensagens da conversa." }
      ]
    },
    {
      title: "Tarefas",
      tips: [
        { kind: "insert", title: "Executar tasks", when: "Roda as tasks pelos números (#) do painel, em ordem. Também dá para marcar no painel e usar Executar.",
          text: "@generate 12 13 14" },
        { kind: "info", title: "Botão Planejar", when: "Task sem passos? Preencha \"Arquivos\" com o que pode ser editado e descreva arquivo, comportamento atual e desejado. O modelo local indica as linhas, o sistema monta e valida os passos." },
        { kind: "info", title: "Importar o JSON do Claude", when: "No painel de tarefas: Importar JSON. Antes, valide na página Pacote (passo 2). Dentro do Importar JSON, \"Copiar prompt\" traz o formato das microtasks." }
      ]
    },
    {
      title: "Economizar tokens com Claude/GPT",
      tips: [
        { kind: "link", title: "Gerar o pacote para a IA externa", href: "/static/pack.html", linkLabel: "Abrir",
          when: "Monta um .md com o problema, o resumo do projeto e só o código relevante, dentro de um orçamento de tokens. Na 1ª vez deixe \"Arquivos\" vazio, veja o que foi escolhido e refaça com a lista certa." },
        { kind: "copy", title: "Exemplo de problema (para a página Pacote)", when: "Descreva com arquivo, função, erro exato e o resultado que você quer.",
          text: "providers.py: OllamaSummarizer._call devolve 404 sem mostrar o motivo. Quero exibir a mensagem do Ollama e uma dica de 'ollama pull'." },
        { kind: "link", title: "Abrir um chat novo no Claude", href: "/static/pack.html", linkLabel: "Gerar primer",
          when: "Use \"Só o primer do projeto\" e cole na 1ª mensagem: contexto fiel em poucos tokens, sem reenviar o repositório." },
        { kind: "link", title: "Validar o JSON antes de executar", href: "/static/pack.html", linkLabel: "Abrir",
          when: "Simula as tasks do Claude numa cópia. Se falhar, mande só o relatório curto de volta para ele." }
      ]
    },
    {
      title: "Projeto, RAG e anexos",
      tips: [
        { kind: "info", title: "Escolher o projeto", when: "Aba Projeto → Procurar pastas no servidor → Usar esta pasta. A lista de projetos é separada por aparelho (PC e celular)." },
        { kind: "info", title: "Fixar projeto e fontes na conversa (📌)", when: "No topo da conversa, o 📌 guarda o projeto e as fontes atuais nela. Ao reabrir a conversa, em qualquer aparelho, eles voltam sozinhos. Com o 📌 ativo, trocar de projeto ou de fontes atualiza o que está fixado; toque de novo para soltar." },
        { kind: "link", title: "Indexar o projeto (RAG)", href: "/static/rag.html", linkLabel: "Abrir",
          when: "Indexar melhora a busca do pacote e do Heavy. Reindexe depois de grandes mudanças; \"Testar resumidor\" mostra se a IA de resumos está funcionando." },
        { kind: "insert", title: "Anexar arquivos (📎)", when: "Aceita .md, .txt, .py, .json, .csv, .pdf e .docx até 10 MB. Diga o que fazer com o arquivo.",
          text: "Resuma o arquivo anexado em 10 linhas e liste as decisões tomadas." },
        { kind: "info", title: "Alerta de fim de resposta (🔔)", when: "O botão 🔔 no canto avisa com som e notificação quando a resposta termina, se a aba estiver em segundo plano. A notificação do navegador exige HTTPS ou localhost." }
      ]
    }
  ];

  var btn = document.getElementById("btn-tips");
  var menu = document.getElementById("tips-menu");
  if (!btn || !menu) return;

  var body = null;
  var search = null;
  var toastEl = null;
  var toastTimer = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function copyText(text) {
    var done = function () { return true; };
    try {
      if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text).then(done, function () { return legacyCopy(text); });
      }
    } catch (e) { /* cai no plano B */ }
    return Promise.resolve(legacyCopy(text));
  }

  // Plano B: em HTTP puro (IP do Tailscale) o navegador não libera navigator.clipboard.
  function legacyCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.style.cssText = "position:fixed;top:0;left:0;opacity:0;";
    document.body.appendChild(area);
    area.focus();
    area.select();
    var ok = false;
    try { area.setSelectionRange(0, text.length); ok = document.execCommand("copy"); } catch (e) { ok = false; }
    area.remove();
    return ok;
  }

  function toast(text) {
    if (!toastEl) return;
    toastEl.textContent = text;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.textContent = ""; }, 2600);
  }

  function tipHtml(tip, gi, ti) {
    var actions = "";
    var ref = ' data-g="' + gi + '" data-t="' + ti + '"';
    if (tip.kind === "insert") {
      actions = '<button type="button" class="tip-btn primary" data-act="use"' + ref + ">Usar</button>" +
        '<button type="button" class="tip-btn" data-act="copy"' + ref + ">Copiar</button>";
    } else if (tip.kind === "copy") {
      actions = '<button type="button" class="tip-btn primary" data-act="copy"' + ref + ">Copiar</button>";
    } else if (tip.kind === "link") {
      actions = '<a class="tip-btn primary" href="' + esc(tip.href) + '" target="_blank" rel="noopener">' + esc(tip.linkLabel || "Abrir") + "</a>";
    }
    return '<div class="tip"><div class="tip-title">' + esc(tip.title) + "</div>" +
      (tip.when ? '<div class="tip-when">' + esc(tip.when) + "</div>" : "") +
      (tip.text ? '<pre class="tip-text">' + esc(tip.text) + "</pre>" : "") +
      (actions ? '<div class="tip-actions">' + actions + "</div>" : "") + "</div>";
  }

  function render(query) {
    var q = String(query || "").trim().toLowerCase();
    var html = "";
    GROUPS.forEach(function (group, gi) {
      var items = [];
      group.tips.forEach(function (tip, ti) {
        var hay = (tip.title + " " + (tip.when || "") + " " + (tip.text || "")).toLowerCase();
        if (!q || hay.indexOf(q) !== -1) items.push(tipHtml(tip, gi, ti));
      });
      if (!items.length) return;
      html += '<details class="tips-group"' + (q || gi === 0 ? " open" : "") + "><summary>" + esc(group.title) +
        ' <span class="tips-count">' + items.length + "</span></summary>" + items.join("") + "</details>";
    });
    body.innerHTML = html || '<div class="tips-empty">Nada encontrado. Tente "tasks", "mapa" ou "erro".</div>';
  }

  function build() {
    menu.innerHTML =
      '<div class="tips-head"><b>Dicas de pedidos</b><small>Toque em <b>Usar</b> para colocar o exemplo na caixa de mensagem e troque o que estiver entre &lt; &gt;.</small></div>' +
      '<input type="search" class="tips-search" placeholder="Buscar (ex.: tasks, mapa, bug)" aria-label="Buscar dicas" autocomplete="off">' +
      '<div class="tips-body"></div><div class="tips-toast" role="status"></div>' +
      '<div class="tips-foot"><a href="/static/pack.html" target="_blank" rel="noopener">Pacote para IA externa</a>' +
      '<a href="/static/rag.html" target="_blank" rel="noopener">Indexação (RAG)</a></div>';
    body = menu.querySelector(".tips-body");
    search = menu.querySelector(".tips-search");
    toastEl = menu.querySelector(".tips-toast");
    search.addEventListener("input", function () { render(search.value); });
    render("");
  }

  function isOpen() { return !menu.classList.contains("hidden"); }

  function open() {
    if (!body) build();
    search.value = "";
    render("");
    menu.classList.remove("hidden");
    btn.setAttribute("aria-expanded", "true");
  }

  function close() {
    menu.classList.add("hidden");
    btn.setAttribute("aria-expanded", "false");
  }

  function useTip(text) {
    var input = document.getElementById("chat-input");
    if (!input || input.offsetParent === null) {
      Promise.resolve(copyText(text)).then(function (ok) {
        toast(ok ? "Copiado. Abra uma conversa e cole." : "Não consegui copiar.");
      });
      return;
    }
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
    var m = /<[^>\n]+>/.exec(text);
    try {
      if (m) input.setSelectionRange(m.index, m.index + m[0].length);
      else input.setSelectionRange(text.length, text.length);
    } catch (e) { /* alguns navegadores móveis não permitem */ }
    close();
  }

  function tipOf(el) {
    var g = GROUPS[Number(el.getAttribute("data-g"))];
    return g ? g.tips[Number(el.getAttribute("data-t"))] : null;
  }

  menu.addEventListener("click", function (event) {
    var button = event.target.closest("[data-act]");
    if (!button) return;
    var tip = tipOf(button);
    if (!tip || !tip.text) return;
    if (button.getAttribute("data-act") === "use") useTip(tip.text);
    else Promise.resolve(copyText(tip.text)).then(function (ok) { toast(ok ? "Copiado ✓" : "Não consegui copiar."); });
  });

  btn.addEventListener("click", function () { if (isOpen()) close(); else open(); });
  document.addEventListener("click", function (event) {
    if (isOpen() && !menu.contains(event.target) && !btn.contains(event.target)) close();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && isOpen()) { close(); btn.focus(); }
  });
})();
