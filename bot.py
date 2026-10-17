import os, re, html, time, asyncio, logging, random
from datetime import datetime, timedelta, timezone
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("moviebot")

# ─────────────── CONFIG ───────────────
BOT_TOKEN      = os.environ["BOT_TOKEN"]
TMDB_TOKEN     = os.environ["TMDB_TOKEN"]
CHANNEL_ID     = os.environ["CHANNEL_ID"]
ADMIN_IDS      = {int(x) for x in os.environ.get("ADMIN_IDS","").split(",") if x.strip()}
FIREBASE_DB_URL= os.environ.get("FIREBASE_DB_URL","").rstrip("/")
FIREBASE_API_KEY=os.environ.get("FIREBASE_API_KEY","")
SITE_URL       = os.environ.get("SITE_URL","https://www.moviemanialk.com").rstrip("/")
DOWNLOAD_URL   = os.environ.get("DOWNLOAD_URL", SITE_URL)
WHATSAPP_URL   = os.environ.get("WHATSAPP_URL","https://whatsapp.com/channel/0029Vb6dIi242DccwGQfTr2R")
FB_URL         = os.environ.get("FB_URL","https://www.facebook.com/profile.php?id=61578959931824")
REQUEST_BOT_URL= os.environ.get("REQUEST_BOT_URL","https://t.me/Moviemanialkrequest_bot")
POLL_SECONDS   = int(os.environ.get("POLL_SECONDS","120"))
SUB_BY_DEFAULT = os.environ.get("SUB_BY","Piratelk.com")
POSTED_PATH    = "telegram_bot/posted"
POSTED: set    = set()
AUTOPOST       = True

TMDB     = "https://api.themoviedb.org/3"
IMG      = "https://image.tmdb.org/t/p/"
HEADERS  = {"Authorization": f"Bearer {TMDB_TOKEN}", "accept":"application/json"}
SEP      = "━━━━━━━━━━━━━━━━━━"
QUALITIES= ["WEB-RIP","WEB-DL","BLURAY","HD-RIP","CAM","CAMCOPY","ORIGINAL WEB","4K"]

# ═══════════════════════════════════════════════════════
#  FORM DEFINITION
#  Each field: key, label, emoji, hint, optional
# ═══════════════════════════════════════════════════════
FORM_FIELDS = [
    # key              label                emoji  hint                                               optional
    ("title",         "Title",             "🎬",  "Movie / Series name",                              False),
    ("year",          "Year",              "📅",  "Release year  (e.g. 2026)",                        False),
    ("genre",         "Genre",             "🎭",  "Comma-separated  (Action, Drama)",                 True),
    ("runtime",       "Runtime",           "⏱",  "e.g.  2h 15m   or  45m / ep",                     True),
    ("rating",        "IMDb Rating",       "⭐",  "e.g.  7.8",                                        True),
    ("quality",       "Quality",           "💿",  "WEB-RIP / WEB-DL / BLURAY / HD-RIP / 4K …",       False),
    ("type",          "Type",              "📺",  "movie  or  tv",                                    False),
    ("description",   "Description",       "📝",  "Story overview (paste or type)",                   True),
    ("poster",        "Poster URL",        "🖼",  "https://image.tmdb.org/… or any image URL",        True),
    ("backdrop",      "Backdrop URL",      "🌄",  "Wide banner image URL",                            True),
    ("trailer",       "Trailer URL",       "▶️",  "YouTube watch URL",                               True),
    ("director",      "Director",          "🎥",  "Director name(s)",                                 True),
    ("cast",          "Cast",              "👥",  "Comma-separated actor names",                      True),
    ("country",       "Country",           "🌍",  "e.g.  USA / South Korea",                          True),
    ("subBy",         "Subtitle By",       "🏷",  "Credit name  (e.g. Piratelk.com)",                 True),
    ("subUrl",        "Sub Stream URL",    "💬",  ".srt/.vtt link for in-player CC",                  True),
    ("dlSubUrl",      "Sub Download URL",  "📦",  ".zip/.srt download link",                          True),
    ("downloads",     "Download Links",    "📥",  "One per line:  720p 1.2GB https://…",              True),
    ("players",       "Player Links",      "▶️",  "One per line:  720p https://… (Pixeldrain auto)",  True),
]

FIELD_KEYS   = [f[0] for f in FORM_FIELDS]
FIELD_MAP    = {f[0]: f for f in FORM_FIELDS}

# fields shown as inline buttons in the form overview
QUICK_CYCLE  = {"quality": QUALITIES, "type": ["movie","tv"]}

# ─────────────── FIREBASE ───────────────
async def fb_get(path, **params):
    if FIREBASE_API_KEY: params["key"] = FIREBASE_API_KEY
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{FIREBASE_DB_URL}/{path}.json", params=params)
        r.raise_for_status(); return r.json()

async def fb_put(path, value):
    params = {"key": FIREBASE_API_KEY} if FIREBASE_API_KEY else {}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.put(f"{FIREBASE_DB_URL}/{path}.json", params=params, json=value)
        r.raise_for_status()

async def fb_delete(path):
    params = {"key": FIREBASE_API_KEY} if FIREBASE_API_KEY else {}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.delete(f"{FIREBASE_DB_URL}/{path}.json", params=params)
        r.raise_for_status()

# ─────────────── TMDB ───────────────
async def tmdb_get(path, **params):
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{TMDB}{path}", headers=HEADERS, params=params)
        r.raise_for_status(); return r.json()

