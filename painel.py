"""Painel do Assistente (so biblioteca padrao).

Sobe API + workers SEM janelas, guarda os logs, separa "Atividade" (pensamentos, rotas,
respostas, tasks) de "Erros", e oferece botoes para reiniciar a API/workers.
Abre em http://localhost:8765  (porta: env PAINEL_PORT).
"""
import json, os, re, socket, subprocess, sys, threading, time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
PANEL_PORT = int(os.getenv("PAINEL_PORT", "8765"))
API_PORT = int(os.getenv("API_PORT", "8001"))
IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW

# ───────────────────────── classificação das linhas ─────────────────────────
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ACCESS = re.compile(r'"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) \S+ HTTP/[\d.]+" (\d{3})')
ERR = re.compile(
    r"Traceback \(most recent|\b(?:ERROR|CRITICAL|FATAL)\b|\w(?:Error|Exception)\b|\bError\b|FALHOU|❌|⚠️"
    r"|\bWARNING\b|raised unexpected|Errno|\bfalhou\b|marcada como falha",
    re.I,
)
ACT = re.compile(
    r"^\s*(?:={3,}|🔀|ℹ️|✅|📌|🧠|💭|⏸️)"
    r"|\[(?:ROUTER|EDGE|HEAVY|GENERATE|COMMIT|RAG|BUSCA|PARSER FALLBACK|DEBUG|painel)\]"
    r"|^\s*(?:TASKS GERADAS|TOOL CALLS|DOSSIÊ|GPT-OSS|Possui tool|Tamanho do rascunho)"
    r"|Task \S+\[[0-9a-f-]{36}\] (?:received|succeeded|raised|retry)"
    r"|Application startup complete|Uvicorn running|\bready\.$"
)
BLOCK_START = re.compile(r"^(?:CONTENT:|description:|\[DEBUG\] ===)")
BLOCK_END = re.compile(r"^(?:CONTENT LENGTH|TOOL_CALLS|metadata:|content:|length:|files:)")
TB_CONT = re.compile(r"^(?:\s|Traceback|During handling|The above exception)")


class Logs:
    def __init__(self):
        self.lock = threading.Lock()
        self.seq = 0
        self.kinds = {k: deque(maxlen=3000) for k in ("activity", "errors", "raw")}
        LOG_DIR.mkdir(exist_ok=True)
        self.files = {}
        for kind, name in (("activity", "atividade"), ("errors", "erros"), ("raw", "bruto")):
            p = LOG_DIR / f"{name}.log"
            if p.exists() and p.stat().st_size > 5_000_000:
                p.replace(LOG_DIR / f"{name}.old.log")
            self.files[kind] = open(p, "a", encoding="utf-8", buffering=1)

    def add(self, kind, src, text):
        t = time.strftime("%H:%M:%S")
        with self.lock:
            self.seq += 1
            self.kinds[kind].append({"id": self.seq, "t": t, "src": src, "text": text})
            try:
                self.files[kind].write(f"{time.strftime('%Y-%m-%d')} {t} [{src}] {text}\n")
            except Exception:  # noqa: BLE001
                pass

    def get(self, kind, after, limit=1500):
        with self.lock:
            items = [e for e in self.kinds[kind] if e["id"] > after]
        return items[-limit:]

    def clear(self, kind):
        with self.lock:
            self.kinds[kind].clear()


LOGS = Logs()


class Classifier:
    def __init__(self, src):
        self.src, self.in_tb, self.block = src, False, 0

    def feed(self, line):
        LOGS.add("raw", self.src, line[:2000])
        if not line.strip():
            return
        short = line[:500]
        if self.in_tb:
            if TB_CONT.match(line):
                return LOGS.add("errors", self.src, short)
            self.in_tb = False
            LOGS.add("errors", self.src, short)  # linha final: "XxxError: msg"
            return
        if line.startswith("Traceback (most recent"):
            self.in_tb = True
            return LOGS.add("errors", self.src, short)
        m = ACCESS.search(line)
        if m:
            if int(m.group(1)) >= 500:
                LOGS.add("errors", self.src, short)
            return
        is_act = bool(ACT.search(line))
        if BLOCK_START.match(line):
            self.block = 80
            is_act = True
        elif self.block and (BLOCK_END.match(line) or is_act):
            self.block = 0
        is_err = bool(ERR.search(line))
        if is_err:
            LOGS.add("errors", self.src, short)
        if is_act or (self.block and not is_err):
            LOGS.add("activity", self.src, short)
        if self.block:
            self.block -= 1


