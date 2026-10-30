# -*- coding: utf-8 -*-
"""聊天记录浏览器 —— Python 标准库 http.server + SQLite + HTMX
启动: python app.py  ->  http://127.0.0.1:8000
只读标准结构库 standard.db(chat-standard v1.0); 换数据源只换导入脚本。
"""
import os, re, sqlite3, html, json
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

BASE = os.path.dirname(os.path.abspath(__file__))
# ---------- 可配置扫描目录(config.json) ----------
CONFIG_PATH = os.path.join(BASE, "config.json")
DEFAULT_CONFIG = {"data_dir": r"C:/Users/a1/Documents/HiSuite",
                  "sms_dir": r"C:/Users/a1/Documents/HiSuite/ExportSMS",
                  "contact_dir": r"C:/Users/a1/Documents/HiSuite/ExportContact"}
CONFIG = {}

def load_config():
    """加载config.json并重算全局路径; 每个功能扫一个可配置目录"""
    global CONFIG, DATA, DB, RAW_DB, DECRYPTED_DB, MEDIA_DIR, MEDIA2_DIR
    CONFIG = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            CONFIG.update(json.load(f) or {})
    except Exception:
        pass
    DATA = CONFIG.get("data_dir", DEFAULT_CONFIG["data_dir"])
    DB = os.path.join(DATA, "standard.db")
    RAW_DB = os.path.join(DATA, "decrypted_view.db")
    DECRYPTED_DB = os.path.join(DATA, "decrypted.db")
    MEDIA_DIR = os.path.join(DATA, "wechat_media")
    MEDIA2_DIR = os.path.join(DATA, "media")
    if not CONFIG.get("sms_dir"):
        CONFIG["sms_dir"] = os.path.join(DATA, "ExportSMS")
    if not CONFIG.get("contact_dir"):
        CONFIG["contact_dir"] = os.path.join(DATA, "ExportContact")

load_config()
PORT = 8001


# ---------- 真全库查询 ----------
def rq(sql, args=()):
    db = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


def rq1(sql, args=()):
    db = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, args).fetchone()
    finally:
        db.close()