async def tmdb_search(query):
    data = await tmdb_get("/search/multi", query=query, include_adult="false")
    return [x for x in data.get("results",[]) if x.get("media_type") in ("movie","tv")][:8]

async def tmdb_details(media_type, tmdb_id):
    return await tmdb_get(
        f"/{media_type}/{tmdb_id}",
        append_to_response="credits,videos,images",
        include_image_language="en,null",
    )

# ─────────────── HELPERS ───────────────
def is_admin(update: Update):
    uid = update.effective_user.id if update.effective_user else 0
    return uid in ADMIN_IDS

def num(v):
    try: return int(float(v))
    except: return 0

def fmt(n): return f"{n:,}"

def slugify(t):
    t = re.sub(r"[''`]","", (t or "").lower())
    return re.sub(r"[^a-z0-9]+","-",t).strip("-")[:80] or "untitled"

async def unique_id(title):
    base = slugify(title)
    for _ in range(8):
        cid = f"{base}-{random.randint(10,99)}"
        if await fb_get(f"movies/{cid}") is None: return cid
    return f"{base}-{str(int(time.time()*1000))[-4:]}"

def pd_convert(url):
    url = (url or "").strip()
    if not url: return url
    if re.search(r"pixeldrain\.com/api/file/[A-Za-z0-9_-]+$", url) and "?download" not in url:
        return url
    if "/api/file/" in url and "?download" in url:
        return url.replace("?download","")
    m = re.search(r"pixeldrain\.com/[ul]/([A-Za-z0-9_-]+)", url)
    if m: return f"https://pixeldrain.com/api/file/{m.group(1)}"
    return url

def parse_downloads(text, quality="WEB-RIP"):
    out = []
    for line in text.splitlines():
        um = re.search(r"https?://\S+", line)
        if not um: continue
        url = um.group(0)
        rm  = re.search(r"\b(2160|1080|720|480|360)p?\b", line, re.I)
        sm  = re.search(r"(\d+(?:\.\d+)?)\s?(GB|MB)", line, re.I)
        res = int(rm.group(1)) if rm else 720
        size= f"{sm.group(1)} {sm.group(2).upper()}" if sm else ""
        pdv = pd_convert(url)
        is_pd = "pixeldrain.com/api/file/" in pdv
        out.append({
            "quality": quality, "res": f"{res}p", "size": size, "url": url,
            "pd480":  pdv if is_pd and res==480  else "",
            "pd720":  pdv if is_pd and res==720  else "",
            "pd1080": pdv if is_pd and res==1080 else "",
            "tgLink":"","srv1":"","srv2":"","srv3":"",
        })
    return out

