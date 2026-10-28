# -*- coding: utf-8 -*-
"""聊天记录浏览器 —— Python 标准库 http.server + SQLite + HTMX
启动: python app.py  ->  http://127.0.0.1:8000
只读标准结构库 standard.db(chat-standard v1.0); 换数据源只换导入脚本。
"""
import os, re, sqlite3, html, json
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = r"C:/Users/a1/Documents/HiSuite"
DB = os.path.join(DATA, "standard.db")
MEDIA_DIR = os.path.join(DATA, "wechat_media")
MEDIA2_DIR = os.path.join(DATA, "media")   # 第二个图片缓存目录
PORT = 8000
def q(sql, args=()):
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()

def q1(sql, args=()):
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, args).fetchone()
    finally:
        db.close()

# ---------- 工具 ----------
def esc(s):
    return html.escape(str(s or ""), quote=False)

def br(s):
    return esc(s).replace("\n", "<br>")

def fmt_time(ms):
    import time
    t = time.localtime(ms / 1000)
    return time.strftime("%Y-%m-%d %H:%M", t)

def fmt_short(ms):
    import time
    t = time.localtime(ms / 1000)
    return time.strftime("%Y-%m-%d %H:%M:%S", t)

def fmt_last(ms):
    import time
    now = time.localtime()
    t = time.localtime(ms / 1000)
    if (t.tm_year, t.tm_mon, t.tm_mday) == (now.tm_year, now.tm_mon, now.tm_mday):
        return time.strftime("%H:%M", t)
    if t.tm_year == now.tm_year:
        return time.strftime("%m-%d", t)
    return time.strftime("%Y-%m-%d", t)

def avatar_char(name):
    return esc((name or "?")[0].upper())

# ---------- 片段: 会话列表 ----------
def render_sessions(search=""):
    if search:
        rows = q("""SELECT s.*, (SELECT text FROM messages m WHERE m.session_id=s.id
                   ORDER BY timestamp DESC LIMIT 1) lt,
                   (SELECT timestamp FROM messages m WHERE m.session_id=s.id
                   ORDER BY timestamp DESC LIMIT 1) lts
                   FROM sessions s WHERE s.name LIKE ? ORDER BY lts DESC""",
                 (f"%{search}%",))
    else:
        rows = q("""SELECT s.*, (SELECT text FROM messages m WHERE m.session_id=s.id
                   ORDER BY timestamp DESC LIMIT 1) lt,
                   (SELECT timestamp FROM messages m WHERE m.session_id=s.id
                   ORDER BY timestamp DESC LIMIT 1) lts
                   FROM sessions s ORDER BY lts DESC""")
    out = []
    for r in rows:
        last = (r["lt"] or "")[:26]
        out.append(
            f'<div class="sess" hx-get="/session?id={esc(r["id"])}" hx-target="#messages" '
            f'hx-swap="innerHTML" hx-on::after-request="scrollBottom()">'
            f'<div class="avatar">{avatar_char(r["name"])}</div>'
            f'<div class="si"><div class="sn">{esc(r["name"])}</div>'
            f'<div class="sl">{br(last)}</div></div>'
            f'<div class="st">{fmt_last(r["lts"]) if r["lts"] else ""}</div></div>')
    if not out:
        return '<div class="none">无匹配会话</div>'
    return "".join(out)