def dq(sql, args=()):
    db = sqlite3.connect(f"file:{DECRYPTED_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


def dq1(sql, args=()):
    db = sqlite3.connect(f"file:{DECRYPTED_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, args).fetchone()
    finally:
        db.close()


# 媒体相对路径索引(构建一次缓存): 子目录->{文件名->相对路径}
import functools


@functools.lru_cache(maxsize=None)
def _scan(sub):
    idx = {}
    root = os.path.join(MEDIA_DIR, sub)
    for dp, _, fs in os.walk(root):
        for f in fs:
            idx.setdefault(f, os.path.relpath(os.path.join(dp, f), MEDIA_DIR).replace(os.sep, "/"))
    return idx


def media_path(sub, fname):
    """按文件名(或md5)找 /media/<rel> 可访问路径; 找不到返回空"""
    if not fname:
        return ""
    idx = _scan(sub)
    if fname in idx:
        return "/media/" + idx[fname]
    stem = fname.split(".")[0]
    if stem in idx:
        return "/media/" + idx[stem]
    for k, v in idx.items():
        if k.startswith(fname) or fname.startswith(k):
            return "/media/" + v
    return ""

def media_path_exact(sub, fname):
    idx = _scan(sub)
    if fname in idx:
        return "/media/" + idx[fname]
    return ""


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

# standard.db 查询别名 (避免被局部变量 q 遮蔽)
_sq = q
_sq1 = q1



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

PALETTE = ["#f56c6c", "#e6a23c", "#67c23a", "#409eff", "#b37feb", "#ff7c9f", "#2ec7c9", "#5b8ff9"]

def avatar_color(name):
    """昵称 hash → 微信风格彩色头像背景"""
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xffffffff
    return PALETTE[h % len(PALETTE)]

# ---------- 片段: 消息 ----------
def render_msg(m, first_of_group):
    mid, sid, direction, sender, sname, ts, typ, text, mp, mt, dur, reply_to, card_json = m
    mine = direction == "send"
    part = []
    if first_of_group:
        part.append(f'<div class="tg"><span>{fmt_time(ts)}</span></div>')
    if typ == "system":
        part.append(f'<div class="msg sys"><div class="bub sys">{br(text)}</div></div>')
        return "".join(part)
    if typ == "image":
        body = (f'<img class="media" loading="lazy" src="{mp}" '
                f'data-src="{mp}" onclick="openLb(this)" style="cursor:zoom-in">' if mp else
                '<div class="bub miss">[图片未解出]</div>')
    elif typ == "voice":
        d = f' {int(dur)}″' if dur else ""
        body = (f'<div class="bub v"><button class="vbtn">▶</button>'
                f'<audio hidden preload="none" data-src="{mp}"></audio><span class="vt">{d}</span></div>'
                if mp else f'<div class="bub">🎤 [语音未解出{d}]</div>')
    elif typ == "video":
        body = (f'<video class="media" controls src="{mp}" preload="metadata" '
                f'ondblclick="try{{this.requestFullscreen()}}catch(e){{}}" style="cursor:pointer"></video>' if mp
                else '<div class="bub miss">[视频未解出]</div>')
    elif typ == "emoji":
        body = (f'<img class="media em" src="{mp}" data-src="{mp}" '
                f'onclick="openLb(this)" style="cursor:zoom-in">' if mp
                else '<div class="bub">😊 [表情]</div>')
    elif typ == "link":
        body = f'<div class="bub link">{br(text)}</div>'
        if card_json:
            try:
                cd = json.loads(card_json)
            except Exception:
                cd = None
            if cd and cd.get("url"):
                cv = f'<img class="cc" src="{esc(cd["cover"])}" loading="lazy">' if cd.get("cover") else ""
                des = cd.get("des") or ""
                src = cd.get("source") or ""
                body = (f'<a class="card" href="{esc(cd["url"])}" target="_blank" rel="noopener">{cv}'
                        f'<div class="cb"><div class="ct">{esc(cd.get("title") or text)}</div>'
                        + (f'<div class="cd">{esc(des)}</div>' if des else "")
                        + f'<div class="cs">{esc(src)}</div></div></a>')
    elif typ == "hongbao":
        try:
            cd = json.loads(card_json) if card_json else {}
        except Exception:
            cd = {}
        u = cd.get("url") or ""
        tx = cd.get("text") or text
        hb = f'<span class="hb-ic">🧧</span><div class="hb-tx">{br(tx)}</div>'
        body = (f'<a class="hb" href="{esc(u)}" target="_blank" rel="noopener">{hb}</a>' if u
                else f'<div class="hb">{hb}</div>')
    elif typ == "location":
        if card_json:
            try:
                cd = json.loads(card_json)
            except Exception:
                cd = None
            if cd and cd.get("x"):
                label = cd.get("label") or text
                body = (f'<a class="card loc" href="https://api.map.baidu.com/marker?location={esc(cd["x"])},{esc(cd["y"])}'
                        f'&title={esc(label)}&content={esc(label)}&output=html" target="_blank" rel="noopener">'
                        f'<div class="cb"><div class="ct">📍 {esc(label)}</div>'
                        f'<div class="cd">坐标 {esc(cd["x"])}, {esc(cd["y"])}</div>'
                        f'<div class="cs">百度地图</div></div></a>')
    else:
        body = f'<div class="bub">{br(text)}</div>'
    if reply_to and typ != "system":
        body = f'<div class="quote">{esc(reply_to)}</div>' + body
    cls = "msg mine" if mine else "msg"
    meta = f'<div class="mt">{fmt_short(ts)}</div>'
    name = ""
    if not mine and sname and sname != "我" and "@chatroom" in sid:
        name = f'<div class="mn" tabindex="0" title="{esc(sname)}">{esc(sname)}</div>'
    av = "我" if mine else (sname or "?")[0]
    ac = "#07c160" if mine else avatar_color(sname or "?")
    return (f'<div class="{cls}" data-mid="{mid}"><div class="mav" style="background:{ac}">{av}</div>'
            f'<div class="mb">{name}{body}{meta}</div></div>')

def render_messages(sid, before=None, limit=10, focus=None):
    s = q1("SELECT * FROM sessions WHERE id=?", (sid,))
    if not s:
        return '<div class="none">会话不存在</div>'
    # (timestamp,id) 复合游标; limit+1 探测是否还有更早
    sel = ("SELECT id,session_id,direction,sender,sender_name,timestamp,type,text,"
           "media_path,media_thumb,media_duration,reply_to,card FROM messages WHERE session_id=? ")
    if focus:
        # 定位: 以 focus 消息为窗口上界, 取其及之前 limit 条
        fm = q1("SELECT timestamp,id FROM messages WHERE id=?", (focus,))
        if not fm:
            return '<div class="none">目标消息不存在</div>'
        rows = q(sel + "AND (timestamp<? OR (timestamp=? AND id<=?)) "
                 "ORDER BY timestamp DESC, id DESC LIMIT ?",
                 (sid, fm["timestamp"], fm["timestamp"], fm["id"], limit))
        has_more = False
    elif before:
        ts, bid = map(int, before.split("_"))
        rows = q(sel + "AND (timestamp<? OR (timestamp=? AND id<?)) "
                 "ORDER BY timestamp DESC, id DESC LIMIT ?",
                 (sid, ts, ts, bid, limit + 1))
        has_more = len(rows) > limit
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
                f'hx-trigger="click" hx-swap="outerHTML" '
                f'hx-on::before-request="beforeLoad()" hx-on::after-request="afterLoad()">'
                f'<div class="loading">↑ 加载更早消息（滚动到顶两次自动加载，或点击）</div></div>' + body)
    return body
# ---------- 真全库板块: 联系人 / 公众号 / 群聊 / 红包 / 转账 / 好友申请 / 媒体 / 账号 ----------
TYPE_NAME = {1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情", 49: "链接", 48: "位置",
             10000: "系统", 285212721: "系统", 436207665: "红包", 419430449: "转账",
             318767153: "小程序", 570425393: "拍一拍", 1048625: "撤回", 50: "聊天记录"}


def _pager(page, limit, total, url, target="#raw-body"):
    total_pages = max(1, (total + limit - 1) // limit)
    if total_pages <= 1:
        return ""
    sep = "&" if "?" in url else "?"

    def pg(p, label=None, act=False, dis=False):
        cls = "pg" + (" act" if act else "")
        if dis:
            return f'<button class="{cls}" disabled>{label or p}</button>'
        return (f'<button class="{cls}" hx-get="{url}{sep}page={p}" '
                f'hx-target="{target}" hx-swap="innerHTML">{label or p}</button>')

    # 页码窗口: 1 2 ... p-1 p p+1 ... N-1 N
    win = sorted({x for x in (1, 2, page - 1, page, page + 1, total_pages - 1, total_pages)
                  if 1 <= x <= total_pages})
    parts, last = [], 0
    for x in win:
        if x - last > 1:
            parts.append('<span class="pgd">…</span>')
        parts.append(pg(x, act=(x == page)))
        last = x
    prev = pg(page - 1, "‹", dis=(page <= 1))
    nxt = pg(page + 1, "›", dis=(page >= total_pages))
    jump = (f'<input class="pgjump" type="number" min="1" max="{total_pages}" value="{page}" '
            f'onkeydown="if(event.key===\'Enter\')pgJump(this,\'{url}\',{total_pages})">'
            f'<button class="pg pgj" onclick="pgJump(this,\'{url}\',{total_pages})">跳转</button>')
    return (f'<div class="pager">{prev}{"".join(parts)}{nxt}'
            f'<span class="pgi">第 {page}/{total_pages} 页 · {total} 条</span>{jump}</div>')


def _raw_head(title, sub=""):
    return (f'<div class="rawhead"><div class="rawtitle">{esc(title)}</div>'
            f'<div class="rawsub">{esc(sub)}</div></div>')


# ---- 联系人 ----
def render_contacts(page=1, q_=""):
    limit = 40
    where = "WHERE (r.nickname LIKE ? OR r.alias LIKE ? OR r.conRemark LIKE ?)" if q_ else ""
    args = (f"%{q_}%",) * 3 if q_ else ()
    total = rq1(f"SELECT COUNT(*) c FROM rcontact r {where}", args)["c"]
    rows = rq(f"SELECT r.*, f.sex, f.province, f.city, f.signature FROM rcontact r "
              f"LEFT JOIN friend_ext f ON f.username=r.username {where} "
              f"ORDER BY r.username LIMIT ? OFFSET ?",
              args + (limit, (page - 1) * limit))
    out = [_raw_head(f"联系人 ({total})", "rcontact + friend_ext · 真全库")]
    out.append('<div class="grid">')
    for r in rows:
        name = r["conRemark"] or r["nickname"] or r["username"]
        kind = "公众号" if str(r["username"]).startswith("gh_") else ("群聊" if "@chatroom" in str(r["username"]) else "好友")
        sex = {1: "♂", 2: "♀"}.get(r["sex"], "")
        region = f'{r["province"]} {r["city"]}'.strip() if r["province"] else ""
        sig = r["signature"] or ""
        out.append(
            f'<div class="ccard"><div class="cav" style="background:{avatar_color(name)}">{(name or "?")[0]}</div>'
            f'<div class="cinfo"><div class="cname">{esc(name)} <span class="badge">{kind}</span> {sex}</div>'
            f'<div class="csub">{esc(r["username"])}{(" · " + esc(r["alias"])) if r["alias"] else ""}</div>'
            + (f'<div class="csub">{esc(region)}</div>' if region else "")
            + (f'<div class="csig">{esc(sig)}</div>' if sig else "")
            + '</div></div>')
    out.append("</div>")
    out.append(_pager(page, limit, total, "/raw/contacts?q=" + urlencode_q(q_)))
    return "".join(out)


def urlencode_q(q):
    from urllib.parse import quote
    return quote(q or "")


# ---- 应用消息(公众号/视频/音乐/文件/红包等) ----
AM_TYPE = {5: "小程序", 3: "音乐", 33: "链接", 4: "视频", 2001: "红包", 19: "聊天记录",
           1: "链接", 6: "文件", 2000: "转账", 8: "其他", 36: "其他", 2: "其他",
           24: "其他", 7: "其他", 54: "其他", 17: "其他", 57: "其他", 51: "其他"}
AM_GROUPS = [("all", "全部"), ("5", "小程序"), ("3", "音乐"), ("4", "视频"), ("33", "链接"),
             ("6", "文件"), ("2001", "红包"), ("2000", "转账"), ("19", "聊天记录"), ("other", "其他")]

def render_articles(page=1, q_="", amtype="all"):
    limit = 30
    conds, args = [], []
    if q_:
        conds.append("(a.title LIKE ? OR a.source LIKE ? OR a.description LIKE ?)")
        args += (f"%{q_}%",) * 3
    if amtype != "all":
        if amtype == "other":
            conds.append("a.type NOT IN (5,3,4,33,6,2001,2000,19,1)")
        else:
            conds.append("a.type=?")
            args.append(int(amtype))
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    total = rq1(f"SELECT COUNT(*) c FROM AppMessage a {where}", args)["c"]
    rows = rq(f"SELECT a.msgId,a.title,a.description,a.source,a.type,a.xml,"
              f"m.talker,m.createTime FROM AppMessage a LEFT JOIN message m ON m.msgId=a.msgId "
              f"{where} ORDER BY COALESCE(m.createTime,0) DESC LIMIT ? OFFSET ?",
              tuple(args) + (limit, (page - 1) * limit))
    # 类型筛选标签
    tabs = ['<div class="arttabs">']
    for gid, glabel in AM_GROUPS:
        act = ' class="act"' if gid == amtype else ""
        tabs.append(f'<button{act} hx-get="/raw/articles?amtype={gid}' +
                    (f'&q={urlencode_q(q_)}' if q_ else '') +
                    f'" hx-target="#raw-body" hx-swap="innerHTML">{glabel}</button>')
    tabs.append('</div>')
    out = [_raw_head(f"应用消息 ({total})", "AppMessage 微信应用消息卡片 · 公众号/视频/音乐/文件/红包等")]
    out += tabs
    for r in rows:
        title = r["title"] or ""
        xml = r["xml"] or ""
        if not title:
            m = re.search(r"<title>(.*?)</title>", xml, re.S)
            title = m.group(1) if m else ""
        des = r["description"] or ""
        if not des:
            m = re.search(r"<des>(.*?)</des>", xml, re.S)
            des = m.group(1) if m else ""
        src = r["source"] or ""
        t = r["talker"] or ""
        ts = fmt_time(r["createTime"]) if r["createTime"] else ""
        tn = AM_TYPE.get(r["type"], f"类型{r['type']}")
        meta = tn
        if src:
            meta += " · " + src
        if t:
            meta += " · " + t
        if ts:
            meta += " · " + ts
        out.append('<div class="art"><div class="art-t">' + esc(title or "(无标题)") + '</div>'
                   + ('<div class="art-d">' + esc(des) + '</div>' if des else "")
                   + '<div class="art-m"><span class="badge">' + tn + '</span>' + esc(meta) + '</div></div>')
    if not rows:
        out.append('<div class="none">无匹配</div>')
    out.append(_pager(page, limit, total, "/raw/articles?amtype=" + amtype + ("&q=" + urlencode_q(q_) if q_ else "")))
    return "".join(out)


# ---- 群聊 ----
def render_rooms(page=1, q_=""):
    # 原始 chatroom 表在 decrypted.db 中已物理损坏(无法读取), 用 standard.db 群聊会话兜底
    limit = 50
    extra = "AND name LIKE ?" if q_ else ""
    args = (f"%{q_}%",) if q_ else ()
    total = q1(f"SELECT COUNT(*) c FROM sessions WHERE id LIKE '%@chatroom' {extra}", args)["c"]
    rows = q(f"SELECT * FROM sessions WHERE id LIKE '%@chatroom' {extra} ORDER BY name LIMIT ? OFFSET ?",
             args + (limit, (page - 1) * limit))
    out = [_raw_head(f"群聊 ({total})", "chatroom 表原始已损坏 · 用 standard.db 群聊会话兜底")]
    for r in rows:
        name = r["name"] or r["id"]
        mlist = esc(str(name)[:120])
        out.append(
            f'<div class="room"><div class="room-n">{esc(name)}</div>'
            f'<div class="room-m">ID {esc(r["id"])}</div>'
            f'<div class="room-list">{mlist}</div></div>')
    if not rows:
        out.append('<div class="none">无匹配</div>')
    out.append(_pager(page, limit, total, "/raw/rooms?q=" + urlencode_q(q_)))
    return "".join(out)




# ---- 红包 / 转账 ----
def render_money(page=1, kind="all"):
    limit = 30
    # 红包: message type=436207665; 转账: type=419430449; 各 parse 金额/状态
    if kind == "hb":
        cond = "AND m.type=436207665"
    elif kind == "tf":
        cond = "AND m.type=419430449"
    else:
        cond = "AND m.type IN (436207665,419430449)"
    total = rq1(f"SELECT COUNT(*) c FROM message m WHERE 1=1 {cond}")["c"]
    rows = rq(f"SELECT m.msgId,m.talker,m.createTime,m.content FROM message m "
              f"WHERE 1=1 {cond} ORDER BY m.createTime DESC LIMIT ? OFFSET ?",
              (limit, (page - 1) * limit))
    out = [_raw_head(f"红包 / 转账 ({total})", "message 原始 XML · 金额/状态/对方")]
    for r in rows:
        c = r["content"] or ""
        title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", c, re.S)
        des = re.search(r"<des>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</des>", c, re.S)
        amt = re.search(r"(\d+(?:\.\d+)?)元", des.group(1)) if des else None
        amount = amt.group(1) if amt else ""
        t = r["talker"] or ""
        kind_s = "🧧 红包" if r["content"] and "hongbao" in c else "💰 转账"
        out.append(
            f'<div class="mny"><div class="mny-h">{kind_s} <b>{esc(amount)}</b>'
            + (f'<span class="mny-n"> 对方 {esc(t)}</span>' if t else "")
            + f'<span class="mny-t">{fmt_time(r["createTime"])}</span></div>'
            + (f'<div class="mny-d">{esc((des.group(1) if des else "")[:120])}</div>' if des else "")
            + '</div>')
    if not rows:
        out.append('<div class="none">无匹配</div>')
    out.append(_pager(page, limit, total, f"/raw/money?kind={kind}&q="))
    return "".join(out)


# ---- 好友申请 / 文件传输 ----
def render_fmessage(page=1):
    limit = 40
    total = rq1("SELECT COUNT(*) c FROM fmessage_conversation")["c"]
    rows = rq("SELECT * FROM fmessage_conversation ORDER BY lastModifiedTime DESC LIMIT ? OFFSET ?",
              (limit, (page - 1) * limit))
    out = [_raw_head(f"好友申请 / 文件传输 ({total})", "fmessage_conversation")]
    for r in rows:
        out.append(
            f'<div class="ccard"><div class="cav" style="background:{avatar_color(r["displayName"] or "?")}">'
            f'{(r["displayName"] or "?")[0]}</div><div class="cinfo">'
            f'<div class="cname">{esc(r["displayName"] or "-")}</div>'
            f'<div class="csub">{esc(r["contentNickname"] or "")}{(" · " + esc(r["contentPhoneNumMD5"])) if r["contentPhoneNumMD5"] else ""}</div>'
            f'<div class="csig">场景 {r["addScene"]} · {"新" if r["isNew"] else "旧"}</div></div></div>')
    if not rows:
        out.append('<div class="none">无</div>')
    out.append(_pager(page, limit, total, "/raw/fmessage"))
    return "".join(out)


# ---- 媒体库: 缩略图 ----
def render_gallery(page=1):
    limit = 60
    # 直接从文件系统列出真实存在的 image2/th_ 缩略图(9055个), 而非 ImgInfo2(其thumb属另一账号已清理)
    idx = _scan("image2")
    ths = sorted([k for k in idx if k.startswith("th_")])
    total = len(ths)
    page_items = ths[(page - 1) * limit:page * limit]
    out = [_raw_head(f"图片缩略图 ({total})", "image2/th_ 真实存在的缩略图 · 点击放大")]
    out.append('<div class="gal">')
    n = 0
    for f in page_items:
        p = "/media/" + idx[f]
        n += 1
        out.append(f'<a class="gitem" href="{p}" onclick="openLb(this.querySelector(\'img\'));return false"><img class="media" loading="lazy" src="{p}" data-src="{p}" alt=""></a>')
    out.append("</div>")
    if n == 0:
        out.append('<div class="none">无缩略图可显示</div>')
    out.append(_pager(page, limit, total, "/raw/gallery"))
    return "".join(out)




# ---- 用户信息 / 账号 ----
def render_account(page=1):
    limit = 100
    total = rq1("SELECT COUNT(*) c FROM userinfo2")["c"]
    rows = rq("SELECT sid,type,value FROM userinfo2 ORDER BY sid LIMIT ? OFFSET ?",
              (limit, (page - 1) * limit))
    out = [_raw_head(f"用户信息 / 设置 ({total})", "userinfo2 · 微信账号配置键值")]
    out.append('<table class="tbl"><tr><th>键</th><th>值</th></tr>')
    for r in rows:
        out.append(f'<tr><td>{esc(r["sid"])}</td><td>{esc(r["value"])}</td></tr>')
    out.append("</table>")
    out.append(_pager(page, limit, total, "/raw/account"))
    return "".join(out)


# ---- 视频播放历史 ----
def render_playhist(page=1):
    limit = 50
    total = rq1("SELECT COUNT(*) c FROM VideoPlayHistory")["c"]
    rows = rq("SELECT * FROM VideoPlayHistory ORDER BY starttime DESC LIMIT ? OFFSET ?",
              (limit, (page - 1) * limit))
    out = [_raw_head(f"视频播放历史 ({total})", "VideoPlayHistory")]
    for r in rows:
        out.append(
            f'<div class="mny"><div class="mny-h">▶ {esc(r["filename"])}'
            f'<span class="mny-t">{fmt_time(int(r["starttime"]) * 1000) if r["starttime"] else ""}'
            + (f' · {r["playduration"]}s' if r["playduration"] else "") + '</span></div></div>')
    if not rows:
        out.append('<div class="none">无</div>')
    out.append(_pager(page, limit, total, "/raw/playhist"))
    return "".join(out)


# ---- 语音 (voiceinfo → voice2 文件) ----
def render_voices(page=1):
    limit = 40
    total = rq1("SELECT COUNT(*) c FROM voiceinfo")["c"]
    rows = rq("SELECT * FROM voiceinfo ORDER BY CreateTime DESC LIMIT ? OFFSET ?",
              (limit, (page - 1) * limit))
    out = [_raw_head(f"语音 ({total})", "voiceinfo → voice2/msg_*.amr · 时长 VoiceLength")]
    for r in rows:
        p = media_path_exact("voice2", f"msg_{r['FileName']}.amr")
        if not p:
            p = media_path("voice2", r["FileName"])
        dur = int(r["VoiceLength"] or 0) / 1000
        sec = f'{int(dur)}″' if dur else ""
        if p:
            out.append(
                f'<div class="bub v"><button class="vbtn">▶</button>'
                f'<audio hidden preload="none" data-src="{p}"></audio>'
                f'<span class="vt">{sec} · {esc(r["Human"] or r["User"] or "")}</span></div>')
        else:
            out.append(f'<div class="bub">🎤 {sec} · {esc(r["Human"] or r["User"] or "")} <span class="mut">(文件缺失)</span></div>')
    if not rows:
        out.append('<div class="none">无</div>')
    out.append(_pager(page, limit, total, "/raw/voices"))
    return "".join(out)


# ---- 视频 (videoinfo2 → video/*.mp4) ----
def render_rawvideos(page=1):
    limit = 30
    total = rq1("SELECT COUNT(*) c FROM videoinfo2 WHERE filename!=''")["c"]
    rows = rq("SELECT * FROM videoinfo2 WHERE filename!='' ORDER BY createtime DESC LIMIT ? OFFSET ?",
              (limit, (page - 1) * limit))
    out = [_raw_head(f"视频 ({total})", "videoinfo2 → video/*.mp4 · 格子懒加载 · 点击播放")]
    out.append('<div class="vgal">')
    for r in rows:
        fn = r["filename"]
        p = media_path_exact("video", f"{fn}.mp4")
        if not p:
            p = media_path("video", fn)
        dur = int(r["videolength"] or 0) / 1000
        sec = f'{int(dur)}″' if dur else ""
        if p:
            # 懒加载: video不设src, 仅data-src; IntersectionObserver滚入视口才加载
            out.append(
                f'<div class="vitem" data-src="{p}" onclick="vPlay(this)">'
                f'<video preload="none" data-src="{p}" muted playsinline></video>'
                f'<span class="vplay">▶</span>'
                + (f'<span class="vbadge">{sec}</span>' if sec else "")
                + f'<div class="vmeta">{esc(r["user"] or r["human"] or fn)}</div></div>')
        else:
            out.append(f'<div class="vitem miss">{fn} {sec} <span class="mut">(文件缺失)</span></div>')
    out.append('</div>')
    if not rows:
        out.append('<div class="none">无</div>')
    out.append(_pager(page, limit, total, "/raw/videos"))
    return "".join(out)


# ---- 总览 ----
def render_rawhome():
    stats = [
        ("消息", rq1("SELECT COUNT(*) c FROM message")["c"], "message 真全库"),
        ("联系人", rq1("SELECT COUNT(*) c FROM rcontact")["c"], "rcontact"),
        ("公众号文章", rq1("SELECT COUNT(*) c FROM AppMessage")["c"], "AppMessage"),
        ("群聊", rq1("SELECT COUNT(*) c FROM chatroom")["c"], "chatroom"),
        ("红包", rq1("SELECT COUNT(*) c FROM message WHERE type=436207665")["c"], "message"),
        ("转账", rq1("SELECT COUNT(*) c FROM message WHERE type=419430449")["c"], "message"),
        ("好友申请", rq1("SELECT COUNT(*) c FROM fmessage_conversation")["c"], "fmessage"),
        ("图片缩略图", rq1("SELECT COUNT(*) c FROM ImgInfo2 WHERE thumbImgPath LIKE 'THUMBNAIL%'")["c"], "ImgInfo2"),
        ("语音", rq1("SELECT COUNT(*) c FROM voiceinfo")["c"], "voiceinfo"),
        ("视频", rq1("SELECT COUNT(*) c FROM videoinfo2 WHERE filename!=''")["c"], "videoinfo2"),
        ("播放历史", rq1("SELECT COUNT(*) c FROM VideoPlayHistory")["c"], "VideoPlayHistory"),
        ("设置键值", rq1("SELECT COUNT(*) c FROM userinfo2")["c"], "userinfo2"),
    ]
    out = [_raw_head("微信真全库总览", "decrypted.db · 除聊天外的全部可展示内容")]
    out.append('<div class="grid">')
    for name, n, src in stats:
        out.append(f'<div class="stat"><div class="stat-n">{n}</div>'
                   f'<div class="stat-t">{esc(name)}</div><div class="stat-s">{esc(src)}</div></div>')
    out.append("</div>")
    return "".join(out)


# ---- 聊天统计 ----
def render_stats():
    total = rq1("SELECT COUNT(*) c FROM message")["c"]
    sess_n = rq1("SELECT COUNT(DISTINCT talker) c FROM message")["c"]
    # 类型分布
    trows = rq("SELECT type, COUNT(*) n FROM message GROUP BY type ORDER BY n DESC LIMIT 10")
    # 按月趋势
    months = rq("""SELECT strftime('%Y-%m', createTime/1000, 'unixepoch') ym, COUNT(*) n
                   FROM message WHERE createTime>0 GROUP BY ym ORDER BY ym""")
    # 活跃会话 TOP
    top = rq("""SELECT m.talker, COUNT(*) n, MAX(m.createTime) mx
                FROM message m GROUP BY m.talker ORDER BY n DESC LIMIT 10""")
    # 时段分布
    hours = rq("SELECT (createTime/1000/3600)%24 h, COUNT(*) n FROM message WHERE createTime>0 GROUP BY h")

    out = [_raw_head(f"聊天统计", f"message {total} 条 · {sess_n} 个会话")]
    # 类型分布
    out.append('<div class="stats">')
    out.append('<div class="statblock"><div class="sb-t">消息类型分布</div>')
    mx = max([r["n"] for r in trows] or [1])
    for r in trows:
        tn = TYPE_NAME.get(r["type"], f"类型{r['type']}")
        w = int(r["n"] * 100 / mx)
        out.append(f'<div class="hb"><span class="hb-l">{esc(tn)}</span>'
                   f'<span class="hb-bar"><span class="hb-f" style="width:{w}%"></span></span>'
                   f'<span class="hb-n">{r["n"]}</span></div>')
    out.append('</div>')
    # 按月趋势
    out.append('<div class="statblock"><div class="sb-t">按月消息量</div>')
    mxm = max([r["n"] for r in months] or [1])
    for r in months[-24:]:
        w = int(r["n"] * 100 / mxm)
        out.append(f'<div class="hb"><span class="hb-l">{esc(r["ym"])}</span>'
                   f'<span class="hb-bar"><span class="hb-f" style="width:{w}%"></span></span>'
                   f'<span class="hb-n">{r["n"]}</span></div>')
    out.append('</div>')
    # 活跃会话
    out.append('<div class="statblock"><div class="sb-t">活跃会话 TOP10</div>')
    names = {r["username"]: (r["conRemark"] or r["nickname"] or r["username"])
             for r in rq("SELECT username,nickname,conRemark FROM rcontact")}
    for r in top:
        nm = names.get(r["talker"], r["talker"])
        w = int(r["n"] * 100 / (top[0]["n"] if top else 1))
        out.append(f'<div class="hb"><span class="hb-l" title="{esc(r["talker"])}">{esc(nm)}</span>'
                   f'<span class="hb-bar"><span class="hb-f" style="width:{w}%"></span></span>'
                   f'<span class="hb-n">{r["n"]}</span></div>')
    out.append('</div>')
    # 时段分布
    out.append('<div class="statblock"><div class="sb-t">时段分布 (24h)</div>')
    hm = {r["h"]: r["n"] for r in hours}
    mxh = max(hm.values()) if hm else 1
    out.append('<div class="hbars">')
    for h in range(24):
        n = hm.get(h, 0)
        ht = int(n * 100 / mxh) if mxh else 0
        out.append(f'<div class="hbcol" title="{h}时 {n}条">'
                   f'<span class="hbc-f" style="height:{ht}%"></span>'
                   f'<span class="hbc-l">{h}</span></div>')
    out.append('</div></div>')
    out.append('</div>')
    return "".join(out)


# ---- 跨会话全文搜索 ----
def render_search(page=1, kw="", target="#searchpane"):
    limit = 30
    q = kw
    if not q:
        out = [_raw_head("全文搜索", "跨全部会话搜索消息内容 · 点击结果打开会话并定位")]
        out.append('<div class="rawsearch"><input name="q" placeholder="输入关键词搜索所有消息..." '
                   f'hx-get="/raw/search" hx-trigger="input delay:300ms" hx-target="{target}" '
                   'hx-swap="innerHTML"></div>')
        out.append('<div class="none">输入关键词开始搜索（匹配消息内容）</div>')
        return "".join(out)
    total = _sq1("SELECT COUNT(*) c FROM messages WHERE text LIKE ?", (f"%{q}%",))["c"]
    rows = _sq("""SELECT m.id,m.session_id,m.timestamp,m.text,m.type,s.name
                FROM messages m LEFT JOIN sessions s ON s.id=m.session_id
                WHERE m.text LIKE ? ORDER BY m.timestamp DESC LIMIT ? OFFSET ?""",
             (f"%{q}%", limit, (page - 1) * limit))
    out = [_raw_head(f"全文搜索 ({total})", f"关键词「{q}」 · 点击结果打开会话并定位")]
    out.append('<div class="rawsearch"><input name="q" placeholder="输入关键词搜索所有消息..." value="'
               + esc(q) + f'" hx-get="/raw/search" hx-trigger="input delay:300ms" hx-target="{target}" '
               'hx-swap="innerHTML"></div>')
    for r in rows:
        nm = r["name"] or r["session_id"]
        txt = r["text"] or ""
        # 高亮关键词
        hi = txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        hi = re.sub(re.escape(q), f'<mark>{re.escape(q)}</mark>', hi, flags=re.I)
        out.append(f'<div class="hit" onclick="openHit(\'{esc(r["session_id"])}\',{r["id"]})">'
                   f'<div class="hit-h"><span class="hit-n">{esc(nm)}</span>'
                   f'<span class="hit-t">{esc(fmt_short(r["timestamp"]) if r["timestamp"] else "")}</span></div>'
                   f'<div class="hit-c">{hi}</div></div>')
    if not rows:
        out.append('<div class="none">无匹配消息</div>')
    out.append(_pager(page, limit, total, "/raw/search?q=" + quote(q), target))
    return "".join(out)

# ---- 文件传输列表 ----
def render_files(page=1, q=""):
    limit = 50
    total = dq1("SELECT COUNT(*) c FROM appattach")["c"]
    rows = dq("SELECT * FROM appattach ORDER BY createTime DESC LIMIT ? OFFSET ?",
              (limit, (page - 1) * limit))
    out = [_raw_head(f"文件传输 ({total})", "appattach 微信附件记录")]
    out.append('<div class="smslist">')
    for r in rows:
        sz = r["totalLen"] or 0
        def fsz(n):
            for u in ("B", "KB", "MB", "GB"):
                if n < 1024:
                    return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
                n /= 1024
            return f"{n:.1f}TB"
        out.append(f'<div class="sms"><div class="sms-h"><span class="sms-n">{esc(str(r["appId"]))}</span>'
                   f'<span class="sms-t">{esc(fmt_short(r["createTime"]) if r["createTime"] else "")}</span></div>'
                   f'<div class="sms-c">类型 {r["type"]} · 大小 {fsz(sz)} · 媒体ID {esc(str(r["mediaSvrId"]))}</div></div>')
    out.append('</div>')
    if not rows:
        out.append('<div class="none">无附件</div>')
    out.append(_pager(page, limit, total, "/raw/files"))
    return "".join(out)


# ---- 公众号时间线 ----
def render_biztl(page=1, q=""):
    limit = 30
    total = dq1("SELECT COUNT(*) c FROM BizTimeLineInfo")["c"]
    rows = dq("""SELECT b.msgId,b.talker,b.createTime,b.content,b.imgPath,c.nickname,c.conRemark
                 FROM BizTimeLineInfo b LEFT JOIN rcontact c ON c.username=b.talker
                 ORDER BY b.createTime DESC LIMIT ? OFFSET ?""",
              (limit, (page - 1) * limit))
    out = [_raw_head(f"公众号时间线 ({total})", "BizTimeLineInfo 公众号推文流")]
    for r in rows:
        xml = r["content"] or ""
        # BizTimeLineInfo 用微信专有 ~SEMI_XML~ 格式, title 出现在 title\x00之后
        m = re.search(r"<title>(.*?)</title>", xml, re.S)
        if not m:
            m = re.search(r"title[^\w]{1,4}(.{2,180}?)(?=[*.\x00\)])", xml, re.S)
        title = m.group(1) if m else "(无标题)"
        nm = r["conRemark"] or r["nickname"] or r["talker"]
        img = ""
        ip = r["imgPath"] or ""
        if "://" in ip:
            fn = ip.split("://")[-1]
            img = media_path_exact("image2", fn)
        cv = f'<img class="btl-img" src="{img}" loading="lazy">' if img else ""
        out.append(f'<div class="art"><div class="art-t">{esc(title)}</div>'
                   f'<div class="art-m"><span class="badge">推文</span>{esc(nm)} · '
                   f'{esc(fmt_time(r["createTime"]) if r["createTime"] else "")}</div>'
                   f'{cv}</div>')
    if not rows:
        out.append('<div class="none">无推文</div>')
    out.append(_pager(page, limit, total, "/raw/biztl"))
    return "".join(out)


# ---- 孤儿媒体扫描(排除已引用, 7类) ----
_orphan_cache = {"ts": 0, "data": None}

def _orphan_type(fp):
    try:
        with open(fp, "rb") as f:
            head = f.read(16)
    except OSError:
        return "other"
    if head[:3] == b"\xff\xd8\xff":
        return "img"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "img"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "img"
    if head[4:8] == b"ftyp":
        return "video"
    # 微信语音: .amr 实为 silk 编码(头 \x02#!SILK_V3 或 #!SILK)
    if head[:4] == b"RIFF" or b"#!SILK" in head[:8] or head[:3] == b"#!":
        return "audio"
    return "other"

def scan_orphans(force=False):
    """扫描媒体库, 返回 [{label, items:[{src,size,type}]}], 缓存10分钟"""
    import time as _t
    if not force and _orphan_cache["data"] and _t.time() - _orphan_cache["ts"] < 600:
        return _orphan_cache["data"]
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    refs = set()
    try:
        for r in db.execute("SELECT media_path FROM messages WHERE media_path!=''"):
            p = r["media_path"]
            if p.startswith("/media/"):
                refs.add(os.path.normpath(os.path.join(MEDIA_DIR, p[7:].replace("/", os.sep))))
            elif p.startswith("/media2/"):
                refs.add(os.path.normpath(os.path.join(MEDIA2_DIR, p[8:].replace("/", os.sep))))
    finally:
        db.close()
    cats = [("失效图片", [("image2", MEDIA_DIR), ("image", MEDIA_DIR)]),
            ("失效视频", [("video", MEDIA_DIR)]),
            ("失效语音", [("voice2", MEDIA_DIR)]),
            ("失效收藏", [("favorite", MEDIA_DIR)]),
            ("失效封面", [("covers", MEDIA2_DIR)]),
            ("失效音乐", [("music", MEDIA_DIR)]),
            ("失效聊天卡", [("record", MEDIA_DIR)])]
    out = []
    for label, dirs in cats:
        items = []
        for d, base in dirs:
            b = os.path.join(base, d)
            if not os.path.isdir(b):
                continue
            for root, _, fs in os.walk(b):
                for f in fs:
                    fp = os.path.normpath(os.path.join(root, f))
                    if fp in refs:
                        continue
                    try:
                        sz = os.path.getsize(fp)
                    except OSError:
                        continue
                    rel = "/media/" + os.path.relpath(fp, MEDIA_DIR).replace(os.sep, "/")
                    items.append({"src": rel, "name": f, "size": sz, "type": _orphan_type(fp)})
        items.sort(key=lambda x: -x["size"])
        out.append({"label": label, "items": items})
    _orphan_cache["data"] = out
    _orphan_cache["ts"] = _t.time()
    return out


def render_orphans(page=1, cat="all"):
    limit = 60
    data = scan_orphans()
    # 分类标签
    tabs = ['<div class="arttabs">']
    alln = sum(len(c["items"]) for c in data)
    tabs.append(f'<button class="{"act" if cat=="all" else ""}" hx-get="/raw/orphans" hx-target="#raw-body" hx-swap="innerHTML">全部 ({alln})</button>')
    for c in data:
        act = " act" if cat == c["label"] else ""
        tabs.append(f'<button class="{act.strip()}" hx-get="/raw/orphans?cat={c["label"]}" hx-target="#raw-body" hx-swap="innerHTML">{c["label"]} ({len(c["items"])})</button>')
    tabs.append('</div>')
    out = [_raw_head(f"孤儿媒体 ({alln})", "媒体库中无消息引用的文件 · 点击查看")]
    out += tabs
    if cat != "all":
        cur = next((c for c in data if c["label"] == cat), None)
        items = cur["items"] if cur else []
    else:
        items = [i for c in data for i in c["items"]]
    page_items = items[(page - 1) * limit:page * limit]
    if not items:
        out.append('<div class="none">无孤儿媒体</div>')
    out.append('<div class="ogrid">')
    for it in page_items:
        name = esc(it["name"][:40])
        size = f'{it["size"]//1024}KB'
        if it["type"] == "img":
            # 图片格子: 缩略图直接显示, 点击灯箱
            out.append(
                f'<div class="oitem" onclick="openLb(this.querySelector(\'img\'));return false" data-src="{it["src"]}">'
                f'<div class="othumb"><img loading="lazy" src="{it["src"]}" data-src="{it["src"]}" alt=""></div>'
                f'<div class="oname">{name}</div><div class="osub">{size}</div></div>')
        elif it["type"] in ("video", "audio"):
            # 视频/音频格子: 图标, 点击内联自研播放器
            ic = "🎬" if it["type"] == "video" else "🔊"
            out.append(
                f'<div class="oitem" onclick="orphPlay(this,\'{it["src"]}\',\'{it["type"]}\')">'
                f'<div class="othumb dark">{ic}</div>'
                f'<div class="oname">{name}</div><div class="osub">{esc(it["type"])} · {size}</div></div>')
        else:
            # 其他: 图标, 点击新窗口查看
            out.append(
                f'<div class="oitem" onclick="window.open(\'{it["src"]}\')">'
                f'<div class="othumb dark">📄</div>'
                f'<div class="oname">{name}</div><div class="osub">{size}</div></div>')
    out.append('</div>')
    if page_items:
        out.append(_pager(page, limit, len(items), "/raw/orphans?cat=" + cat))
    return "".join(out)


# ---- 短信浏览器(可配置扫描 ExportSMS) ----
def _find_sms_csv():
    d = CONFIG.get("sms_dir", "")
    if not d or not os.path.isdir(d):
        return None
    fs = [f for f in os.listdir(d) if f.lower().endswith(".csv")]
    if not fs:
        return None
    return os.path.join(d, sorted(fs)[-1])


def render_sms(page=1, q="", target="#smspane"):
    import csv as _csv
    limit = 50
    csvp = _find_sms_csv()
    if not csvp:
        return (_raw_head("短信 (无数据)", "ExportSMS 目录无CSV · 在设置里配置短信目录")
                + '<div class="none">未找到短信CSV, 请到设置页配置短信扫描目录</div>')
    rows = []
    try:
        with open(csvp, encoding="utf-8-sig", errors="replace") as f:
            rd = _csv.reader(f)
            next(rd, None)
            for r in rd:
                if len(r) >= 5:
                    rows.append(r)
    except Exception as e:
        return _raw_head("短信 (读取失败)", str(e))
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r[0] or "").lower() or ql in (r[1] or "").lower()
                or ql in (r[2] or "").lower()]
    total = len(rows)
    page_items = rows[(page - 1) * limit:page * limit]
    out = [_raw_head(f"短信 ({total})", "ExportSMS · 可配置扫描目录 · 按号码/内容搜索")]
    out.append('<div class="rawsearch"><input name="q" placeholder="搜索号码/内容..." value="'
               + esc(q) + '" hx-get="/raw/sms" hx-trigger="input delay:300ms" hx-target="' + target + '" hx-swap="innerHTML"></div>')
    out.append('<div class="smslist">')
    for r in page_items:
        src, num, content, tm = (r[0], r[1], r[2], r[3])
        out.append(f'<div class="sms"><div class="sms-h"><span class="sms-n">{esc(num or src)}</span>'
                   f'<span class="sms-t">{esc(tm)}</span></div>'
                   f'<div class="sms-c">{esc(content)}</div></div>')
    out.append('</div>')
    if not page_items:
        out.append('<div class="none">无短信</div>')
    out.append(_pager(page, limit, total, "/raw/sms" + ("?q=" + quote(q) if q else ""), target))
    return "".join(out)


