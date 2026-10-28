# -*- coding: utf-8 -*-
"""导入 decrypted.db(微信7.0.17) -> standard.db(标准结构)
标准 schema: contacts/sessions/messages —— 以后微信/QQ各版本都往这套表导入。
"""
import sqlite3, re, os, glob, sys, time

BASE = r"C:/Users/a1/wechat-viewer"
DATA = r"C:/Users/a1/Documents/HiSuite"
SRC = os.path.join(DATA, "decrypted.db")
MEDIA = os.path.join(DATA, "wechat_media")
DST = os.path.join(DATA, "standard.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts(
  id TEXT PRIMARY KEY, name TEXT, remark TEXT, avatar TEXT, type TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, name TEXT, type TEXT, avatar TEXT, member_count INTEGER);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT, session_id TEXT, direction TEXT, sender TEXT, sender_name TEXT,
  timestamp INTEGER, type TEXT, text TEXT,
  media_path TEXT, media_thumb TEXT, media_duration REAL, reply_to TEXT);
CREATE INDEX IF NOT EXISTS idx_msg_sess ON messages(session_id, timestamp);
"""

def type_map(t):
    return {1:"text",3:"image",34:"voice",43:"video",47:"emoji",
            49:"link",48:"location",10000:"system",285212721:"system"}.get(t,"unknown")

MEDIA2 = os.path.join(DATA, "media")   # 第二个图片缓存目录(微信 xx/yy/{md5}.jpg+.thumb.jpg)

def build_media_index():
    """全量 basename -> 完整 URL(/media/ 或 /media2/)。两目录并集, O(1) 查询。"""
    idx = {}
    for base, prefix in ((MEDIA, "/media/"), (MEDIA2, "/media2/")):
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), base).replace("\\", "/")
                idx.setdefault(f, prefix + rel)
    return idx

def find_image(idx, md5):
    """原图 {md5}.jpg > {md5}.thumb.jpg > 缩略图 th_{md5} > hevc"""
    if not md5:
        return ""
    for k in (md5 + ".jpg", md5 + ".thumb.jpg", "th_" + md5,
              md5 + ".jpg_hevc", md5, "th_" + md5 + ".jpg"):
        if k in idx:
            return idx[k]
    return ""

def find_voice(idx, vid):
    """voice2/msg_{id}.amr"""
    vid = (vid or "").strip()
    if not vid:
        return ""
    for k in ("msg_" + vid + ".amr", vid + ".amr", "msg_" + vid):
        if k in idx:
            return idx[k]
    return ""

def find_video(idx, vid):
    """video/{id}.mp4 (缩略图 {id}.jpg 兜底)"""
    vid = (vid or "").strip()
    if not vid:
        return ""
    for k in (vid + ".mp4", vid + ".jpg"):
        if k in idx:
            return idx[k]
    return ""

def find_emoji(idx, md5):
    md5 = (md5 or "").strip()
    if not md5:
        return ""
    for k in (md5, md5 + ".gif", md5 + ".png"):
        if k in idx:
            return idx[k]
    return ""

def main():
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    if os.path.exists(DST): os.remove(DST)
    db = sqlite3.connect(SRC); db.text_factory=lambda b: b.decode("utf-8","replace")
    cur = db.cursor()
    out = sqlite3.connect(DST); out.executescript(SCHEMA)
    oc = out.cursor()

    # 会话名
    room={}
    try:
        for r in cur.execute("SELECT chatroomname,displayname,memberlist FROM chatroom"):
            nm=(r[1] or "").strip()
            if not nm and r[2]:
                mem=r[2].split(";"); nm="、".join(mem[:6])+("…" if len(mem)>6 else "")
            room[r[0]]=nm
    except: pass
    contact={}
    try:
        for r in cur.execute("SELECT username,conRemark,nickname FROM rcontact"):
            contact[r[0]]=((r[1] or "").strip(),(r[2] or "").strip())
    except: pass
    def tname(t):
        if t.endswith("@chatroom"): return room.get(t) or t.split("@")[0]
        if t in contact:
            cr,nk=contact[t]; return cr or nk or t
        return t

    midx = build_media_index()
    sess_meta = {}
    nmsg = 0
    for r in cur.execute("SELECT msgId,talker,isSend,createTime,type,content,imgPath FROM message ORDER BY createTime ASC"):
        mid,talker,isSend,ts,typ,content,imgPath = r
        content = content or ""; imgPath = imgPath or ""
        ty = type_map(typ); text=""; mp=""; mt=""; dur=None
        if ty=="text": text=content
        if ty=="image":
            m=re.search(r'th_([0-9a-f]{32})',imgPath)
            if m:
                p=find_image(midx,m.group(1))
                if p: mp=p; mt=p
            text="[图片]"
        elif ty=="voice":
            m=re.search(r'voicelength="?(\d+)',content)
            if m: dur=float(m.group(1))/1000.0
            p=find_voice(midx,imgPath)
            if p: mp=p
            text="[语音]"
        elif ty=="video":
            p=find_video(midx,imgPath)
            if p: mp=p
            text="[视频]"
        elif ty=="emoji":
            m=re.search(r'([0-9a-f]{32})',imgPath)
            if m:
                p=find_emoji(midx,m.group(1))
                if p: mp=p; mt=p
            text="[表情]"
        elif ty=="link":
            t=re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>',content,re.S)
            text=(t.group(1) if t else "") or "[链接]"
        elif ty=="system": text=content.strip()[:500]
        else: text=(content.strip()[:100]) or f"[未知 {typ}]"

        sess = sess_meta.get(talker)
        if sess is None:
            sess_meta[talker] = {"name":tname(talker),
                "type":"group" if talker.endswith("@chatroom") else ("official" if talker.startswith("gh_") else "private")}
        oc.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(mid),talker,"send" if isSend else "recv",talker,
             "我" if isSend else tname(talker),int(ts),ty,text,mp,mt,dur,""))
        nmsg+=1

    for sid,meta in sess_meta.items():
        oc.execute("INSERT INTO sessions VALUES(?,?,?,?,0)",(sid,meta["name"],meta["type"],""))
    for un,(cr,nk) in contact.items():
        oc.execute("INSERT OR IGNORE INTO contacts VALUES(?,?,?,?,?)",(un,nk or cr,cr,"","user"))
    out.commit()
    print(f"standard.db: sessions={len(sess_meta)} messages={nmsg} size={os.path.getsize(DST)/1e6:.1f}MB")

if __name__=="__main__": main()
