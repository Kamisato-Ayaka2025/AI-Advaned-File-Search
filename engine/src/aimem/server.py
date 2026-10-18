from __future__ import annotations

import datetime as dt
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from . import db, planner
from .embedders import make_embedder
from .rerank import make_reranker
from .search.pipeline import search
from .text import size_label
from .vectors import VectorStore

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>个人信息记忆检索</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1b1f24; --sub:#6b7280; --line:#e5e7eb;
          --accent:#2563eb; --fs:#0f766e; --wx:#15803d; --qq:#1d4ed8; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
  header { position:sticky; top:0; background:rgba(246,247,249,.92); backdrop-filter:blur(8px);
           border-bottom:1px solid var(--line); padding:18px 0 12px; z-index:5; }
  .wrap { max-width:960px; margin:0 auto; padding:0 20px; }
  h1 { font-size:19px; margin:0 0 2px; letter-spacing:.2px; }
  .sub { color:var(--sub); font-size:13px; margin-bottom:12px; }
  .bar { display:flex; gap:10px; }
  input[type=search] { flex:1; padding:13px 16px; font-size:16px; border:1px solid var(--line);
        border-radius:12px; background:#fff; outline:none; }
  input[type=search]:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(37,99,235,.12); }
  button { border:1px solid var(--line); background:#fff; border-radius:12px; padding:0 18px;
           font-size:15px; cursor:pointer; }
  button:hover { border-color:var(--accent); color:var(--accent); }
  .filters { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; align-items:center; }
  .chip { border:1px solid var(--line); background:#fff; border-radius:999px; padding:5px 12px;
          font-size:13px; cursor:pointer; color:var(--sub); }
  .chip.on { border-color:var(--accent); color:var(--accent); background:#eff6ff; }
  label.toggle { margin-left:auto; font-size:13px; color:var(--sub); display:flex; gap:6px; align-items:center; }
  main { padding:18px 0 60px; }
  .meta { color:var(--sub); font-size:13px; margin:0 0 12px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px;
          margin-bottom:12px; }
  .card:hover { border-color:#c7d2fe; box-shadow:0 2px 10px rgba(15,23,42,.05); }
  .title { font-size:16px; font-weight:600; margin:0 0 4px; }
  .badges { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:6px; }
  .badge { font-size:12px; padding:2px 8px; border-radius:999px; background:#f3f4f6; color:#374151; }
  .badge.fs { background:#ecfdf5; color:var(--fs); }
  .badge.wechat { background:#f0fdf4; color:var(--wx); }
  .badge.qq { background:#eff6ff; color:var(--qq); }
  .path { font:12px/1.5 ui-monospace,Consolas,monospace; color:var(--sub); word-break:break-all; }
  .snippet { margin-top:8px; color:#374151; font-size:14px; }
  .why { margin-top:8px; font-size:12px; color:var(--sub); }
  .why span { background:#f9fafb; border:1px solid var(--line); border-radius:6px; padding:1px 6px; margin-right:4px; }
  .empty { color:var(--sub); text-align:center; padding:48px 0; }
  .score { margin-left:auto; font:12px ui-monospace,monospace; color:#9ca3af; }
</style>
</head>
<body>
<header><div class="wrap">
  <h1>个人信息记忆检索</h1>
  <div class="sub" id="stats">加载中…</div>
  <div class="bar">
    <input id="q" type="search" placeholder="例如：上周张经理发的采购方案 / 课表 第8周 / 显卡过热掉帧" autofocus>
    <button id="go">搜索</button>
  </div>
  <div class="filters">
    <span class="chip on" data-src="">全部</span>
    <span class="chip" data-src="fs">本地文件</span>
    <span class="chip" data-src="wechat">微信</span>
    <span class="chip" data-src="qq">QQ</span>
    <label class="toggle"><input id="rerank" type="checkbox"> AI 精排</label>
  </div>
</div></header>
<main><div class="wrap">
  <div class="meta" id="meta"></div>
  <div id="list"></div>
</div></main>
<script>
const $ = s => document.querySelector(s);
let source = "", seq = 0;
const fmtDate = ts => ts ? new Date(ts*1000).toLocaleString('zh-CN',{hour12:false}) : '';

async function stats(){
  const r = await fetch('/api/stats'); const d = await r.json();
  const parts = [];
  for (const [k,v] of Object.entries(d.by_source||{})) parts.push(`${k} ${v}`);
  $('#stats').textContent = `索引 ${d.units.toLocaleString()} 个单元  ·  ${parts.join('  ·  ')}`;
}

async function run(){
  const q = $('#q').value.trim();
  if(!q){ $('#list').innerHTML=''; $('#meta').textContent=''; return; }
  const my = ++seq;
  $('#meta').textContent = '搜索中…';
  const url = `/api/search?q=${encodeURIComponent(q)}&source=${source}&rerank=${$('#rerank').checked?1:0}`;
  const t0 = performance.now();
  const r = await fetch(url); const d = await r.json();
  if(my !== seq) return;
  $('#meta').textContent = `${d.results.length} 条结果  ·  ${d.elapsed_ms} ms`;
  if(!d.results.length){ $('#list').innerHTML = '<div class="empty">没有找到，试试更短的关键词</div>'; return; }
  $('#list').innerHTML = d.results.map(r => {
    const b = r.source || 'fs';
    const title = r.title || r.path || r.id;
    const path = r.path ? `<div class="path">${esc(r.path)}</div>` : '';
    const why = (r.reasons||[]).map(x=>`<span>${esc(x)}</span>`).join('');
    return `<div class="card">
      <div class="badges"><span class="badge ${b}">${label(b)}</span>
        <span class="badge">${esc(r.kind||'')}</span>
        <span class="badge">${fmtDate(r.ts)}</span>
        ${r.size?`<span class="badge">${r.size_label||''}</span>`:''}
        <span class="score">${(r.score??0).toFixed(3)}</span></div>
      <div class="title">${esc(title)}</div>
      ${path}
      <div class="snippet">${esc(r.snippet||'')}</div>
      ${why?`<div class="why">${why}</div>`:''}
    </div>`;
  }).join('');
}
function label(s){ return {fs:'本地文件',wechat:'微信',qq:'QQ'}[s] || s; }
function esc(s){ return (s||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

$('#q').addEventListener('input', ()=> setTimeout(run, 280));
$('#go').addEventListener('click', run);
$('#q').addEventListener('keydown', e=>{ if(e.key==='Enter') run(); });
$('#rerank').addEventListener('change', run);
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', ()=>{
  document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); source = c.dataset.src; run();
}));
stats();
</script>
</body>
</html>
"""


class App:
    def __init__(
        self,
        db_path: str,
        store_path: str,
        embed_spec: str,
        rerank_spec: str | None,
        device: str | None,
    ) -> None:
        self.conn = db.connect(db_path)
        self.store = VectorStore(store_path).load()
        self.embedder = make_embedder(embed_spec, device)
        self.reranker = (
            make_reranker(rerank_spec, device, "float16") if rerank_spec else None
        )
        print(
            f"[serve] db={db_path} units={db.stats(self.conn)['units']} "
            f"vectors={len(self.store)} embed={embed_spec} rerank={rerank_spec}",
            flush=True,
        )

    def search(self, q: str, source: str, use_rerank: bool) -> dict:
        t0 = time.time()
        plan = planner.plan(q)
        if source:
            plan.sources = [source]
        results = search(
            self.conn,
            self.store,
            self.embedder,
            q,
            limit=20,
            plan=plan,
            reranker=self.reranker if (self.reranker and use_rerank) else None,
        )
        out = []
        for r in results:
            d = r.to_dict()
            d["size_label"] = size_label(r.unit.size)
            out.append(d)
        return {
            "results": out,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            u = urlparse(self.path)
            if u.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if u.path == "/api/stats":
                self._send(
                    200,
                    json.dumps(db.stats(app.conn), ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if u.path == "/api/search":
                qs = parse_qs(u.query)
                q = (qs.get("q") or [""])[0]
                source = (qs.get("source") or [""])[0]
                use_rerank = (qs.get("rerank") or ["0"])[0] == "1"
                try:
                    payload = app.search(q, source, use_rerank)
                except Exception as exc:  # keep the demo alive
                    payload = {"results": [], "elapsed_ms": 0, "error": str(exc)}
                self._send(
                    200,
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            self._send(404, b"not found", "text/plain")

        def log_message(self, *args) -> None:
            return

    return Handler


def serve(
    db_path: str,
    store_path: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    embed: str = "st:BAAI/bge-small-zh-v1.5",
    rerank: str | None = None,
    device: str | None = None,
) -> None:
    app = App(db_path, store_path, embed, rerank, device)
    server = HTTPServer((host, port), make_handler(app))
    print(f"[serve] http://{host}:{port}", flush=True)
    server.serve_forever()