# ---- 手机联系人浏览器(可配置扫描 ExportContact) ----
def _load_phone_contacts():
    import csv as _csv
    d = CONFIG.get("contact_dir", "")
    if not d or not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        fp = os.path.join(d, fn)
        if fn.lower().endswith(".csv"):
            try:
                with open(fp, encoding="utf-8-sig", errors="replace") as f:
                    rd = _csv.reader(f)
                    next(rd, None)
                    for r in rd:
                        if not r:
                            continue
                        name = (r[0] or r[1] or "").strip() if len(r) > 1 else (r[0] or "").strip()
                        phone = r[5].strip() if len(r) > 5 else ""
                        if phone:
                            out.append({"name": name, "phone": phone})
            except Exception:
                pass
        elif fn.lower().endswith(".vcf"):
            try:
                with open(fp, encoding="utf-8-sig", errors="replace") as f:
                    cur = {}
                    for line in f:
                        line = line.strip()
                        if line.upper() == "BEGIN:VCARD":
                            cur = {}
                        elif line.upper() == "END:VCARD":
                            if cur.get("phone"):
                                out.append(cur)
                        elif line.startswith("FN"):
                            cur["name"] = line.split(":", 1)[-1].strip()
                        elif line.startswith("TEL"):
                            cur["phone"] = line.split(":", 1)[-1].strip()
            except Exception:
                pass
    seen, dedup = set(), []
    for c in out:
        if c["phone"] not in seen:
            seen.add(c["phone"])
            dedup.append(c)
    return dedup