# ---------- 片段: 消息 ----------
def render_msg(m, first_of_group):
    mid, sid, direction, sender, sname, ts, typ, text, mp, mt, dur = m
    mine = direction == "send"
    part = []
    if first_of_group:
        part.append(f'<div class="tg"><span>{fmt_time(ts)}</span></div>')
    if typ == "system":
        part.append(f'<div class="msg sys"><div class="bub sys">{br(text)}</div></div>')
        return "".join(part)
    if typ == "image":
        body = (f'<img class="media" loading="lazy" src="/media/{mp}" '
                f'data-src="/media/{mp}" onclick="openLb(this)" style="cursor:zoom-in">' if mp else
                '<div class="bub miss">[图片未解出]</div>')
    elif typ == "voice":
        d = f' {int(dur)}″' if dur else ""
        body = (f'<div class="bub v"><audio controls src="/media/{mp}"></audio></div>'
                if mp else f'<div class="bub">🎤 [语音未解出{d}]</div>')
    elif typ == "video":
        body = (f'<video class="media" controls src="/media/{mp}" preload="metadata" '
                f'ondblclick="try{{this.requestFullscreen()}}catch(e){{}}" style="cursor:pointer"></video>' if mp
                else '<div class="bub miss">[视频未解出]</div>')
    elif typ == "emoji":
        body = (f'<img class="media em" src="/media/{mp}" data-src="/media/{mp}" '
                f'onclick="openLb(this)" style="cursor:zoom-in">' if mp
                else '<div class="bub">😊 [表情]</div>')
    elif typ == "link":
        body = f'<div class="bub link">{br(text)}</div>'
    else:
        body = f'<div class="bub">{br(text)}</div>'
    cls = "msg mine" if mine else "msg"
    meta = f'<div class="mt">{fmt_short(ts)}</div>'
    name = ""
    if not mine and sname and sname != "我" and "@chatroom" in sid:
        name = f'<div class="mn">{esc(sname)}</div>'
    return (f'<div class="{cls}"><div class="mav">{("我" if mine else (sname or "?")[0])}</div>'
            f'<div class="mb">{name}{body}{meta}</div></div>')

def render_messages(sid, before=None, limit=50):
    s = q1("SELECT * FROM sessions WHERE id=?", (sid,))
    if not s:
        return '<div class="none">会话不存在</div>'
    # (timestamp,id) 复合游标; limit+1 探测是否还有更早
    sel = ("SELECT id,session_id,direction,sender,sender_name,timestamp,type,text,"
           "media_path,media_thumb,media_duration FROM messages WHERE session_id=? ")
    if before:
        ts, bid = map(int, before.split("_"))
        rows = q(sel + "AND (timestamp<? OR (timestamp=? AND id<?)) "
                 "ORDER BY timestamp DESC, id DESC LIMIT ?",
                 (sid, ts, ts, bid, limit + 1))
    else:
        rows = q(sel + "ORDER BY timestamp DESC, id DESC LIMIT ?", (sid, limit + 1))
    has_more = len(rows) > limit
    msgs = list(reversed(rows[:limit]))  # 升序渲染(最早在前)
    parts = []
    last_ts = 0
    for m in msgs:
        first = (m["timestamp"] - last_ts) > 5 * 60 * 1000
        parts.append(render_msg(tuple(m), first))
        last_ts = m["timestamp"]
    body = "".join(parts)
    if has_more and msgs:
        e = msgs[0]
        cur = f"{e['timestamp']}_{e['id']}"
        body = (f'<div id="loadmore" hx-get="/session?id={esc(sid)}&before={cur}" '
                f'hx-trigger="revealed, click" hx-swap="outerHTML" '
                f'hx-on::before-request="beforeLoad()" hx-on::after-request="afterLoad()">'
                f'<div class="loading">↑ 加载更早消息（点击或继续上滑）</div></div>' + body)
    return body

