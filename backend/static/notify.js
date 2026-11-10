/* notify.js - avisa quando a IA termina de responder.

   Carregado pela página (<script src="/static/notify.js"></script>). Não depende de nenhum outro arquivo:
   observa o fetch da conversa (POST /api/ai/) e, quando a resposta chega, dispara
   som, notificação do navegador e título da aba piscando.

   Por padrão só avisa se você NÃO está olhando a aba (aba em segundo plano ou janela sem foco).
   O botão 🔔 no canto da tela abre as opções e tem "Testar alerta". */
(function () {
  "use strict";
  if (window.aiNotify) return;

  var KEY = "aiNotify.v1";
  var DEFAULTS = { sound: true, desktop: true, title: true, always: false };
  var settings = load();
  var audioCtx = null;
  var blinkTimer = null;
  var originalTitle = null;

  function load() {
    try {
      return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(KEY) || "{}"));
    } catch (e) {
      return Object.assign({}, DEFAULTS);
    }
  }

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch (e) { /* sem storage: segue sem salvar */ }
  }

  function away() {
    return document.hidden || !document.hasFocus();
  }

  // ---- som ----------------------------------------------------------------
  function ensureAudio() {
    try {
      if (!audioCtx) {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return null;
        audioCtx = new Ctx();
      }
      if (audioCtx.state === "suspended") audioCtx.resume();
      return audioCtx;
    } catch (e) {
      return null;
    }
  }

  // O navegador só libera áudio depois de um gesto do usuário: destrava no primeiro clique/tecla.
  ["pointerdown", "keydown"].forEach(function (name) {
    window.addEventListener(name, function () { ensureAudio(); }, { once: true, passive: true });
  });

  function beep() {
    var ctx = ensureAudio();
    if (!ctx) return;
    var now = ctx.currentTime;
    [[880, 0], [1320, 0.16]].forEach(function (note) {
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      var t = now + note[1];
      osc.type = "sine";
      osc.frequency.value = note[0];
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.25);
    });
  }

  // ---- notificação do navegador e título da aba ---------------------------
  function showDesktop(title, body) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    try {
      var n = new Notification(title, { body: body, tag: "ai-done" });
      n.onclick = function () { window.focus(); n.close(); };
      setTimeout(function () { n.close(); }, 8000);
    } catch (e) { /* alguns navegadores móveis não permitem: ignora */ }
  }

  function stopBlink() {
    if (blinkTimer) {
      clearInterval(blinkTimer);
      blinkTimer = null;
      if (originalTitle !== null) document.title = originalTitle;
    }
  }

  function blinkTitle(text) {
    stopBlink();
    originalTitle = document.title;
    var on = false;
    blinkTimer = setInterval(function () {
      on = !on;
      document.title = on ? text : originalTitle;
    }, 1000);
  }

  document.addEventListener("visibilitychange", function () { if (!document.hidden) stopBlink(); });
  window.addEventListener("focus", stopBlink);

  // ---- API pública --------------------------------------------------------
  function done(opts) {
    opts = opts || {};
    var title = opts.title || "Resposta pronta";
    var body = opts.body || "";
    var isAway = away();
    if (!(opts.force || settings.always || isAway)) return false;
    if (settings.sound) beep();
    if (settings.desktop && (opts.force || isAway)) showDesktop("✅ " + title, body);
    if (settings.title && isAway) blinkTitle("✅ " + title);
    return true;
  }

  function preview(text) {
    return String(text || "")
      .replace(/```[\s\S]*?```/g, " [código] ")
      .replace(/[#*_`>|]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 140);
  }

  // ---- observa a resposta da conversa (POST /api/ai/) ----------------------
  function isChatUrl(url) {
    try {
      return /^\/api\/ai\/?$/.test(new URL(url, location.href).pathname);
    } catch (e) {
      return false;
    }
  }

  var originalFetch = window.fetch;
  if (typeof originalFetch === "function") {
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
      var promise = originalFetch.apply(this, arguments);
      if (method === "POST" && isChatUrl(url)) {
        promise.then(function (res) {
          if (!res.ok) return;
          res.clone().json().then(function (data) {
            if (!data || data.cancelled || typeof data.content !== "string") return;
            done({ title: data.name || "Resposta pronta", body: preview(data.content) });
          }).catch(function () { /* resposta não era JSON: ignora */ });
        }).catch(function () { /* erro de rede: o próprio front já trata */ });
      }
      return promise;
    };
  }

  // ---- botão 🔔 e painel de opções ----------------------------------------
  function row(label, key, onChange) {
    var wrap = document.createElement("label");
    wrap.style.cssText = "display:flex;align-items:center;gap:8px;margin:6px 0;cursor:pointer;";
    var input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!settings[key];
    input.addEventListener("change", function () {
      settings[key] = input.checked;
      save();
      if (onChange) onChange(input);
    });
    var text = document.createElement("span");
    text.textContent = label;
    wrap.appendChild(input);
    wrap.appendChild(text);
    return wrap;
  }

  function buildUI() {
    var box = document.createElement("div");
    box.id = "ai-notify";
    box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:9999;font:13px system-ui,sans-serif;";

    var button = document.createElement("button");
    button.type = "button";
    button.title = "Alertas de resposta";
    button.textContent = "🔔";
    button.style.cssText = "width:38px;height:38px;border-radius:50%;cursor:pointer;font-size:16px;" +
      "border:1px solid rgba(128,128,128,.45);background:var(--ai-notify-bg,#262626);color:var(--ai-notify-fg,#f0f0f0);";

    var panel = document.createElement("div");
    panel.style.cssText = "display:none;position:absolute;right:0;bottom:46px;min-width:250px;padding:10px 12px;" +
      "border-radius:10px;border:1px solid rgba(128,128,128,.45);box-shadow:0 6px 20px rgba(0,0,0,.35);" +
      "background:var(--ai-notify-bg,#262626);color:var(--ai-notify-fg,#f0f0f0);";

    var hint = document.createElement("div");
    hint.style.cssText = "margin-top:6px;font-size:12px;opacity:.75;";

    panel.appendChild(row("Som", "sound"));
    panel.appendChild(row("Notificação do navegador", "desktop", function (input) {
      if (!input.checked || !("Notification" in window)) return;
      if (Notification.permission === "default") {
        Notification.requestPermission().then(function (p) {
          if (p !== "granted") {
            hint.textContent = "Permissão negada: libere nas configurações do site.";
            input.checked = false;
            settings.desktop = false;
            save();
          }
        });
      } else if (Notification.permission === "denied") {
        hint.textContent = "Permissão negada: libere nas configurações do site.";
        input.checked = false;
        settings.desktop = false;
        save();
      }
    }));
    panel.appendChild(row("Piscar o título da aba", "title"));
    panel.appendChild(row("Avisar também com a aba aberta", "always"));

    var test = document.createElement("button");
    test.type = "button";
    test.textContent = "Testar alerta";
    test.style.cssText = "margin-top:6px;padding:4px 10px;cursor:pointer;";
    test.addEventListener("click", function () {
      ensureAudio();
      done({ force: true, title: "Teste de alerta", body: "É assim que você será avisado." });
    });
    panel.appendChild(test);
    panel.appendChild(hint);

    button.addEventListener("click", function () {
      panel.style.display = panel.style.display === "none" ? "block" : "none";
    });
    document.addEventListener("click", function (event) {
      if (!box.contains(event.target)) panel.style.display = "none";
    });

    box.appendChild(panel);
    box.appendChild(button);
    document.body.appendChild(box);
  }

  if (document.body) buildUI();
  else document.addEventListener("DOMContentLoaded", buildUI);

  window.aiNotify = {
    done: done,
    get: function () { return Object.assign({}, settings); },
    set: function (key, value) { settings[key] = value; save(); },
  };
})();