def render_phonecontacts(page=1, q="", target="#contactpane"):
    limit = 60
    rows = _load_phone_contacts()
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r["name"] or "").lower() or ql in r["phone"]]
    total = len(rows)
    page_items = rows[(page - 1) * limit:page * limit]
    out = [_raw_head(f"手机联系人 ({total})", "ExportContact · 可配置扫描目录 · CSV+VCF")]
    out.append('<div class="rawsearch"><input name="q" placeholder="搜索姓名/号码..." value="'
               + esc(q) + '" hx-get="/raw/phonecontacts" hx-trigger="input delay:300ms" hx-target="' + target + '" hx-swap="innerHTML"></div>')
    out.append('<div class="ogrid">')
    for r in page_items:
        name = r["name"] or r["phone"]
        out.append(f'<div class="oitem"><div class="othumb">{(name or "?")[0]}</div>'
                   f'<div class="oname">{esc(name[:30])}</div><div class="osub">{esc(r["phone"])}</div></div>')
    out.append('</div>')
    if not page_items:
        out.append('<div class="none">无联系人</div>')
    out.append(_pager(page, limit, total, "/raw/phonecontacts" + ("?q=" + quote(q) if q else ""), target))
    return "".join(out)


# ---- 设置页(每个功能可配置扫描目录) ----
def render_settings(saved=False, target="#settingspane"):
    def inp(label, key, val):
        return (f'<div class="setrow"><label>{esc(label)}</label>'
                f'<input name="{key}" value="{esc(val)}" class="setinp"></div>')
    body = '<div class="settings">'
    body += inp("微信数据目录 (standard.db/decrypted_view.db/wechat_media/media)", "data_dir", CONFIG.get("data_dir", ""))
    body += inp("短信目录 (扫ExportSMS的CSV)", "sms_dir", CONFIG.get("sms_dir", ""))
    body += inp("联系人目录 (扫ExportContact的CSV/VCF)", "contact_dir", CONFIG.get("contact_dir", ""))
    body += ('<button class="pg" hx-get="/raw/settings?save=1" hx-include="closest .settings" '
             'hx-target="' + target + '" hx-swap="innerHTML">保存配置</button>')
    body += '</div>'
    out = [_raw_head("设置", "每个功能扫描的可配置目录 · config.json")]
    if saved:
        out.append('<div class="none" style="color:var(--acc)">✓ 已保存并重载</div>')
    out.append(body)
    return "".join(out)