def parse_players(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        low = line.lower()
        name = "Facebook" if "facebook" in low else "VLC" if "vlc" in low else "MovieManiaLK"
        um = re.search(r"https?://\S+", line)
        if um:
            url = um.group(0)
            rest = line.replace(url," ")
        else:
            fm = re.search(r"\b\d{8,}\b", line)
            if not (name=="Facebook" and fm): continue
            url  = f"https://fb-con.vercel.app/video?video_id={fm.group(0)}"
            rest = line.replace(fm.group(0)," ")
        rm = re.search(r"\b(2160|1080|720|480|360)p?\b", rest)
        q  = f"{rm.group(1)}p" if rm else "720p"
        if name != "Facebook": url = pd_convert(url)
        t = "facebook" if name=="Facebook" else "vlc" if name=="VLC" else \
            "hls" if ".m3u8" in url else "direct"
        out.append({"name":name,"quality":q,"url":url,"type":t})
    return out

def movie_link(mid, m):
    kind = "tv" if m.get("type") in ("tv","series","tv-series") else "movie"
    return f"{SITE_URL}/{kind}/{mid}-sinhala-subtitles"

# ─────────────── FORM STATE ───────────────
def empty_draft():
    return {k: "" for k in FIELD_KEYS} | {
        "quality": "WEB-RIP", "type": "movie",
        "subBy": SUB_BY_DEFAULT,
        "downloads": [], "players": [],
        "screenshots":[], "seasons":[], "players_raw":"",
        "isVip": False, "adult": False, "showSubNotice": False,
        "adminNote":"","scheduledAt":None,"collection":"","collectionOrder":0,
        "addedAt": 0, "tmdbId":"",
    }

def field_value_display(draft, key):
    v = draft.get(key,"")
    if key == "downloads":
        items = draft.get("downloads",[])
        return f"{len(items)} link(s)" if items else "—"
    if key == "players":
        items = draft.get("players",[])
        return f"{len(items)} player(s)" if items else "—"
    if isinstance(v, bool): return "✅" if v else "—"
    if not v: return "—"
    s = str(v)
    return s[:40]+"…" if len(s)>40 else s

def field_status(draft, key):
    _, _, _, _, optional = FIELD_MAP[key]
    v = draft.get(key,"")
    if key in ("downloads","players"): v = draft.get(key,[])
    filled = bool(v) if not isinstance(v, list) else bool(v)
    if filled: return "✅"
    if optional: return "⬜"
    return "❗"

# ─────────────── FORM KEYBOARD ───────────────
def form_keyboard(draft, editing_key=None):
    rows = []
    # Field buttons — 2 per row
    field_btns = []
    for key, label, emoji, _, optional in FORM_FIELDS:
        status = field_status(draft, key)
        val    = field_value_display(draft, key)
        short  = val if len(val)<=15 else val[:13]+"…"
        text   = f"{status} {emoji}{label}: {short}"
        if key in QUICK_CYCLE:
            # tapping cycles through values
            field_btns.append(InlineKeyboardButton(text, callback_data=f"form:cycle:{key}"))
        else:
            field_btns.append(InlineKeyboardButton(text, callback_data=f"form:edit:{key}"))
    # 2 columns
    for i in range(0,len(field_btns),2):
        rows.append(field_btns[i:i+2])

    rows.append([InlineKeyboardButton("⭐ VIP: "  + ("ON" if draft.get("isVip") else "OFF"),
                                       callback_data="form:cycle:isVip")])
    rows.append([
        InlineKeyboardButton("🔍 TMDB Auto-fill", callback_data="form:tmdb"),
        InlineKeyboardButton("🧹 Clear All",       callback_data="form:clear"),
    ])
    rows.append([
        InlineKeyboardButton("✅ Save & Post",  callback_data="form:savepost"),
        InlineKeyboardButton("💾 Save Only",   callback_data="form:saveonly"),
        InlineKeyboardButton("❌ Cancel",       callback_data="form:cancel"),
    ])
    return InlineKeyboardMarkup(rows)

def form_text(draft):
    e = html.escape
    lines = ["📋 <b>Add Movie / Series — Form</b>", SEP]
    required_missing = []
    for key, label, emoji, hint, optional in FORM_FIELDS:
        status = field_status(draft, key)
        val    = field_value_display(draft, key)
        lines.append(f"{status} <b>{emoji} {label}:</b>  {e(val)}")
        if status == "❗": required_missing.append(label)
    lines.append(SEP)
    if required_missing:
        lines.append("❗ <i>Required fields missing: " + ", ".join(required_missing) + "</i>")
    else:
        lines.append("✅ <i>All required fields filled — ready to save!</i>")
    return "\n".join(lines)

# ─────────────── TMDB AUTO-FILL ───────────────
def fill_from_tmdb(draft, d, media_type):
    vids  = d.get("videos",{}).get("results",[])
    yt    = [v for v in vids if v.get("site")=="YouTube"]
    trl   = next((v for v in yt if v.get("type")=="Trailer"),None) or (yt[0] if yt else None)
    crew  = d.get("credits",{}).get("crew",[])
    cast  = d.get("credits",{}).get("cast",[])
    backs = d.get("images",{}).get("backdrops",[])[:6]
    date  = d.get("release_date") or d.get("first_air_date") or ""
    mins  = d.get("runtime") or 0
    vote  = d.get("vote_average") or 0
    countries = [c["name"] for c in d.get("production_countries",[]) or []] or \
                list(d.get("origin_country") or [])
    draft.update({
        "title":    d.get("title") or d.get("name") or "",
        "year":     date[:4],
        "genre":    ", ".join(g["name"] for g in d.get("genres",[])),
        "runtime":  f"{mins//60}h {mins%60}m" if mins else "",
        "rating":   f"{vote:.1f}" if vote else "",
        "description": d.get("overview") or "",
        "poster":   f"{IMG}original{d['poster_path']}"   if d.get("poster_path")   else "",
        "backdrop": f"{IMG}original{d['backdrop_path']}" if d.get("backdrop_path") else "",
        "trailer":  f"https://www.youtube.com/watch?v={trl['key']}" if trl else "",
        "director": ", ".join(c["name"] for c in crew if c.get("job")=="Director"),
        "cast":     ", ".join(c["name"] for c in cast[:8]),
        "country":  ", ".join(countries),
        "type":     media_type,
        "tmdbId":   str(d.get("id") or ""),
        "collection": (d.get("belongs_to_collection") or {}).get("name",""),
        "screenshots": [f"{IMG}original{b['file_path']}" for b in backs],
    })
    if not draft.get("subBy"): draft["subBy"] = SUB_BY_DEFAULT
    return draft

# ─────────────── CAPTION / POST ───────────────
def stars(r):
    f = int(round(r/2))
    return "★"*f + "☆"*(5-f)

def hashtags(genres, year):
    tags = ["#" + "".join(ch for ch in g.title() if ch.isalnum()) for g in genres[:3] if g]
    tags += ["#SinhalaSub"]
    if year: tags.append(f"#{year}")
    return " ".join(tags)

SINHALA_LINE = "🇱🇰 <b>සිංහල උපසිරස සමග Download කරගැනීමට හා Online නැරඹීමට</b> 👇"

def render_card(title,year,kind,rating,genres,runtime,quality,country,director,cast,overview):
    e = html.escape
    head = f"{kind} <b>{e(title.upper())}</b>" + (f" <i>({e(str(year))})</i>" if year else "")
    lines = [head, SEP]
    if rating: lines.append(f"⭐ <b>{rating:.1f}</b>/10  {stars(rating)}")
    if genres: lines.append("🎭 " + " • ".join(e(g) for g in genres))
    meta=[]
    if runtime: meta.append(f"⏱ {e(str(runtime))}")
    if quality: meta.append(f"💿 {e(str(quality))}")
    if country: meta.append(f"🌍 {e(str(country))}")
    if meta: lines.append("  |  ".join(meta))
    lines.append(SEP)
    if director: lines.append(f"🎥 <b>Director:</b> {e(str(director))}")
    if cast:     lines.append(f"👥 <b>Cast:</b> {e(str(cast))}")
    tail = ["", SINHALA_LINE, "", hashtags(genres, str(year or ""))]
    overview = (overview or "").strip()
    limit = 300
    while True:
        body = list(lines)
        if overview:
            ov = overview if len(overview)<=limit else overview[:limit-3].rsplit(" ",1)[0]+"..."
            body += ["", f"<blockquote expandable>📝 {e(ov)}</blockquote>"]
        text = "\n".join(body+tail)
        if len(text)<=1024 or limit<=60: return text
        limit -= 40

def site_caption(m):
    try: rating = float(m.get("rating") or 0)
    except: rating = 0
    genres = [g.strip() for g in str(m.get("genre","")).split(",") if g.strip()]
    kind   = "📺" if m.get("type") in ("tv","series","tv-series") else "🎬"
    return render_card(
        m.get("title",""), m.get("year",""), kind, rating, genres,
        m.get("runtime"), m.get("quality"), m.get("country"),
        m.get("director"), m.get("cast"), m.get("description"),
    )

def post_keyboard(download_url, trailer):
    rows = [[
        InlineKeyboardButton("📥 Download Now",    url=download_url),
        InlineKeyboardButton("▶️ Watch Online",    url=download_url),
    ]]
    if trailer: rows.append([InlineKeyboardButton("🎞 Watch Trailer", url=trailer)])
    rows.append([InlineKeyboardButton("🎬 Request Movie", url=REQUEST_BOT_URL)])
    rows.append([
        InlineKeyboardButton("💬 WhatsApp", url=WHATSAPP_URL),
        InlineKeyboardButton("👍 Facebook", url=FB_URL),
    ])
    return InlineKeyboardMarkup(rows)

async def post_movie(bot, mid, m):
    caption = site_caption(m)
    link    = movie_link(mid, m)
    kb      = post_keyboard(link, (m.get("trailer") or "").strip() or None)
    poster  = (m.get("poster") or m.get("backdrop") or "").strip()
    poster  = poster.replace("/t/p/original/","/t/p/w780/")
    if poster.startswith("http"):
        try:
            await bot.send_photo(CHANNEL_ID, poster, caption=caption, parse_mode="HTML", reply_markup=kb)
            return
        except Exception: log.exception("photo failed, sending text")
    await bot.send_message(CHANNEL_ID, caption, parse_mode="HTML", reply_markup=kb)

# ─────────────── SAVE DRAFT TO FIREBASE ───────────────
async def save_draft_to_firebase(draft):
    movie = {
        "title":        draft.get("title",""),
        "year":         draft.get("year",""),
        "genre":        draft.get("genre",""),
        "runtime":      draft.get("runtime",""),
        "rating":       draft.get("rating",""),
        "description":  draft.get("description",""),
        "poster":       draft.get("poster",""),
        "backdrop":     draft.get("backdrop",""),
        "trailer":      draft.get("trailer",""),
        "director":     draft.get("director",""),
        "cast":         draft.get("cast",""),
        "country":      draft.get("country",""),
        "quality":      draft.get("quality","WEB-RIP"),
        "type":         draft.get("type","movie"),
        "subBy":        draft.get("subBy", SUB_BY_DEFAULT),
        "subUrl":       draft.get("subUrl",""),
        "subtitleUrl":  draft.get("subUrl",""),
        "dlSubUrl":     draft.get("dlSubUrl",""),
        "screenshots":  draft.get("screenshots",[]),
        "downloads":    draft.get("downloads",[]),
        "players":      draft.get("players",[]),
        "seasons":      draft.get("seasons",[]),
        "isVip":        bool(draft.get("isVip",False)),
        "adult":        bool(draft.get("adult",False)),
        "showSubNotice":bool(draft.get("showSubNotice",False)),
        "adminNote":    draft.get("adminNote",""),
        "scheduledAt":  draft.get("scheduledAt",None),
        "collection":   draft.get("collection",""),
        "collectionOrder": int(draft.get("collectionOrder",0) or 0),
        "tmdbId":       draft.get("tmdbId",""),
        "addedAt":      int(time.time()*1000),
        "views":        0,
        "downloads_count": 0,
        "subtitle_downloads_count": 0,
    }
    mid = await unique_id(movie["title"])
    await fb_put(f"movies/{mid}", movie)
    return mid, movie

# ═══════════════════════════════════════════════════════
#  HANDLERS
# ═══════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            "🎬 <b>MovieMania LK</b>\n\nMovie request කරන්නද?\nBot: " + REQUEST_BOT_URL,
            parse_mode="HTML"
        ); return
    await update.message.reply_text(
        "👋 <b>Admin Panel</b>\n\n"
        "🎬 Movie / Series name type කරන්න — TMDB auto-fill\n"
        "➕ /add — blank form open\n"
        "📊 /stats  🕘 /last  🔎 /find  🗑 /del  ⭐ /vip  🔄 /repost",
        parse_mode="HTML"
    )

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    ctx.user_data["draft"] = empty_draft()
    ctx.user_data["state"] = None
    await update.message.reply_text(
        form_text(ctx.user_data["draft"]),
        parse_mode="HTML",
        reply_markup=form_keyboard(ctx.user_data["draft"])
    )