# ───────────────────────── processos ─────────────────────────
def _python():
    venv = ROOT / ".venv" / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")
    if venv.exists():
        return str(venv)
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def port_in_use(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Service:
    def __init__(self, name, label, cmd, group, port=None):
        self.name, self.label, self.cmd, self.group, self.port = name, label, cmd, group, port
        self.proc = None
        self.since = None
        self.stopping = False
        self.code = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running:
            return
        if self.port and port_in_use(self.port):
            LOGS.add("errors", self.name, f"[painel] porta {self.port} ocupada (processo antigo?). Feche-o e use Reiniciar.")
            return
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        kw = {"creationflags": NO_WINDOW} if IS_WIN else {"start_new_session": True}
        self.stopping, self.code = False, None
        self.proc = subprocess.Popen(
            self.cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw,
        )
        self.since = time.time()
        LOGS.add("activity", self.name, f"[painel] {self.label} iniciado (pid {self.proc.pid})")
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        cls = Classifier(self.name)
        for raw in iter(proc.stdout.readline, b""):
            cls.feed(ANSI.sub("", raw.decode("utf-8", "replace").rstrip("\r\n")))
        self.code = proc.wait()
        if self.stopping:
            LOGS.add("activity", self.name, f"[painel] {self.label} parado")
        else:
            LOGS.add("errors", self.name, f"[painel] {self.label} ENCERROU sozinho (código {self.code}). Veja a aba Erros/Bruto.")

    def stop(self):
        p = self.proc
        if not p or p.poll() is not None:
            return
        self.stopping = True
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        else:
            import signal
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()


def build_services():
    py = _python()
    celery = [py, "-m", "celery", "-A", "tasks", "worker", "--loglevel=info"]
    return [
        Service("api", "API", [py, "run_api.py", str(API_PORT), "0.0.0.0"], "api", API_PORT),
        Service("worker", "Worker", celery + ["--queues=celery", "--pool=threads", "--concurrency=4", "-n", "principal@localhost"], "workers"),
        Service("git", "Worker Git", celery + ["--queues=generate_sequential", "--pool=solo", "-n", "gitworker@localhost"], "workers"),
    ]


SERVICES = []
OPS = {"lock": threading.Lock(), "msg": ""}


def run_op(label, fn):
    if not OPS["lock"].acquire(blocking=False):
        return False

    def work():
        try:
            OPS["msg"] = label
            fn()
        except Exception as exc:  # noqa: BLE001
            LOGS.add("errors", "painel", f"[painel] falha em '{label}': {exc}")
        finally:
            OPS["msg"] = ""
            OPS["lock"].release()

    threading.Thread(target=work, daemon=True).start()
    return True


def restart(group):
    targets = [s for s in SERVICES if group == "all" or s.group == group]
    LOGS.add("activity", "painel", f"[painel] reiniciando: {', '.join(s.label for s in targets)}")
    for s in targets:
        s.stop()
    for s in targets:
        deadline = time.time() + 15
        while s.port and port_in_use(s.port) and time.time() < deadline:
            time.sleep(0.3)
    for s in targets:
        s.start()


def stop_all():
    for s in SERVICES:
        s.stop()


# ───────────────────────── servidor HTTP ─────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "Painel"

    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json; charset=utf-8", code=200):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False), code=code)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(HTML, "text/html; charset=utf-8")
        if u.path == "/api/logs":
            kind = q.get("kind", ["activity"])[0]
            if kind not in LOGS.kinds:
                return self._json({"error": "kind"}, 400)
            after = int(q.get("after", ["0"])[0] or 0)
            return self._json({"lines": LOGS.get(kind, after, 500 if after == 0 else 1500)})
        if u.path == "/api/status":
            return self._json({
                "busy": OPS["msg"],
                "api_port": API_PORT,
                "services": [
                    {"name": s.name, "label": s.label, "running": s.running,
                     "pid": s.proc.pid if s.proc else None, "since": s.since, "code": s.code}
                    for s in SERVICES
                ],
            })
        self._send("not found", "text/plain", 404)

    def do_POST(self):
        if self.headers.get("X-Painel") != "1":  # bloqueia POST vindo de outros sites
            return self._send("forbidden", "text/plain", 403)
        parts = urlparse(self.path).path.strip("/").split("/")
        if parts[:2] == ["api", "restart"] and len(parts) == 3 and parts[2] in ("api", "workers", "all"):
            ok = run_op(f"Reiniciando {parts[2]}…", lambda: restart(parts[2]))
            return self._json({"ok": ok})
        if parts[:2] == ["api", "clear"] and len(parts) == 3 and parts[2] in LOGS.kinds:
            LOGS.clear(parts[2])
            return self._json({"ok": True})
        if parts == ["api", "shutdown"]:
            def bye():
                stop_all()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            self._json({"ok": run_op("Encerrando…", bye)})
            return
        self._send("not found", "text/plain", 404)


HTML = r"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Painel do Assistente</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#14161a;--panel:#1c1f25;--line:#2b2f38;--fg:#d8dce3;--dim:#8a91a0;--acc:#7aa2ff;--err:#ff6b6b;--ok:#4cd08a;--warn:#f0b35a}
@media(prefers-color-scheme:light){:root{--bg:#f4f5f7;--panel:#fff;--line:#d9dce3;--fg:#1d2128;--dim:#68707f;--acc:#2f5fd0;--err:#c92a2a;--ok:#1f9d5b;--warn:#b7791f}}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;display:flex;flex-direction:column}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:10px 14px;background:var(--panel);border-bottom:1px solid var(--line)}
h1{font-size:15px;margin:0 8px 0 0}.pills{display:flex;gap:8px;flex-wrap:wrap}
.pill{display:flex;align-items:center;gap:6px;padding:3px 9px;border:1px solid var(--line);border-radius:99px;font-size:12px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--err)}.up .dot{background:var(--ok)}
.sp{flex:1}button,select,input{font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 10px}
button{cursor:pointer}button:hover:not(:disabled){border-color:var(--acc)}button:disabled{opacity:.5;cursor:default}
button.danger:hover:not(:disabled){border-color:var(--err)}a{color:var(--acc);text-decoration:none}
#busy{color:var(--warn);font-size:12px}
nav{display:flex;gap:4px;padding:8px 14px 0;align-items:center}
.tab{border-bottom:2px solid transparent;border-radius:6px 6px 0 0;border-color:transparent}
.tab.on{border-bottom-color:var(--acc);background:var(--panel)}
.badge{background:var(--err);color:#fff;border-radius:99px;padding:0 6px;font-size:11px;margin-left:4px}.badge:empty{display:none}
#filter{width:200px}label{color:var(--dim);font-size:12px;display:flex;gap:4px;align-items:center}
main{flex:1;min-height:0;margin:0 14px 14px;background:var(--panel);border:1px solid var(--line);border-radius:0 8px 8px 8px;position:relative}
.log{position:absolute;inset:0;overflow:auto;padding:8px 0;display:none;font:12.5px/1.5 ui-monospace,Consolas,monospace}
.log.on{display:block}.l{display:flex;gap:10px;padding:1px 12px;white-space:pre-wrap;word-break:break-word}
.l:hover{background:rgba(127,127,127,.08)}.t{color:var(--dim);flex:none}.src{flex:none;width:52px;color:var(--dim)}
.src.api{color:#7aa2ff}.src.worker{color:#c792ea}.src.git{color:#4cd08a}.src.painel{color:var(--warn)}
.m{flex:1}.h .m{font-weight:600;color:var(--acc)}#errors .m{color:var(--err)}.hide{display:none}
.empty{color:var(--dim);padding:16px;font-family:system-ui}
</style></head><body>
<header><h1>Painel do Assistente</h1><div class="pills" id="pills"></div><span id="busy"></span><div class="sp"></div>
<a id="app" target="_blank">Abrir assistente ↗</a>
<button data-r="api">Reiniciar API</button><button data-r="workers">Reiniciar workers</button><button data-r="all">Reiniciar tudo</button>
<button class="danger" id="stop">Encerrar tudo</button></header>
<nav><button class="tab on" data-k="activity">Atividade</button><button class="tab" data-k="errors">Erros<span class="badge" id="eb"></span></button>
<button class="tab" data-k="raw">Bruto</button><div class="sp"></div>
<input id="filter" placeholder="filtrar…"><label><input type="checkbox" id="follow" checked>seguir</label><button id="clear">Limpar</button></nav>
<main><div class="log on" id="activity"></div><div class="log" id="errors"></div><div class="log" id="raw"></div></main>
<script>
const $=s=>document.querySelector(s),H={'X-Painel':'1'};let tab='activity',after={activity:0,errors:0,raw:0},unseen=0,busy=false;
$('#app').href=location.protocol+'//'+location.hostname+':8001';
const post=u=>fetch(u,{method:'POST',headers:H}).then(r=>r.json()).catch(()=>({}));
function add(kind,items){const box=$('#'+kind),f=$('#filter').value.toLowerCase();if(!items.length)return;
 const stick=$('#follow').checked||box.scrollHeight-box.scrollTop-box.clientHeight<60;
 for(const e of items){after[kind]=Math.max(after[kind],e.id);const d=document.createElement('div');
  const hd=/^\s*={3,}/.test(e.text);d.className='l'+(hd?' h':'');
  d.innerHTML='<span class="t"></span><span class="src"></span><span class="m"></span>';
  d.children[0].textContent=e.t;d.children[1].textContent=e.src;d.children[1].classList.add(e.src);
  d.children[2].textContent=hd?e.text.replace(/=+/g,'').trim():e.text;
  if(f&&!e.text.toLowerCase().includes(f))d.classList.add('hide');box.appendChild(d);}
 while(box.children.length>2500)box.removeChild(box.firstChild);
 if(stick&&kind===tab)box.scrollTop=box.scrollHeight;
 if(kind==='errors'&&tab!=='errors'){unseen+=items.length;$('#eb').textContent=unseen;}}
async function poll(){for(const k of ['activity','errors',...(tab==='raw'?['raw']:[])]){
 try{const r=await (await fetch('/api/logs?kind='+k+'&after='+after[k])).json();add(k,r.lines||[]);}catch(e){}}
 setTimeout(poll,1000);}
async function status(){try{const s=await (await fetch('/api/status')).json();
 $('#pills').innerHTML=s.services.map(x=>`<span class="pill ${x.running?'up':''}" title="${x.running?'pid '+x.pid:'parado'+(x.code!=null?' (código '+x.code+')':'')}"><span class="dot"></span>${x.label}</span>`).join('');
 busy=!!s.busy;$('#busy').textContent=s.busy;document.querySelectorAll('[data-r],#stop').forEach(b=>b.disabled=busy);}
 catch(e){$('#pills').innerHTML='<span class="pill"><span class="dot"></span>painel offline</span>';}
 setTimeout(status,1500);}
document.querySelectorAll('[data-r]').forEach(b=>b.onclick=async()=>{const k=b.dataset.r;
 if(k!=='api'&&!confirm('Se uma task estiver rodando agora, ela será interrompida. Continuar?'))return;
 b.disabled=true;await post('/api/restart/'+k);});
$('#stop').onclick=async()=>{if(confirm('Encerrar API e workers e fechar o painel?')){await post('/api/shutdown');$('#busy').textContent='Encerrado.';}};
$('#clear').onclick=async()=>{await post('/api/clear/'+tab);$('#'+tab).innerHTML='';};
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{tab=b.dataset.k;
 document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===b));
 document.querySelectorAll('.log').forEach(x=>x.classList.toggle('on',x.id===tab));
 if(tab==='errors'){unseen=0;$('#eb').textContent='';}const box=$('#'+tab);box.scrollTop=box.scrollHeight;});
$('#filter').oninput=()=>{const f=$('#filter').value.toLowerCase();
 document.querySelectorAll('.l').forEach(d=>d.classList.toggle('hide',!!f&&!d.textContent.toLowerCase().includes(f)));};
poll();status();
</script></body></html>"""


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PANEL_PORT), Handler)
    except OSError:
        print(f"Painel já está rodando em http://localhost:{PANEL_PORT}")
        return
    SERVICES.extend(build_services())
    run_op("Iniciando serviços…", lambda: [s.start() for s in SERVICES])
    try:
        server.serve_forever()
    finally:
        stop_all()


if __name__ == "__main__":
    main()