# ---------- 页面骨架 ----------
INDEX = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>聊天记录浏览器</title>
<script src="/static/htmx.min.js"></script>
<style>
:root{--bg:#f5f5f5;--side:#f7f7f7;--bd:#e5e5e5;--mine:#95ec69;--txt:#111;--mut:#999;--acc:#07c160}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei",sans-serif;background:var(--bg);color:var(--txt);height:100vh;overflow:hidden}
#app{display:flex;height:100vh}
#sb{width:300px;min-width:240px;background:var(--side);border-right:1px solid var(--bd);display:flex;flex-direction:column}
#sbx{padding:10px;border-bottom:1px solid var(--bd)}
#sbx input{width:100%;padding:8px 12px;border:1px solid var(--bd);border-radius:6px;font-size:14px;outline:none}
#sbx input:focus{border-color:var(--acc)}
#sl{flex:1;overflow-y:auto;min-height:0}
.sess{display:flex;padding:10px 12px;cursor:pointer;gap:10px;align-items:center;border-bottom:1px solid #f0f0f0}
.sess:hover,.sess.active{background:#ebebeb}
.avatar{width:40px;height:40px;border-radius:5px;background:var(--acc);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:bold;flex-shrink:0}
.si{flex:1;overflow:hidden}.sn{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sl{font-size:12px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}
.st{font-size:11px;color:var(--mut);flex-shrink:0}
.none{padding:20px;color:#999;text-align:center;font-size:13px}
.loading{padding:12px;color:#999;text-align:center;font-size:12px}
#ch{flex:1;display:flex;flex-direction:column;min-width:0}
#chh{height:50px;background:var(--side);border-bottom:1px solid var(--bd);display:flex;align-items:center;padding:0 16px;font-size:15px;font-weight:bold;gap:10px}
#chh .ct{font-weight:normal;font-size:12px;color:var(--mut)}
#messages{flex:1;overflow-y:auto;overflow-x:hidden;min-height:0;padding:16px 10% 30px;scrollbar-width:thin}
#messages::-webkit-scrollbar{width:8px}
#messages::-webkit-scrollbar-thumb{background:#c8c8c8;border-radius:4px}
#messages::-webkit-scrollbar-thumb:hover{background:#aaa}
.tg{text-align:center;margin:14px 0;color:var(--mut);font-size:12px}
.tg span{background:#e8e8e8;padding:3px 10px;border-radius:4px}
.msg{display:flex;margin:8px 0;gap:8px;align-items:flex-start}
.msg.mine{flex-direction:row-reverse}
.mav{width:36px;height:36px;border-radius:4px;background:#ddd;flex-shrink:0;font-size:12px;display:flex;align-items:center;justify-content:center;color:#888}
.mb{max-width:65%;display:flex;flex-direction:column}
.msg.mine .mb{align-items:flex-end}
.mn{font-size:11px;color:var(--mut);margin-bottom:2px}
.bub{padding:8px 12px;border-radius:6px;font-size:14px;line-height:1.55;word-break:break-word;box-shadow:0 1px 1px rgba(0,0,0,.05);background:#fff}
.msg.mine .bub{background:var(--mine)}
.msg.sys .bub{background:none;box-shadow:none;color:var(--mut);font-size:12px}
.mt{font-size:11px;color:var(--mut);margin-top:3px}
.media{border-radius:6px;max-width:260px;max-height:280px;display:block;cursor:zoom-in;background:#eee}
.media.em{max-width:120px;max-height:120px}
.bub.miss{background:#eee;color:#999;font-size:13px}
.bub.link{background:#fff;border:1px solid var(--bd)}
.bub.v{padding:6px}
audio{height:30px;max-width:240px}
video.media{max-height:320px;cursor:default}
#ib{background:#fff;border-top:1px solid var(--bd);padding:12px 16px 16px;flex-shrink:0;height:110px}
#ib .row{display:flex;align-items:center;gap:12px;height:100%;max-width:800px;margin:0 auto}
#ib input.inp{flex:1;height:48px;border:1px solid #e5e5e5;background:#f7f7f7;border-radius:6px;padding:0 16px;font-size:15px;outline:none;color:#999}
#ib input.inp::placeholder{color:#bbb}
#ib .send{flex:none;width:90px;height:48px;background:var(--acc);color:#fff;border:none;border-radius:6px;font-size:15px;cursor:not-allowed;opacity:.85}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;z-index:9999;align-items:center;justify-content:center;user-select:none}
#lb.open{display:flex}
#lb .lb-stage{position:absolute;inset:0;overflow:hidden;display:flex;align-items:center;justify-content:center}
#lb img.lb-img{max-width:none;max-height:none;transition:transform .18s ease;cursor:grab;box-shadow:0 8px 40px rgba(0,0,0,.5)}
#lb img.lb-img:active{cursor:grabbing}
#lb .lb-nav{position:absolute;top:0;bottom:0;width:72px;background:transparent;border:none;color:#fff;font-size:52px;cursor:pointer;opacity:.35;display:flex;align-items:center;justify-content:center;transition:opacity .15s;z-index:2}
#lb .lb-nav:hover{opacity:.9;background:rgba(255,255,255,.06)}
#lb .lb-prev{left:0}
#lb .lb-next{right:0}
#lb .lb-top{position:absolute;top:0;left:0;right:0;height:52px;display:flex;align-items:center;justify-content:space-between;padding:0 18px;color:#ddd;font-size:14px;z-index:3;background:linear-gradient(rgba(0,0,0,.55),transparent)}
#lb .lb-count{letter-spacing:.5px}
#lb .lb-close{background:none;border:none;color:#fff;font-size:30px;cursor:pointer;line-height:1;padding:6px}
#lb .lb-close:hover{color:#7ee}
#lb .lb-bar{position:absolute;bottom:16px;left:50%;transform:translateX(-50%);display:flex;gap:10px;background:rgba(30,30,30,.8);padding:7px 12px;border-radius:20px;z-index:3}
#lb .lb-bar button{background:none;border:none;color:#ddd;font-size:15px;cursor:pointer;padding:2px 6px;border-radius:4px}
#lb .lb-bar button:hover{background:rgba(255,255,255,.15);color:#fff}
</style></head>
<body>
<div id="app">
<aside id="sb">
<div id="sbx"><input placeholder="搜索会话…" hx-get="/sessions" hx-trigger="input delay:300ms"
 hx-target="#sl" hx-swap="innerHTML" name="q"></div>
<div id="sl" hx-get="/sessions" hx-trigger="load"></div>
</aside>
<main id="ch">
<header id="chh"><span id="chname">聊天记录浏览器</span><span class="ct">chat-standard · 点击左侧会话</span></header>
<div id="messages"></div>
<div id="ib">
 <div class="row">
  <input class="inp" placeholder="（只读存档，不可发送）" readonly value="">
  <button class="send" disabled>发送</button>
 </div>
</div>

</main>
</div>
<script>
function scrollBottom(){setTimeout(()=>{const e=document.getElementById("messages");e.scrollTop=e.scrollHeight},400)}
function selSess(name,n){document.getElementById("chname").textContent=name;
 document.getElementById("chh").querySelector(".ct").textContent=n+" 条"}
function beforeLoad(){const e=document.getElementById("messages");
 window._st=e.scrollTop; window._sh=e.scrollHeight}
function afterLoad(){const e=document.getElementById("messages");
 setTimeout(()=>{e.scrollTop=window._st+(e.scrollHeight-window._sh)},250)}
document.addEventListener('DOMContentLoaded',()=>{
 const m=document.getElementById("messages");
 m.addEventListener('scroll',()=>{
   if(m.scrollTop<=8){const lm=document.getElementById("loadmore"); if(lm&&!lm.dataset.loading){lm.dataset.loading=1; htmx.trigger(lm,'click')}}
 });
 // loadmore 每次加载完后允许再次触发
 document.body.addEventListener('htmx:afterSwap',()=>{setTimeout(()=>{const lm=document.getElementById("loadmore"); if(lm) delete lm.dataset.loading},600)});
});
// ---------- lightbox 图片浏览器 ----------
const lb = { list:[], idx:0, scale:1, tx:0, ty:0 };
function openLb(el){
  lb.list=[...document.querySelectorAll('#messages img.media[data-src]')].map(i=>i.dataset.src);
  lb.idx=Math.max(0, lb.list.indexOf(el.dataset.src));
  lb.scale=1; lb.tx=0; lb.ty=0;
  renderLb(); document.getElementById('lb').classList.add('open');
  document.body.style.overflow='hidden';
}
function renderLb(){
  const img=document.getElementById('lb-img'), c=document.getElementById('lb-count');
  img.src=lb.list[lb.idx]; c.textContent=(lb.idx+1)+' / '+lb.list.length;
  img.style.transform=`scale(${lb.scale}) translate(${lb.tx}px,${lb.ty}px)`;
  document.getElementById('lb-prev').style.display=lb.idx>0?'':'none';
  document.getElementById('lb-next').style.display=lb.idx<lb.list.length-1?'':'none';
}
function lbNav(d){ if(lb.idx+d<0||lb.idx+d>=lb.list.length)return; lb.idx+=d; lb.scale=1; lb.tx=0; lb.ty=0; renderLb(); }
function lbClose(){ document.getElementById('lb').classList.remove('open'); document.body.style.overflow=''; }
function lbZoom(z, cx, cy){ lb.scale=Math.min(6,Math.max(.2, lb.scale*(z>0?1.25:0.8))); renderLb(); }
function lbReset(){ lb.scale=1; lb.tx=0; lb.ty=0; renderLb(); }
// 拖拽平移
let drag=null;
function lbDown(e){ const img=e.target; drag={x:e.clientX,y:e.clientY,tx:lb.tx,ty:lb.ty,moved:false}; e.preventDefault(); }
function lbMove(e){ if(!drag)return; const dx=e.clientX-drag.x, dy=e.clientY-drag.y; if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true; lb.tx=drag.tx+dx; lb.ty=drag.ty+dy; renderLb(); }
function lbUp(){ drag=null; }
document.addEventListener('DOMContentLoaded',()=>{
  const stage=document.getElementById('lb-stage');
  stage.addEventListener('mousedown',lbDown); document.addEventListener('mousemove',lbMove); document.addEventListener('mouseup',lbUp);
  stage.addEventListener('wheel',e=>{ e.preventDefault(); lbZoom(e.deltaY<0?1:-1); },{passive:false});
  stage.addEventListener('dblclick',e=>{ if(lb.scale>1.01)lbReset(); else lbZoom(1); });
  document.addEventListener('keydown',e=>{
    if(!document.getElementById('lb').classList.contains('open'))return;
    if(e.key==='Escape')lbClose(); else if(e.key==='ArrowLeft')lbNav(-1); else if(e.key==='ArrowRight')lbNav(1);
  });
});
</script>
<div id="lb">
 <div class="lb-top"><span class="lb-count" id="lb-count"></span><button class="lb-close" onclick="lbClose()">×</button></div>
 <button class="lb-nav lb-prev" id="lb-prev" onclick="lbNav(-1)">‹</button>
 <div class="lb-stage" id="lb-stage"><img class="lb-img" id="lb-img" draggable="false" alt=""></div>
 <button class="lb-nav lb-next" id="lb-next" onclick="lbNav(1)">›</button>
 <div class="lb-bar"><button onclick="lbZoom(1)">＋</button><button onclick="lbZoom(-1)">－</button><button onclick="lbReset()">1:1</button></div>
</div>
</body></html>"""

# ---------- HTTP ----------
MIME = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".gif":"image/gif",
        ".mp4":"video/mp4",".webp":"image/webp",".mp3":"audio/mpeg",".amr":"audio/amr",
        ".silk":"audio/silk",".js":"application/javascript",".html":"text/html"}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="text/html; charset=utf-8", status=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path, params = u.path, parse_qs(u.query)
        try:
            if path == "/":
                return self.send(INDEX)
            if path == "/static/htmx.min.js":
                with open(os.path.join(BASE, "static", "htmx.min.js"), "rb") as f:
                    return self.send(f.read(), "application/javascript")
            if path == "/sessions":
                return self.send(render_sessions((params.get("q") or [""])[0]))
            if path == "/session":
                sid = (params.get("id") or [""])[0]
                before = (params.get("before") or [None])[0]
                limit = int((params.get("limit") or ["50"])[0])
                s = q1("SELECT name FROM sessions WHERE id=?", (sid,))
                if s:
                    n = q1("SELECT COUNT(*) c FROM messages WHERE session_id=?", (sid,))["c"]
                    self.send(f'<script>selSess({esc(s["name"])!r},{n});</script>'
                              + render_messages(sid, before, limit))
                else:
                    self.send('<script>selSess("",0)</script><div class="none">会话不存在</div>')
                return
            m = None
            if path.startswith("/media/"):
                m, rel = MEDIA_DIR, path[len("/media/"):]
            elif path.startswith("/media2/"):
                m, rel = MEDIA2_DIR, path[len("/media2/"):]
            if m:
                full = os.path.join(m, rel.replace("/", os.sep))
                if not os.path.isfile(full):
                    return self.send("not found", "text/plain", 404)
                size = os.path.getsize(full)
                ctype = MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    spec = rng[6:].split("-")
                    start = int(spec[0]) if spec[0] else 0
                    end = int(spec[1]) if len(spec) > 1 and spec[1] else size - 1
                    start = max(0, min(start, size - 1))
                    end = max(start, min(end, size - 1))
                    n = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(n))
                    self.end_headers()
                    with open(full, "rb") as f:
                        f.seek(start)
                        left = n
                        while left > 0:
                            chunk = f.read(min(65536, left))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            left -= len(chunk)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(size))
                    self.end_headers()
                    with open(full, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                return
            return self.send("404", "text/plain", 404)
        except Exception as e:
            return self.send(f"error: {esc(e)}", "text/plain", 500)

if __name__ == "__main__":
    print(f"聊天记录浏览器: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