async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: {update.effective_user.id}")

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    ctx.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")

# ─────────────── TEXT HANDLER ───────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await handle_request(update, ctx); return

    text  = (update.message.text or "").strip()
    state = ctx.user_data.get("state")
    draft = ctx.user_data.get("draft")

    # ── Editing a field ──
    if state and state.startswith("edit:") and draft is not None:
        key = state[5:]
        skip = text.lower() in ("/skip","skip","-",".")

        if not skip:
            if key == "downloads":
                parsed = parse_downloads(text, draft.get("quality","WEB-RIP"))
                if not parsed:
                    await update.message.reply_text("❌ Valid URL හොයාගන්න බෑ. ආයෙ try.\nExample:\n<code>720p 1.2GB https://pixeldrain.com/u/abc</code>", parse_mode="HTML")
                    return
                draft["downloads"] = parsed
                # Auto players from Pixeldrain
                players = []
                for d in parsed:
                    for p in ("pd480","pd720","pd1080"):
                        if d.get(p):
                            players.append({"name":"MovieManiaLK","quality":d["res"],"url":d[p],"type":"direct"})
                if players: draft["players"] = players
            elif key == "players":
                parsed = parse_players(text)
                if parsed: draft["players"] = parsed
            else:
                draft[key] = text.strip()

        ctx.user_data["state"] = None
        msg_id = ctx.user_data.get("form_msg_id")
        if msg_id:
            try:
                await ctx.bot.edit_message_text(
                    form_text(draft), chat_id=update.effective_chat.id,
                    message_id=msg_id, parse_mode="HTML",
                    reply_markup=form_keyboard(draft)
                )
                await update.message.delete()
                return
            except Exception: pass
        # fallback — send new form
        m = await update.message.reply_text(form_text(draft), parse_mode="HTML", reply_markup=form_keyboard(draft))
        ctx.user_data["form_msg_id"] = m.message_id
        return

    # ── TMDB search waiting ──
    if state == "tmdb_search":
        ctx.user_data["state"] = None
        await do_tmdb_search(update, ctx, text)
        return

    # ── Default: treat as TMDB search ──
    ctx.user_data.clear()
    await do_tmdb_search(update, ctx, text)