RAW_TABS = [
    ("home", "总览", "/raw/home"),
    ("contacts", "联系人", "/raw/contacts"),
    ("articles", "公众号", "/raw/articles"),
    ("rooms", "群聊", "/raw/rooms"),
    ("money", "红包转账", "/raw/money"),
    ("fmessage", "好友申请", "/raw/fmessage"),
    ("gallery", "图片", "/raw/gallery"),
    ("voices", "语音", "/raw/voices"),
    ("videos", "视频", "/raw/videos"),
    ("orphans", "孤儿媒体", "/raw/orphans"),
    ("files", "文件", "/raw/files"),
    ("biztl", "推文", "/raw/biztl"),
    ("account", "账号", "/raw/account"),
]


def render_raw(section, page=1, q="", amtype="all"):
    try:
        page = max(1, int(page))
    except Exception:
        page = 1
    if section == "contacts":
        return render_contacts(page, q)
    if section == "articles":
        return render_articles(page, q, amtype)
    if section == "rooms":
        return render_rooms(page, q)
    if section == "money":
        return render_money(page, q)
    if section == "fmessage":
        return render_fmessage(page)
    if section == "gallery":
        return render_gallery(page)
    if section == "voices":
        return render_voices(page)
    if section == "videos":
        return render_rawvideos(page)
    if section == "playhist":
        return render_playhist(page)
    if section == "orphans":
        return render_orphans(page, q or "all")
    if section == "files":
        return render_files(page, q)
    if section == "biztl":
        return render_biztl(page, q)
    if section == "sms":
        return render_sms(page, q)
    if section == "phonecontacts":
        return render_phonecontacts(page, q)
    if section == "settings":
        return render_settings(q == "1")
    if section == "search":
        return render_search(page, q)
    if section == "stats":
        return render_stats()

    if section == "account":
        return render_account(page)
    return render_rawhome()