async def do_tmdb_search(update, ctx, text):
    try:
        results = await tmdb_search(text)
    except Exception:
        await update.message.reply_text("⚠️ TMDB error. Try again."); return
    if not results:
        await update.message.reply_text("😕 Nothing found. Try another name."); return

    lines = ["🔎 <b>TMDB Results</b> — pick one:\n"]
    buttons = []
    for i, r in enumerate(results, 1):
        t  = r.get("title") or r.get("name","?")
        y  = (r.get("release_date") or r.get("first_air_date") or "")[:4]
        ic = "🎬" if r["media_type"]=="movie" else "📺"
        lines.append(f"{i}. {ic} {html.escape(t)} ({y})  ⭐{r.get('vote_average',0):.1f}")
        buttons.append(InlineKeyboardButton(str(i), callback_data=f"tmdb:{r['media_type']}:{r['id']}"))
    rows = [buttons[i:i+4] for i in range(0,len(buttons),4)]
    rows.append([InlineKeyboardButton("➕ Skip TMDB — blank form", callback_data="form:blank")])
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))

# ─────────────── CALLBACK ───────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(update): return
    data  = q.data
    draft = ctx.user_data.get("draft") or {}

    # ── TMDB pick ──
    if data.startswith("tmdb:"):
        _, media_type, tmdb_id = data.split(":")
        await q.edit_message_text("⏳ TMDB loading…")
        try:
            d = await tmdb_details(media_type, int(tmdb_id))
        except Exception as ex:
            await q.edit_message_text(f"❌ TMDB error: {ex}"); return
        if not ctx.user_data.get("draft"):
            ctx.user_data["draft"] = empty_draft()
        fill_from_tmdb(ctx.user_data["draft"], d, media_type)
        draft = ctx.user_data["draft"]
        m = await q.message.reply_text(form_text(draft), parse_mode="HTML", reply_markup=form_keyboard(draft))
        ctx.user_data["form_msg_id"] = m.message_id
        return

    # ── Blank form ──
    if data == "form:blank":
        ctx.user_data["draft"] = empty_draft()
        ctx.user_data["state"] = None
        m = await q.message.reply_text(
            form_text(ctx.user_data["draft"]), parse_mode="HTML",
            reply_markup=form_keyboard(ctx.user_data["draft"])
        )
        ctx.user_data["form_msg_id"] = m.message_id
        return

    # ── Form TMDB auto-fill button ──
    if data == "form:tmdb":
        ctx.user_data["state"] = "tmdb_search"
        await q.message.reply_text("🔍 Movie / Series name type කරන්න (TMDB search):")
        return

    # ── Clear ──
    if data == "form:clear":
        ctx.user_data["draft"] = empty_draft()
        ctx.user_data["state"] = None
        await q.edit_message_text(
            form_text(ctx.user_data["draft"]), parse_mode="HTML",
            reply_markup=form_keyboard(ctx.user_data["draft"])
        )
        return

    # ── Cancel ──
    if data == "form:cancel":
        ctx.user_data.clear()
        await q.edit_message_text("❌ Cancelled.")
        return

    # ── Cycle quick fields ──
    if data.startswith("form:cycle:"):
        key = data[len("form:cycle:"):]
        if key == "isVip":
            draft["isVip"] = not bool(draft.get("isVip"))
        elif key in QUICK_CYCLE:
            opts = QUICK_CYCLE[key]
            cur  = draft.get(key, opts[0])
            draft[key] = opts[(opts.index(cur)+1) % len(opts)] if cur in opts else opts[0]
        ctx.user_data["draft"] = draft
        await q.edit_message_text(form_text(draft), parse_mode="HTML", reply_markup=form_keyboard(draft))
        return

    # ── Edit field ──
    if data.startswith("form:edit:"):
        key = data[len("form:edit:"):]
        _, label, emoji, hint, optional = FIELD_MAP[key]
        cur = field_value_display(draft, key)
        ctx.user_data["state"] = f"edit:{key}"
        ctx.user_data["form_msg_id"] = q.message.message_id
        opt_txt = " (optional — /skip to leave blank)" if optional else " (required)"
        await q.message.reply_text(
            f"{emoji} <b>{label}</b>{opt_txt}\n\n"
            f"💡 <i>{html.escape(hint)}</i>\n\n"
            f"Current: <code>{html.escape(cur)}</code>",
            parse_mode="HTML"
        )
        return

    # ── Save ──
    if data in ("form:savepost","form:saveonly"):
        if not draft.get("title"):
            await q.answer("❗ Title field required!", show_alert=True); return
        if not draft.get("quality"):
            await q.answer("❗ Quality field required!", show_alert=True); return

        await q.edit_message_text("⏳ Saving to Firebase…")
        try:
            mid, movie = await save_draft_to_firebase(draft)
        except Exception as ex:
            await q.edit_message_text(f"❌ Save failed:\n{ex}"); return

        POSTED.add(mid)
        try: await fb_put(f"{POSTED_PATH}/{mid}", True)
        except: pass

        result = f"✅ <b>Saved!</b>\n🎬 {html.escape(movie['title'])}\n🆔 <code>{mid}</code>"

        if data == "form:savepost":
            try:
                await post_movie(ctx.bot, mid, movie)
                result += "\n📢 Channel ලෙ post කළා!"
                await fb_put(f"telegram_bot/history/{mid}", {"title": movie["title"], "ts": int(time.time()*1000)})
            except Exception as ex:
                result += f"\n⚠️ Post failed: {ex}\n(/repost {mid})"
        else:
            result += f"\n💾 Save only. Channel ලෙ post: /repost {mid}"

        ctx.user_data.clear()
        await q.edit_message_text(
            result, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🌐 Open on site", url=movie_link(mid, movie))
            ]])
        )
        return

    # ── Legacy callbacks (requests, del, vip, repost) ──
    if data.startswith("rq:"): await handle_req_action(update, ctx); return
    if data.startswith("del:"): await handle_del_action(update, ctx); return

# ═══════════════════════════════════════════════════════
#  REQUESTS
# ═══════════════════════════════════════════════════════
REQ_COOLDOWN = 60
_last_req: dict = {}
_requests: dict = {}
_req_msgs: dict = {}
STATUS_ICON = {"pending":"⏳","seen":"👀","added":"✅","rejected":"❌"}

def req_text(rec):
    e   = html.escape
    st  = rec.get("status","pending")
    ico = STATUS_ICON.get(st, st)
    by  = f" — {e(rec['by'])}" if rec.get("by") and st!="pending" else ""
    return (
        "📩 <b>New Request</b>\n"
        f"🎬 {e(rec['text'])}\n"
        f"👤 <a href=\"tg://user?id={rec['uid']}\">{e(rec['name'])}</a>\n"
        f"📌 {ico} <b>{st.title()}</b>{by}"
    )

def req_kb(rec):
    rid,st = rec["id"],rec.get("status","pending")
    if st=="pending":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 Seen", callback_data=f"rq:seen:{rid}")],
            [InlineKeyboardButton("✅ Added", callback_data=f"rq:added:{rid}"),
             InlineKeyboardButton("❌ Not available", callback_data=f"rq:rejected:{rid}")],
        ])
    if st=="seen":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Added", callback_data=f"rq:added:{rid}"),
            InlineKeyboardButton("❌ Not available", callback_data=f"rq:rejected:{rid}"),
        ]])
    return None

async def handle_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()[:100]
    if not text: return
    now  = time.time()
    wait = REQ_COOLDOWN - (now - _last_req.get(user.id, 0))
    if wait > 0:
        await update.message.reply_text(f"⏳ තව {int(wait)}s අකින් request කරන්න."); return
    _last_req[user.id] = now
    rec = {"id": str(int(now*1000)), "uid": user.id, "name": user.full_name or "User",
           "text": text, "status": "pending", "ts": int(now*1000)}
    _requests[rec["id"]] = rec
    _req_msgs[rec["id"]] = []
    for admin in ADMIN_IDS:
        try:
            msg = await ctx.bot.send_message(admin, req_text(rec), parse_mode="HTML", reply_markup=req_kb(rec))
            _req_msgs[rec["id"]].append((admin, msg.message_id))
        except: pass
    try: await fb_put(f"telegram_bot/requests/{rec['id']}", rec)
    except: pass
    await update.message.reply_text("✅ Request ලැබුණා! Admin දැකල දැනුම් දෙන්නම් 🎬")