# ---------- 页面骨架 ----------
INDEX = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>聊天记录浏览器</title>
<script src="/static/htmx.min.js"></script>
<style>
:root{--bg:#f5f5f5;--side:#f7f7f7;--bd:#e5e5e5;--mine:#95ec69;--txt:#111;--mut:#999;--acc:#07c160}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei",sans-serif;background:var(--bg);color:var(--txt);height:100vh;overflow:hidden;display:flex;flex-direction:column}
#app{display:flex;flex:1;min-height:0}
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
#chh #chname{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
#chh #chname:hover{white-space:normal;overflow:visible}
#chh .ct{font-weight:normal;font-size:12px;color:var(--mut)}
#messages{flex:1;overflow-y:auto;overflow-x:hidden;min-height:0;padding:16px 10% 30px;scrollbar-width:thin}
#messages::-webkit-scrollbar{width:8px}
#messages::-webkit-scrollbar-thumb{background:#c8c8c8;border-radius:4px}
#messages::-webkit-scrollbar-thumb:hover{background:#aaa}
.tg{text-align:center;margin:14px 0;color:var(--mut);font-size:12px}
.tg span{background:#e8e8e8;padding:3px 10px;border-radius:4px}
.msg{display:flex;margin:8px 0;gap:8px;align-items:flex-start}
.msg.mine{flex-direction:row-reverse}
.mav{width:36px;height:36px;border-radius:4px;flex-shrink:0;font-size:14px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:500;user-select:none}
.mb{max-width:65%;display:flex;flex-direction:column}
.msg.mine .mb{align-items:flex-end}
.mn{font-size:11px;color:var(--mut);margin-bottom:2px;max-width:150px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer;outline:none}
.mn:focus{white-space:normal;overflow:visible;text-overflow:clip}
.bub{padding:8px 12px;border-radius:6px;font-size:14px;line-height:1.55;word-break:break-word;box-shadow:0 1px 1px rgba(0,0,0,.05);background:#fff}
.quote{font-size:12px;color:var(--mut);background:#f2f2f2;border-left:3px solid #ddd;border-radius:4px;padding:4px 8px;margin-bottom:4px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
.quote:hover{white-space:normal;overflow:visible}
.hb{display:flex;align-items:center;gap:10px;background:linear-gradient(135deg,#ff6a3d,#f74f2e);border-radius:8px;padding:10px 14px;max-width:280px;text-decoration:none;color:#fff;box-shadow:0 1px 2px rgba(0,0,0,.12)}
.hb .hb-ic{font-size:26px;flex-shrink:0}
.hb .hb-tx{font-size:14px;line-height:1.4;word-break:break-word}
.msg.mine .hb{background:linear-gradient(135deg,#ff5a2c,#e8441f)}
.card{display:flex;gap:9px;background:#fff;border:1px solid var(--bd);border-radius:8px;padding:10px;max-width:300px;text-decoration:none;color:var(--txt);box-shadow:0 1px 1px rgba(0,0,0,.05)}
.card .cc{width:88px;height:88px;object-fit:cover;border-radius:4px;flex-shrink:0;background:#eee}
.card .cb{min-width:0;display:flex;flex-direction:column;gap:3px}
.card .ct{font-size:14px;line-height:1.4;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .cd{font-size:12px;color:var(--mut);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .cs{font-size:11px;color:var(--mut);margin-top:auto}
.msg.mine .bub{background:var(--mine)}
.msg.sys .bub{background:none;box-shadow:none;color:var(--mut);font-size:12px}
.mt{font-size:11px;color:var(--mut);margin-top:3px}
.media{border-radius:6px;max-width:260px;max-height:280px;display:block;cursor:zoom-in;background:#eee}
.media.em{max-width:120px;max-height:120px}
.bub.miss{background:#eee;color:#999;font-size:13px}
.bub.link{background:#fff;border:1px solid var(--bd)}
.bub.v{display:flex;align-items:center;gap:8px;padding:8px 10px}
.bub.v .vbtn{flex:none;width:34px;height:34px;border-radius:50%;background:var(--acc);color:#fff;border:none;font-size:14px;cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:1}
.bub.v .vt{font-size:12px;color:var(--mut);white-space:nowrap}
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
/* ---------- 真全库板块样式 ---------- */
#topnav{display:flex;background:var(--side);border-bottom:1px solid var(--bd);overflow-x:auto;flex-shrink:0}
.tnav{padding:10px 14px;border:none;background:none;cursor:pointer;font-size:13px;color:var(--mut);white-space:nowrap;border-bottom:2px solid transparent;flex-shrink:0}
.tnav:hover{color:var(--txt)}
.tnav.act{color:var(--acc);border-bottom-color:var(--acc);font-weight:bold}
.rpane{flex:1;overflow-y:auto;min-height:0;padding:14px 16px 40px}
.rpane .rawhead{margin-bottom:14px}
.rpane .rawtitle{font-size:16px;font-weight:bold;color:var(--txt)}
.rpane .rawsub{font-size:12px;color:var(--mut);margin-top:2px}
.rpane .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.rpane .stat{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:14px}
.rpane .stat-n{font-size:24px;font-weight:bold;color:var(--acc)}
.rpane .stat-t{font-size:14px;margin-top:2px}
.rpane .stat-s{font-size:11px;color:var(--mut)}
.rpane .ccard{display:flex;gap:10px;background:#fff;border:1px solid var(--bd);border-radius:8px;padding:10px;align-items:flex-start}
.rpane .cav{width:36px;height:36px;border-radius:50%;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:bold;flex-shrink:0;font-size:14px}
.rpane .cinfo{min-width:0;flex:1}
.rpane .cname{font-size:14px;font-weight:500}
.rpane .csub{font-size:11px;color:var(--mut);margin-top:1px;word-break:break-all}
.rpane .orph-player{margin-top:8px;width:100%}
.rpane .orph-player video{width:100%;max-height:240px;border-radius:6px;background:#000}
.rpane .orph-player audio{width:100%;border-radius:6px}
.rpane .orph-player .bub.v{margin:0;background:#f0f0f0}
.rpane .csig{font-size:12px;color:#666;margin-top:3px}
.rpane .badge{display:inline-block;background:#e8f5e9;color:#2e7d32;border-radius:3px;padding:1px 5px;font-size:10px;font-weight:normal;margin-left:4px;vertical-align:middle}
.rpane .art{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:12px;margin-bottom:10px}
.rpane .arttabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.rpane .arttabs button{background:#fff;border:1px solid var(--bd);border-radius:20px;padding:4px 12px;font-size:12px;cursor:pointer;color:var(--txt)}
.rpane .arttabs button.act{background:var(--acc);border-color:var(--acc);color:#fff}
.rpane .arttabs button:hover{border-color:var(--acc)}
.rpane .art-t{font-size:14px;font-weight:500;line-height:1.4}
.rpane .art-d{font-size:12px;color:#666;margin-top:4px;line-height:1.5}
.rpane .art-m{font-size:11px;color:var(--mut);margin-top:6px}
.rpane .room{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:12px;margin-bottom:10px}
.rpane .room-n{font-size:14px;font-weight:500}
.rpane .room-m{font-size:12px;color:var(--mut);margin-top:3px}
.rpane .room-list{font-size:12px;color:#555;margin-top:5px;word-break:break-all}
.rpane .room-notice{font-size:12px;color:#888;margin-top:5px;background:#f7f7f7;border-radius:4px;padding:6px 8px}
.rpane .mny{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:10px 12px;margin-bottom:8px}
.rpane .mny-h{font-size:14px}
.rpane .mny-h b{color:#e5484d}
.rpane .mny-n{font-size:12px;color:#555;margin-left:6px}
.rpane .mny-t{font-size:11px;color:var(--mut);float:right}
.rpane .mny-d{font-size:12px;color:#666;margin-top:4px}
.rpane .gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:6px}
.rpane .gitem{display:block;aspect-ratio:1;background:#eee;border-radius:4px;overflow:hidden}
.rpane .gitem img{width:100%;height:100%;object-fit:cover;display:block}
.rpane .vgal{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
.rpane .vitem{position:relative;aspect-ratio:16/9;background:#000;border-radius:6px;overflow:hidden;cursor:pointer}
.rpane .vitem video{width:100%;height:100%;object-fit:contain;display:block;background:#000}
.rpane .vitem .vplay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:38px;color:#fff;text-shadow:0 2px 10px rgba(0,0,0,.7);pointer-events:none;transition:opacity .2s}
.rpane .vitem:hover .vplay{opacity:.7}
.rpane .vitem .vbadge{position:absolute;right:6px;bottom:28px;background:rgba(0,0,0,.75);color:#fff;font-size:11px;padding:2px 6px;border-radius:4px}
.rpane .vitem .vmeta{position:absolute;left:0;right:0;bottom:0;padding:3px 6px;font-size:11px;color:#ddd;background:linear-gradient(transparent,rgba(0,0,0,.7));white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rpane .vitem.miss{display:flex;align-items:center;justify-content:center;color:#999;font-size:12px;background:#f5f5f5}
.rpane .ogrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
.rpane .oitem{background:#fff;border:1px solid var(--bd);border-radius:6px;overflow:hidden;cursor:pointer;transition:box-shadow .15s}
.rpane .oitem:hover{box-shadow:0 2px 10px rgba(0,0,0,.12)}
.rpane .othumb{aspect-ratio:1;background:#eee;display:flex;align-items:center;justify-content:center;font-size:34px;overflow:hidden}
.rpane .othumb img{width:100%;height:100%;object-fit:cover;display:block}
.rpane .othumb.dark{background:#2a2a2a;color:#fff}
.rpane .oname{font-size:11px;padding:4px 6px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rpane .osub{font-size:10px;color:var(--mut);padding:0 6px 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rpane .mv{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:10px;margin-bottom:10px}
.rpane .mv video{width:100%;max-height:260px;border-radius:6px;background:#000}
.rpane .mv-m{font-size:12px;color:var(--mut);margin-top:5px}
.rpane .mv.miss{font-size:13px;color:#999;padding:8px}
.rpane .tbl{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--bd);border-radius:8px;font-size:12px}
.rpane .tbl th,.rpane .tbl td{text-align:left;padding:6px 10px;border-bottom:1px solid #f0f0f0;vertical-align:top}
.rpane .tbl th{background:var(--side);font-weight:500;color:#555;position:sticky;top:0}
.rpane .tbl td:first-child{color:var(--mut);word-break:break-all;max-width:45%}
.rpane .pager{display:flex;gap:10px;align-items:center;justify-content:center;margin-top:16px}
.rpane .pg{background:#fff;border:1px solid var(--bd);border-radius:6px;padding:6px 14px;cursor:pointer;font-size:13px}
.rpane .pg:hover{border-color:var(--acc);color:var(--acc)}
.rpane .pg.act{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:bold}
.rpane .pg:disabled{opacity:.4;cursor:default}
.rpane .pgd{color:var(--mut);padding:0 2px;font-size:13px}
.rpane .pgjump{width:64px;padding:5px 8px;border:1px solid var(--bd);border-radius:6px;font-size:13px;outline:none}
.rpane .pgjump:focus{border-color:var(--acc)}
.rpane .pgj{padding:6px 10px}
.rpane .pgi{font-size:12px;color:var(--mut)}
.rpane .rawsearch{margin-bottom:12px;display:flex;gap:8px}
.rpane .rawsearch input{flex:1;max-width:320px;padding:8px 12px;border:1px solid var(--bd);border-radius:6px;font-size:13px;outline:none}
.rpane .rawsearch input:focus{border-color:var(--acc)}
.rpane .mut{color:var(--mut)}
.rpane .bub.v{margin-bottom:6px}
.rpane .bub{margin-bottom:6px}
.rpane .smslist{background:#fff;border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.rpane .sms{border-bottom:1px solid #f0f0f0;padding:8px 12px}
.rpane .sms:last-child{border-bottom:none}
.rpane .sms-h{display:flex;justify-content:space-between;gap:10px;align-items:center}
.rpane .sms-n{font-size:13px;font-weight:500}
.rpane .sms-t{font-size:11px;color:var(--mut);flex-shrink:0}
.rpane .sms-c{font-size:12px;color:#555;margin-top:3px;line-height:1.5;word-break:break-all}
.rpane .settings{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:14px;max-width:560px}
.rpane .setrow{margin-bottom:12px}
.rpane .setrow label{display:block;font-size:12px;color:#555;margin-bottom:4px}
.rpane .setinp{width:100%;padding:8px 12px;border:1px solid var(--bd);border-radius:6px;font-size:13px;outline:none;box-sizing:border-box}
.rpane .setinp:focus{border-color:var(--acc)}
/* 统计 */
.rpane .stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:12px}
.rpane .statblock{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:14px}
.rpane .sb-t{font-size:13px;font-weight:bold;margin-bottom:10px}
.rpane .hb{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:12px}
.rpane .hb-l{width:110px;text-align:right;color:#555;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0}
.rpane .hb-bar{flex:1;height:14px;background:#f0f0f0;border-radius:3px;overflow:hidden}
.rpane .hb-f{display:block;height:100%;background:var(--acc);border-radius:3px;min-width:2px}
.rpane .hb-n{width:60px;color:var(--mut);flex-shrink:0}
.rpane .hbars{display:flex;align-items:flex-end;gap:3px;height:120px;padding-top:8px}
.rpane .hbcol{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.rpane .hbc-f{width:100%;background:var(--acc);border-radius:2px 2px 0 0;min-height:2px}
.rpane .hbc-l{font-size:9px;color:var(--mut);margin-top:3px}
/* 全文搜索结果 */
.rpane .hit{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer;transition:box-shadow .15s}
.rpane .hit:hover{box-shadow:0 2px 10px rgba(0,0,0,.12)}
.rpane .hit-h{display:flex;justify-content:space-between;gap:10px;align-items:center}
.rpane .hit-n{font-size:13px;font-weight:500}
.rpane .hit-t{font-size:11px;color:var(--mut);flex-shrink:0}
.rpane .hit-c{font-size:12px;color:#555;margin-top:3px;line-height:1.5;word-break:break-all}
.rpane .hit-c mark{background:#fff3a0;border-radius:2px;padding:0 2px}
.rpane .btl-img{width:120px;height:80px;object-fit:cover;border-radius:4px;margin-top:8px;background:#eee}

</style></head>
<body>
<nav id="topnav">
 <button class="tnav act" id="tab-chat" onclick="switchMode('chat')">💬 聊天</button>
 <button class="tnav" id="tab-raw" onclick="switchMode('raw')">📚 全库</button>
 <button class="tnav" id="tab-sms" onclick="switchMode('sms')">✉️ 短信</button>
 <button class="tnav" id="tab-contacts" onclick="switchMode('contacts')">👥 联系人</button>
 <button class="tnav" id="tab-search" onclick="switchMode('search')">🔍 搜索</button>
 <button class="tnav" id="tab-stats" onclick="switchMode('stats')">📊 统计</button>
 <button class="tnav" id="tab-settings" onclick="switchMode('settings')">⚙️ 设置</button>
</nav>
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
<div id="rawpane" class="rpane" style="display:none"></div>
<div id="smspane" class="rpane" style="display:none"></div>
<div id="contactpane" class="rpane" style="display:none"></div>
<div id="settingspane" class="rpane" style="display:none"></div>
<div id="searchpane" class="rpane" style="display:none"></div>
<div id="statspane" class="rpane" style="display:none"></div>
<script>
const RAW_TABS = [
 ["home","总览","/raw/home"],["contacts","联系人","/raw/contacts"],["articles","公众号","/raw/articles"],
 ["rooms","群聊","/raw/rooms"],["money","红包转账","/raw/money"],["fmessage","好友申请","/raw/fmessage"],
 ["gallery","图片","/raw/gallery"],["voices","语音","/raw/voices"],["videos","视频","/raw/videos"],
 ["playhist","播放历史","/raw/playhist"],["orphans","孤儿媒体","/raw/orphans"],
 ["files","文件","/raw/files"],["biztl","推文","/raw/biztl"],
 ["account","账号","/raw/account"]];
let _rawCur = "home";
function switchMode(m){
  document.querySelectorAll('#topnav .tnav').forEach(b=>b.classList.toggle('act', b.id==='tab-'+m));
  const panes = {chat:'app', raw:'rawpane', sms:'smspane', contacts:'contactpane',
                 search:'searchpane', stats:'statspane', settings:'settingspane'};
  const loaders = {raw:()=>loadRaw('home'), sms:()=>loadPane('smspane','/raw/sms'),
                   contacts:()=>loadPane('contactpane','/raw/phonecontacts'),
                   search:()=>loadPane('searchpane','/raw/search'),
                   stats:()=>loadPane('statspane','/raw/stats'),
                   settings:()=>loadPane('settingspane','/raw/settings')};
  for(const k in panes){
    const el=document.getElementById(panes[k]);
    if(el) el.style.display = (m===k) ? (k==='chat'?'flex':'block') : 'none';
  }
  if(loaders[m]){
    const el=document.getElementById(panes[m]);
    if(el && !el.dataset.loaded){ el.dataset.loaded="1"; loaders[m](); }
  }
}
// 全文搜索结果 → 打开会话并定位到该消息
async function openHit(sid, msgId){
  switchMode('chat');
  const mm=document.getElementById('messages');
  mm.innerHTML='<div class="loading">加载中…</div>';
  try{
    const r=await fetch('/session?id='+encodeURIComponent(sid)+'&focus='+msgId);
    mm.innerHTML=await r.text();
    document.getElementById('chname').textContent=sid;
    const f=document.querySelector('[data-mid="'+msgId+'"]');
    if(f){ f.scrollIntoView({block:'center'}); }
  }catch(e){ mm.innerHTML='<div class="none">加载失败</div>'; }
}
async function loadPane(id, url){
  const el=document.getElementById(id);
  if(!el) return;
  el.innerHTML = '<div class="loading">加载中…</div>';
  try{
    const r=await fetch(url); el.innerHTML = await r.text();
    if(window.htmx) htmx.process(el);
  }catch(e){ el.innerHTML = '<div class="none">加载失败: '+e+'</div>'; }
}
function rawTabs(active){
  let h = '<div class="rawsearch">';
  h += '<input placeholder="搜索…" name="q" value="" '
     + 'hx-get="' + tabUrl(active) + '" hx-trigger="input delay:300ms" hx-target="#raw-body" hx-swap="innerHTML">';
  h += '</div><div class="rawtabs">';
  for(const [id,label,url] of RAW_TABS){
    h += `<button class="tnav${id===active?' act':''}" onclick="loadRaw('${id}')">${label}</button>`;
  }
  h += '</div><div id="raw-body" hx-get="'+tabUrl(active)+'" hx-trigger="load"></div>';
  return h;
}
function tabUrl(sec){
  const t = RAW_TABS.find(x=>x[0]===sec); return t ? t[2] : "/raw/home";
}
async function loadRaw(sec){
  _rawCur = sec;
  const rp = document.getElementById('rawpane');
  rp.innerHTML = rawTabs(sec);
  rp.querySelectorAll('.tnav').forEach(b=>{ if(b.getAttribute('onclick')!=='') b.style.cursor='pointer'; });
  if (window.htmx) htmx.process(rp);
}
// 分页跳转: 输入页码后跳到指定页(htmx局部加载#raw-body)
function pgJump(btn, url, maxPage){
  const inp=btn.previousElementSibling;
  let p=parseInt(inp.value,10)||1;
  p=Math.min(maxPage, Math.max(1, p));
  const sep=url.includes('?')?'&':'?';
  const pane=btn.closest('#rawpane,#smspane,#contactpane,#settingspane');
  const tgt=pane?('#'+pane.id):'#raw-body';
  if(window.htmx) htmx.ajax('GET', url+sep+'page='+p, {target:tgt, swap:'innerHTML'});
  else location.href=url+sep+'page='+p;
}
// 孤儿媒体格子: 内联复用主功能区播放器(视频原生controls / 语音silk解码 / 音乐audio)
function orphPlay(link, src, type){
  const card=link.closest('.ccard,.oitem');
  if(!card) return;
  let p=card.querySelector('.orph-player');
  if(p){ p.remove(); return; }  // 再点收起(不影响格子其他内容)
  const d=document.createElement('div'); d.className='orph-player';
  if(type==='video'){
    d.innerHTML=`<video controls autoplay src="${src}"></video>`;
  }else if(type==='audio'){
    if(src.toLowerCase().endsWith('.silk') || src.toLowerCase().endsWith('.amr')){
      d.innerHTML=`<div class="bub v"><button class="vbtn">▶</button><audio hidden preload="none" data-src="${src}"></audio><span class="vt">语音</span></div>`;
      card.appendChild(d);
      playVoice(d.querySelector('.bub'));
      d.addEventListener('click',e=>e.stopPropagation());
      return;
    }
    d.innerHTML=`<audio controls autoplay src="${src}"></audio>`;
  }
  d.addEventListener('click',e=>e.stopPropagation());  // 播放器内点击不触发收起
  card.appendChild(d);
}
// 视频格子: 点击播放(懒加载后)
function vPlay(item){
  const v=item.querySelector('video');
  if(!v) return;
  if(!v.src && item.dataset.src) v.src=item.dataset.src;
  v.controls=true;
  v.play().catch(()=>{});
}
// 视频懒加载: IntersectionObserver 滚入视口才设src(不一次性全加载)
function initVLazy(scope){
  scope=scope||document;
  const items=scope.querySelectorAll('.vitem[data-src]:not([data-vinit])');
  if(!items.length) return;
  if(!('IntersectionObserver' in window)){
    items.forEach(i=>{const v=i.querySelector('video'); if(v&&i.dataset.src&&!v.src) v.src=i.dataset.src;});
    return;
  }
  const io=new IntersectionObserver(es=>{
    es.forEach(e=>{
      if(e.isIntersecting){
        const v=e.target.querySelector('video');
        if(v&&e.target.dataset.src&&!v.src){ v.src=e.target.dataset.src; v.load(); }
        io.unobserve(e.target);
      }
    });
  },{rootMargin:'300px'});
  items.forEach(i=>{ i.dataset.vinit=1; io.observe(i); });
}

console.log('wechat-viewer v5: 语音silk-wasm解码版');
let _silkMod=null;
async function loadSilk(){
  if(!_silkMod) _silkMod = await import('/static/silk/index.mjs');
  return _silkMod;
}
function pcmToWav(pcm, sr){
  const n=pcm.length>>1, h=44, out=new Uint8Array(h+n*2);
  const dv=new DataView(out.buffer);
  out.set([82,73,70,70],0); dv.setUint32(4,36+n*2,true); out.set([87,65,86,69],8);
  out.set([102,109,116,32],12); dv.setUint32(16,16,true); dv.setUint16(20,1,true); dv.setUint16(22,1,true);
  dv.setUint32(24,sr,true); dv.setUint32(28,sr*2,true); dv.setUint16(32,2,true); dv.setUint16(34,16,true);
  out.set([100,97,116,97],36); dv.setUint32(40,n*2,true); out.set(pcm.subarray(0,n*2),44);
  return out;
}
async function playVoice(bub){
  const audio = bub.querySelector('audio');
  const btn = bub.querySelector('.vbtn');
  if(!audio || !btn || audio.dataset.err) return;
  if(audio.src){  // 已解码: 切换播放/暂停
    if(audio.paused){ audio.play().catch(()=>{}); btn.textContent='⏸'; }
    else { audio.pause(); btn.textContent='▶'; }
    return;
  }
  const url=audio.dataset.src; if(!url) return;
  if(audio.dataset.loading) return;  // 解码中防重
  audio.dataset.loading = 1;
  try{
    const buf=await (await fetch(url)).arrayBuffer();
    const silk=await loadSilk();
    const {data,duration}=await silk.decode(buf,24000);
    const wav=pcmToWav(data,24000);
    audio.src=URL.createObjectURL(new Blob([wav],{type:'audio/wav'}));
    if(duration) bub.querySelector('.vt').textContent=Math.round(duration/1000)+"″";
    await audio.play();
    btn.textContent='⏸';
    audio.onended=()=>{ btn.textContent='▶'; };
  }catch(e){ audio.dataset.err=1; audio.dataset.loading=0; bub.querySelector('.vt').textContent='解码失败:'+String(e).slice(0,60); }
}
// 捕获级 pointerdown: 点击语音气泡任意处(含自绘播放按钮)都触发
document.addEventListener('pointerdown', (e) => {
  const bub = e.composedPath().find(el => el && el.classList && el.classList.contains('bub'));
  if(bub){ playVoice(bub); }
}, true);

function scrollBottom(){setTimeout(()=>{const e=document.getElementById("messages");e.scrollTop=e.scrollHeight},400)}
function selSess(name,n){document.getElementById("chname").textContent=name;
 document.getElementById("chh").querySelector(".ct").textContent=n+" 条"}
function beforeLoad(){const e=document.getElementById("messages");
 window._st=e.scrollTop; window._sh=e.scrollHeight}
function afterLoad(){const e=document.getElementById("messages");
 setTimeout(()=>{e.scrollTop=window._st+(e.scrollHeight-window._sh)},250)}
document.addEventListener('DOMContentLoaded',()=>{
 const m=document.getElementById("messages");
 // 滚动条已在顶部时, 滚轮向上滚一次(wheel deltaY<0)触发一次加载
 m.addEventListener('wheel',(e)=>{
   if(m.scrollTop<=8 && e.deltaY<0){
     const lm=document.getElementById("loadmore");
     if(lm&&!lm.dataset.loading){lm.dataset.loading=1; htmx.trigger(lm,'click')}
   }
 }, {passive:true});
 // loadmore 每次加载完后允许再次触发
 document.body.addEventListener('htmx:afterSwap',()=>{setTimeout(()=>{const lm=document.getElementById("loadmore"); if(lm) delete lm.dataset.loading; initVLazy(document.getElementById('raw-body'));},600)});
});
// ---------- lightbox 图片浏览器 ----------
const lb = { list:[], idx:0, scale:1, tx:0, ty:0 };
function openLb(el){
  if(!el||!el.dataset||!el.dataset.src)return;
  // 复用主功能区灯箱: 收集点击元素所在区域(#messages聊天 或 #raw-body全库)的所有图片
  const scope=el.closest('#messages,#raw-body')||document;
  lb.list=[...scope.querySelectorAll('img[data-src]')].map(i=>i.dataset.src);
  if(!lb.list.includes(el.dataset.src)) lb.list=[el.dataset.src];
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
        ".silk":"audio/silk",".js":"application/javascript",".html":"text/html",
        ".mjs":"application/javascript",".wasm":"application/wasm"}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="text/html; charset=utf-8", status=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


    def do_GET(self):
        u = urlparse(self.path)
        path, params = u.path, parse_qs(u.query)
        try:
            if path == "/favicon.ico":
                return self.send(b"", "image/x-icon", 204)
            if path == "/":
                return self.send(INDEX)
            if path == "/static/htmx.min.js":
                with open(os.path.join(BASE, "static", "htmx.min.js"), "rb") as f:
                    return self.send(f.read(), "application/javascript")
            if path.startswith("/static/"):
                rel = path[len("/static/"):].replace("/", os.sep)
                full = os.path.join(BASE, "static", rel)
                if os.path.isfile(full):
                    ctype = MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
                    with open(full, "rb") as f:
                        return self.send(f.read(), ctype)
            if path.startswith("/raw/"):
                sec = path[len("/raw/"):] or "home"
                if sec == "home":
                    return self.send(render_rawhome())
                page = max(1, int((params.get("page") or ["1"])[0]))
                q_ = (params.get("q") or [""])[0]
                amtype = (params.get("amtype") or ["all"])[0]
                cat = (params.get("cat") or ["all"])[0]
                if sec == "money":
                    kind = (params.get("kind") or ["all"])[0]
                    return self.send(render_money(page, kind))
                if sec == "fmessage":
                    return self.send(render_fmessage(page))
                if sec == "gallery":
                    return self.send(render_gallery(page))
                if sec == "voices":
                    return self.send(render_voices(page))
                if sec == "videos":
                    return self.send(render_rawvideos(page))
                if sec == "playhist":
                    return self.send(render_playhist(page))
                if sec == "settings":
                    if (params.get("save") or [""])[0] == "1":
                        new = {}
                        for k in ("data_dir", "sms_dir", "contact_dir"):
                            v = (params.get(k) or [""])[0]
                            if v:
                                new[k] = v
                        try:
                            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                                json.dump(new, f, ensure_ascii=False, indent=2)
                            load_config()
                            return self.send(render_settings(True))
                        except Exception as e:
                            return self.send(render_settings(False) + f'<div class="none">保存失败: {esc(str(e))}</div>')
                    return self.send(render_settings(False))
                if sec == "account":
                    return self.send(render_account(page))
                return self.send(render_raw(sec, page, cat if sec == "orphans" else q_, amtype))
            if path == "/sessions":
                return self.send(render_sessions((params.get("q") or [""])[0]))
            if path == "/session":
                sid = (params.get("id") or [""])[0]
                before = (params.get("before") or [None])[0]
                focus = (params.get("focus") or [None])[0]
                limit = int((params.get("limit") or ["10"])[0])
                s = q1("SELECT name FROM sessions WHERE id=?", (sid,))
                if s:
                    n = q1("SELECT COUNT(*) c FROM messages WHERE session_id=?", (sid,))["c"]
                    self.send(f'<script>selSess({esc(s["name"])!r},{n});</script>'
                              + render_messages(sid, before, limit, focus))
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
                ctype = MIME.get(os.path.splitext(full)[1].lower(), "")
                if not ctype:
                    # 无扩展名: 按内容识别 (th_ 缩略图/emoji 等)
                    with open(full, "rb") as fh:
                        head = fh.read(16)
                    if head[:3] == b"\xff\xd8\xff":
                        ctype = "image/jpeg"
                    elif head[:8] == b"\x89PNG\r\n\x1a\n":
                        ctype = "image/png"
                    elif head[:6] in (b"GIF87a", b"GIF89a"):
                        ctype = "image/gif"
                    elif head[:4] == b"RIFF":
                        ctype = "audio/amr"
                    elif head[4:8] == b"ftyp":
                        ctype = "video/mp4"
                    else:
                        ctype = "application/octet-stream"
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