async def handle_req_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    _,action,rid = q.data.split(":",2)
    rec = _requests.get(rid)
    if not isinstance(rec,dict):
        try: rec = await fb_get(f"telegram_bot/requests/{rid}")
        except: rec = None
    if not isinstance(rec,dict):
        await q.edit_message_text("⚠️ Request හොයාගන්න බෑ."); return
    _requests[rid] = rec
    if rec["status"] == action or rec["status"] in ("added","rejected"):
        try: await q.answer("දැනටමත් update ✔️")
        except: pass
        return
    rec["status"] = action
    rec["by"]     = update.effective_user.first_name or "Admin"
    try: await fb_put(f"telegram_bot/requests/{rid}", rec)
    except: pass
    for chat_id,msg_id in (_req_msgs.get(rid) or [(q.message.chat_id,q.message.message_id)]):
        try:
            await ctx.bot.edit_message_text(req_text(rec), chat_id=chat_id, message_id=msg_id,
                                            parse_mode="HTML", reply_markup=req_kb(rec))
        except: pass
    title = html.escape(rec["text"])
    kb = None
    if action == "seen":
        msg = f"👀 <b>ඔයාගේ request admin දැක්කා!</b>\n🎬 {title}"
    elif action == "added":
        msg = f"✅ <b>ඔයාගේ request add කළා!</b>\n🎬 {title}\nSite ලෙ බලන්න 👇"
        kb  = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Website", url=SITE_URL)]])
    else:
        msg = f"❌ සමාවෙන්න, <b>{title}</b> දැනට ලබාගන්න අමාරුයි."
    try: await ctx.bot.send_message(rec["uid"], msg, parse_mode="HTML", reply_markup=kb)
    except:
        try: await q.answer("Member ට message යවන්න බෑ", show_alert=True)
        except: pass

# ═══════════════════════════════════════════════════════
#  ADMIN COMMANDS
# ═══════════════════════════════════════════════════════
async def handle_del_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query
    parts = q.data.split(":",2)
    action,mid = parts[1],(parts[2] if len(parts)>2 else "")
    if action=="no":
        await q.edit_message_text("❌ Cancelled."); return
    try:
        m = await fb_get(f"movies/{mid}")
        if not isinstance(m,dict):
            await q.edit_message_text("❌ Movie not found."); return
        v,dl = num(m.get("views")),num(m.get("downloads_count"))
        if v or dl:
            cur = await fb_get("analytics/deletedStats") or {}
            await fb_put("analytics/deletedStats",{
                "totalViews": num(cur.get("totalViews"))+v,
                "totalDownloads": num(cur.get("totalDownloads"))+dl,
                "deletedCount": num(cur.get("deletedCount"))+1,
            })
        await fb_delete(f"movies/{mid}")
        await q.edit_message_text(f"🗑 Deleted: {html.escape(str(m.get('title')))}",parse_mode="HTML")
    except Exception as ex:
        await q.edit_message_text(f"❌ Failed: {ex}")

async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    term = " ".join(ctx.args).strip().lower()
    if not term:
        await update.message.reply_text("Usage: /find movie-name"); return
    try: movies = await fb_get("movies") or {}
    except:
        await update.message.reply_text("⚠️ Firebase error."); return
    hits = [(k,v) for k,v in movies.items()
            if isinstance(v,dict) and term in str(v.get("title","")).lower()][:8]
    if not hits:
        await update.message.reply_text("😕 Nothing found."); return
    lines = ["🔎 <b>Results</b>\n"]
    for k,v in hits:
        vip = " ⭐VIP" if v.get("isVip") else ""
        lines.append(f"🎬 <b>{html.escape(str(v.get('title')))}</b> ({v.get('year','')}){vip}\n"
                     f"   <code>{html.escape(k)}</code>  👁{fmt(num(v.get('views')))}  📥{fmt(num(v.get('downloads_count')))}")
    lines.append("\n/vip id  •  /del id  •  /repost id")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cmd_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not ctx.args:
        await update.message.reply_text("Usage: /del movie-id"); return
    mid = ctx.args[0]
    try: m = await fb_get(f"movies/{mid}")
    except: m = None
    if not isinstance(m,dict):
        await update.message.reply_text("❌ Movie not found."); return
    await update.message.reply_text(
        f"🗑 Delete <b>{html.escape(str(m.get('title')))}</b>?", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Yes, delete", callback_data=f"del:yes:{mid}"),
            InlineKeyboardButton("❌ No",          callback_data="del:no"),
        ]])
    )

async def cmd_vip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not ctx.args:
        await update.message.reply_text("Usage: /vip movie-id"); return
    mid = ctx.args[0]
    try: m = await fb_get(f"movies/{mid}")
    except: m = None
    if not isinstance(m,dict):
        await update.message.reply_text("❌ Movie not found."); return
    new = not bool(m.get("isVip"))
    await fb_put(f"movies/{mid}/isVip", new)
    await update.message.reply_text(
        f"⭐ <b>{html.escape(str(m.get('title')))}</b>\nVIP: <b>{'ON' if new else 'OFF'}</b>", parse_mode="HTML")

async def cmd_repost(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not ctx.args:
        await update.message.reply_text("Usage: /repost movie-id"); return
    mid = ctx.args[0]
    try:
        m = await fb_get(f"movies/{mid}")
        if not isinstance(m,dict):
            await update.message.reply_text("❌ Movie not found."); return
        await post_movie(ctx.bot, mid, m)
        await update.message.reply_text(f"✅ Reposted: {m.get('title')}")
    except Exception as ex:
        await update.message.reply_text(f"❌ Failed: {ex}")

async def cmd_last(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: hist = await fb_get("telegram_bot/history") or {}
    except:
        await update.message.reply_text("⚠️ Firebase error."); return
    items = sorted((h for h in hist.values() if isinstance(h,dict)),
                   key=lambda h: float(h.get("ts",0)), reverse=True)[:5]
    if not items:
        await update.message.reply_text("No post history yet."); return
    lines = ["🕘 <b>Last posts</b>\n"]
    for i,h in enumerate(items,1):
        lines.append(f"{i}. {html.escape(str(h.get('title','?')))}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cmd_requests(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        data = await fb_get("telegram_bot/requests", orderBy='"$key"', limitToLast="10") or {}
    except:
        await update.message.reply_text("⚠️ Firebase error."); return
    recs = sorted((r for r in data.values() if isinstance(r,dict)),
                  key=lambda r: num(r.get("ts")), reverse=True)
    if not recs:
        await update.message.reply_text("📭 No requests."); return
    pending = sum(1 for r in recs if r.get("status") in ("pending","seen"))
    lines = [f"📩 <b>Requests</b> (last {len(recs)}, pending: {pending})\n"]
    for r in recs:
        ico = STATUS_ICON.get(r.get("status"),"•")
        lines.append(f"{ico} {html.escape(str(r.get('text')))} — {html.escape(str(r.get('name')))}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    wait = await update.message.reply_text("⏳ Stats loading…")
    try:
        movies   = await fb_get("movies") or {}
        deleted  = await fb_get("analytics/deletedStats") or {}
        vis_tot  = num(await fb_get("analytics/totalVisitors"))
        hist     = await fb_get("telegram_bot/history") or {}
    except Exception:
        await wait.edit_text("⚠️ Firebase error."); return
    items  = [(k,v) for k,v in movies.items() if isinstance(v,dict)]
    views  = sum(num(v.get("views")) for _,v in items) + num(deleted.get("totalViews"))
    dls    = sum(num(v.get("downloads_count")) for _,v in items) + num(deleted.get("totalDownloads"))
    lines  = [
        "📊 <b>Stats</b>", SEP,
        f"🎞 Titles: <b>{fmt(len(items))}</b>",
        f"👁 Total views: <b>{fmt(views)}</b>",
        f"📥 Total downloads: <b>{fmt(dls)}</b>",
        f"👥 Visitors: <b>{fmt(vis_tot)}</b>",
        f"📤 Bot posts: <b>{fmt(len(hist))}</b>",
        SEP,
        f"🤖 Auto post: <b>{'ON' if AUTOPOST else 'OFF'}</b>",
    ]
    await wait.edit_text("\n".join(lines), parse_mode="HTML")

async def cmd_autopost(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global AUTOPOST
    if not is_admin(update): return
    arg = ctx.args[0].lower() if ctx.args else ""
    if arg in ("on","off"):
        AUTOPOST = arg == "on"
        try: await fb_put("telegram_bot/autopost", AUTOPOST)
        except: pass
    await update.message.reply_text(f"🤖 Auto post: {'ON ✅' if AUTOPOST else 'OFF ⏸'}")

# ═══════════════════════════════════════════════════════
#  AUTO POST LOOP
# ═══════════════════════════════════════════════════════
def is_due(m):
    sched = m.get("scheduledAt")
    return not sched or float(sched) <= time.time()*1000

async def check_new_movies(bot, posted):
    keys = await fb_get("movies", shallow="true") or {}
    for mid in keys:
        if mid in posted: continue
        m = await fb_get(f"movies/{mid}")
        if not isinstance(m,dict) or not is_due(m): continue
        if m.get("adult"):
            posted.add(mid); continue
        try:
            await post_movie(bot, mid, m)
        except Exception:
            log.exception("auto post failed: %s", mid); continue
        posted.add(mid)
        try: await fb_put(f"{POSTED_PATH}/{mid}", True)
        except: pass
        try: await fb_put(f"telegram_bot/history/{mid}", {"title": m.get("title"), "ts": int(time.time()*1000)})
        except: pass
        for admin in ADMIN_IDS:
            try: await bot.send_message(admin, f"✅ Auto posted: {m.get('title')}")
            except: pass
        await asyncio.sleep(3)

async def auto_post_loop(app: Application):
    if not FIREBASE_DB_URL: return
    global AUTOPOST
    try:
        if await fb_get("telegram_bot/autopost") is False: AUTOPOST = False
    except: pass
    try:
        saved = await fb_get(POSTED_PATH)
        if saved is None:
            keys = await fb_get("movies", shallow="true") or {}
            POSTED.update(keys)
            try: await fb_put(POSTED_PATH, {k: True for k in POSTED} or {"_init":True})
            except: pass
        else:
            POSTED.update(saved)
    except: return
    while True:
        try:
            if AUTOPOST: await check_new_movies(app.bot, POSTED)
        except: log.exception("auto post check failed")
        await asyncio.sleep(POLL_SECONDS)

async def post_init(app: Application):
    asyncio.create_task(auto_post_loop(app))

async def on_error(update, ctx):
    log.error("handler error", exc_info=ctx.error)

# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("add",       cmd_add))
    app.add_handler(CommandHandler("myid",      cmd_myid))
    app.add_handler(CommandHandler("cancel",    cmd_cancel))
    app.add_handler(CommandHandler("find",      cmd_find))
    app.add_handler(CommandHandler("del",       cmd_del))
    app.add_handler(CommandHandler("vip",       cmd_vip))
    app.add_handler(CommandHandler("repost",    cmd_repost))
    app.add_handler(CommandHandler("last",      cmd_last))
    app.add_handler(CommandHandler("requests",  cmd_requests))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("autopost",  cmd_autopost))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    log.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
