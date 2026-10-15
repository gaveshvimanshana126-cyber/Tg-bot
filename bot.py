import os
import html
import time
from datetime import datetime, timedelta, timezone
import asyncio
import logging

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("moviebot")

# ---------- CONFIG (Railway Variables) ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]
TMDB_TOKEN = os.environ["TMDB_TOKEN"]  # TMDB "API Read Access Token"
CHANNEL_ID = os.environ["CHANNEL_ID"]  # e.g. -1001234567890 or @yourchannel
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}

DOWNLOAD_URL = os.environ.get("DOWNLOAD_URL", "https://moviemanialk.com")  # fixed for every post
WHATSAPP_URL = os.environ.get(
    "WHATSAPP_URL", "https://whatsapp.com/channel/0029Vb6dIi242DccwGQfTr2R"
)
FB_URL = os.environ.get(
    "FB_URL", "https://www.facebook.com/profile.php?id=61578959931824"
)

# ---- Auto-post (Firebase admin panel) ----
FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "https://cineflix1-1fdc6-default-rtdb.firebaseio.com").rstrip("/")
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "AIzaSyAh6zMB65iWqt3R2Ep0C5_7eV8ZaUHI7t8")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "120"))
SITE_URL = os.environ.get("SITE_URL", "https://www.moviemanialk.com").rstrip("/")
REQUEST_BOT_URL = os.environ.get("REQUEST_BOT_URL", "https://t.me/Moviemanialkrequest_bot")
POSTED_PATH = "telegram_bot/posted"

TMDB = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w500"
HEADERS = {"Authorization": f"Bearer {TMDB_TOKEN}", "accept": "application/json"}


# ---------- TMDB ----------
async def tmdb_get(path: str, **params):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{TMDB}{path}", headers=HEADERS, params=params)
        r.raise_for_status()
        return r.json()


async def search(query: str):
    data = await tmdb_get("/search/multi", query=query, include_adult="false")
    results = [x for x in data.get("results", []) if x.get("media_type") in ("movie", "tv")]
    return results[:8]


async def details(media_type: str, tmdb_id: int):
    return await tmdb_get(
        f"/{media_type}/{tmdb_id}", append_to_response="credits,videos"
    )


# ---------- POST BUILDER ----------
SEP = "━━━━━━━━━━━━━━━━━━"
SINHALA_LINE = "🇱🇰 <b>සිංහල උපසිරස සමග Download කරගැනිමට හා Online නැරඹිමට පිවිසෙන්න</b> 👇"


def stars(rating: float) -> str:
    full = int(round(rating / 2))
    return "★" * full + "☆" * (5 - full)


def hashtags(genres: list, year: str) -> str:
    tags = []
    for g in genres[:3]:
        t = "".join(ch for ch in g.title() if ch.isalnum())
        if t:
            tags.append("#" + t)
    tags.append("#SinhalaSub")
    if year:
        tags.append(f"#{year}")
    return " ".join(tags)


def render_card(title, year, kind, rating, genres, runtime, quality, country,
                director, cast, overview) -> str:
    e = html.escape
    head = f"{kind} <b>{e(title.upper())}</b>" + (f" <i>({e(str(year))})</i>" if year else "")
    lines = [head, SEP]
    if rating:
        lines.append(f"⭐ <b>{rating:.1f}</b>/10  {stars(rating)}")
    if genres:
        lines.append("🎭 " + " • ".join(e(g) for g in genres))
    meta = []
    if runtime:
        meta.append(f"⏱ {e(str(runtime))}")
    if quality:
        meta.append(f"💿 {e(str(quality))}")
    if country:
        meta.append(f"🌍 {e(str(country))}")
    if meta:
        lines.append("  |  ".join(meta))
    lines.append(SEP)
    if director:
        lines.append(f"🎥 <b>Director:</b> {e(str(director))}")
    if cast:
        lines.append(f"👥 <b>Cast:</b> {e(str(cast))}")

    tail = ["", SINHALA_LINE, "", hashtags(genres, str(year or ""))]
    overview = (overview or "").strip()
    limit = 300
    while True:
        body = list(lines)
        if overview:
            ov = overview if len(overview) <= limit else overview[: limit - 3].rsplit(" ", 1)[0] + "..."
            body += ["", f"<blockquote expandable>📝 {e(ov)}</blockquote>"]
        text = "\n".join(body + tail)
        if len(text) <= 1024 or limit <= 60:
            return text
        limit -= 40


def build_caption(d: dict, media_type: str) -> str:
    title = d.get("title") or d.get("name") or "Unknown"
    date = d.get("release_date") or d.get("first_air_date") or ""
    if media_type == "movie":
        mins = d.get("runtime") or 0
        runtime = f"{mins // 60}h {mins % 60}m" if mins else ""
    else:
        eps = d.get("episode_run_time") or []
        runtime = f"{eps[0]}m / ep" if eps else ""
    credits = d.get("credits", {})
    cast = ", ".join(c["name"] for c in credits.get("cast", [])[:5])
    directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"]
    return render_card(
        title, date[:4], "🎬" if media_type == "movie" else "📺",
        d.get("vote_average") or 0,
        [g["name"] for g in d.get("genres", [])],
        runtime, "", "", ", ".join(directors[:2]), cast, d.get("overview"),
    )


def trailer_url(d: dict):
    for v in d.get("videos", {}).get("results", []):
        if v.get("site") == "YouTube" and v.get("type") == "Trailer":
            return f"https://www.youtube.com/watch?v={v['key']}"
    return None


def btn(text: str, url: str, style: str | None = None) -> InlineKeyboardButton:
    """URL button with optional colour: primary=blue, success=green, danger=red."""
    if not style:
        return InlineKeyboardButton(text, url=url)
    try:
        return InlineKeyboardButton(text, url=url, style=style)
    except TypeError:  # older python-telegram-bot without native `style`
        return InlineKeyboardButton(text, url=url, api_kwargs={"style": style})


def post_keyboard(download_url: str, trailer: str | None) -> InlineKeyboardMarkup:
    rows = [[
        btn("📥 Download Now", download_url, "primary"),   # blue
        btn("▶️ Watch Online", download_url, "danger"),    # red
    ]]
    if trailer:
        rows.append([btn("🎞 Watch Trailer", trailer)])
    rows.append([btn("🎬 Request Movie", REQUEST_BOT_URL, "success")])  # green
    rows.append([
        btn("💬 WhatsApp", WHATSAPP_URL, "success"),       # green
        btn("👍 Facebook", FB_URL, "primary"),             # blue
    ])
    return InlineKeyboardMarkup(rows)


async def send_post(bot, chat_id, post: dict, download_url: str):
    kb = post_keyboard(download_url, post["trailer"])
    if post["poster"]:
        return await bot.send_photo(
            chat_id, post["poster"], caption=post["caption"],
            parse_mode="HTML", reply_markup=kb,
        )
    return await bot.send_message(
        chat_id, post["caption"], parse_mode="HTML", reply_markup=kb
    )


# ---------- HELPERS ----------
def is_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return uid in ADMIN_IDS


# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        kb = InlineKeyboardMarkup([
            [btn("🌐 Website", SITE_URL, "primary")],
            [
                btn("💬 WhatsApp", WHATSAPP_URL, "success"),
                btn("👍 Facebook", FB_URL, "primary"),
            ],
        ])
        await update.message.reply_text(
            "🎬 <b>MovieMania LK</b>\n\n"
            "සිංහල උපසිරස සමග Movies & TV Series 🇱🇰\n\n"
            "📩 ඔයාට ඕන Movie / Series එකේ නම මෙතන type කරන්න, අපි ඒක add කරන්නම්!",
            parse_mode="HTML", reply_markup=kb,
        )
        return
    await update.message.reply_text(
        "👋 <b>Admin Panel</b>\n\n"
        "🔎 Movie / TV series නමක් type කරලා manual post එකක් හදන්න\n\n"
        "<b>Commands</b>\n"
        "/autopost on|off – auto post පාලනය\n"
        "/stats – සංඛ්‍යා ලේඛන\n"
        "/last – අන්තිමට post කළ 5\n"
        "/requests – members ලාගේ requests\n"
        "/repost &lt;id&gt; – movie එකක් ආයෙ post කරන්න",
        parse_mode="HTML",
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: {update.effective_user.id}")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await handle_request(update, context)
        return
    text = update.message.text.strip()

    # Step 1: search
    context.user_data.clear()
    try:
        results = await search(text)
    except Exception:
        log.exception("search failed")
        await update.message.reply_text("⚠️ TMDB error. පස්සේ try කරන්න.")
        return
    if not results:
        await update.message.reply_text("😕 කිසිවක් හම්බුනේ නෑ. වෙන නමකින් try කරන්න.")
        return

    lines = ["🔎 <b>Results</b> — අංකය තොරන්න:\n"]
    buttons = []
    for i, r in enumerate(results, 1):
        t = r.get("title") or r.get("name")
        y = (r.get("release_date") or r.get("first_air_date") or "")[:4]
        icon = "🎬" if r["media_type"] == "movie" else "📺"
        lines.append(f"{i}. {icon} {html.escape(t)} ({y}) ⭐{r.get('vote_average', 0):.1f}")
        buttons.append(
            InlineKeyboardButton(str(i), callback_data=f"pick:{r['media_type']}:{r['id']}")
        )
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows)
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if update.effective_user.id not in ADMIN_IDS:
        return
    data = q.data
    if data.startswith("rq:"):
        await handle_req_action(update, context)
        return

    if data.startswith("pick:"):
        _, media_type, tmdb_id = data.split(":")
        d = await details(media_type, int(tmdb_id))
        poster = f"{IMG}{d['poster_path']}" if d.get("poster_path") else None
        context.user_data["post"] = {
            "caption": build_caption(d, media_type),
            "poster": poster,
            "trailer": trailer_url(d),
        }
        context.user_data["download_url"] = DOWNLOAD_URL
        await send_post(context.bot, update.effective_chat.id, context.user_data["post"], DOWNLOAD_URL)
        await q.message.reply_text(
            "👆 Preview එක. Channel එකට යවමුද?",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("✅ Post to Channel", callback_data="post"),
                    InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
                ]]
            ),
        )

    elif data == "post":
        post = context.user_data.get("post")
        url = context.user_data.get("download_url")
        if not post or not url:
            await q.message.reply_text("⚠️ Session expire. ආයෙ නමක් එවන්න.")
            return
        try:
            await send_post(context.bot, CHANNEL_ID, post, url)
            await q.edit_message_text("✅ Channel එකට post කළා!")
        except Exception as ex:
            log.exception("post failed")
            await q.edit_message_text(f"❌ Failed: {ex}\nBot එක channel admin ද බලන්න.")
        context.user_data.clear()

    elif data == "cancel":
        context.user_data.clear()
        await q.edit_message_text("❌ Cancel කළා.")


# ---------- PREMIUM EXTRAS ----------
AUTOPOST = True
REQ_COOLDOWN = 60
_last_req: dict = {}


_requests: dict = {}   # rid -> record (cache)
_req_msgs: dict = {}   # rid -> [(admin_chat_id, message_id)]

STATUS_LINE = {
    "pending": "⏳ <b>Pending</b>",
    "seen": "👀 <b>Seen</b>",
    "added": "✅ <b>Added</b>",
    "rejected": "❌ <b>Not available</b>",
}
STATUS_ICON = {"pending": "⏳", "seen": "👀", "added": "✅", "rejected": "❌"}


def req_text(rec: dict) -> str:
    line = STATUS_LINE.get(rec["status"], rec["status"])
    if rec.get("by") and rec["status"] != "pending":
        line += f" — {html.escape(rec['by'])}"
    return (
        "📩 <b>New Request</b>\n"
        f"🎬 {html.escape(rec['text'])}\n"
        f"👤 <a href=\"tg://user?id={rec['uid']}\">{html.escape(rec['name'])}</a>\n"
        f"📌 {line}"
    )


def req_keyboard(rec: dict):
    rid, st = rec["id"], rec["status"]
    if st == "pending":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 Seen", callback_data=f"rq:seen:{rid}")],
            [
                InlineKeyboardButton("✅ Added", callback_data=f"rq:added:{rid}"),
                InlineKeyboardButton("❌ Not available", callback_data=f"rq:rejected:{rid}"),
            ],
        ])
    if st == "seen":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Added", callback_data=f"rq:added:{rid}"),
            InlineKeyboardButton("❌ Not available", callback_data=f"rq:rejected:{rid}"),
        ]])
    return None


async def save_req(rec: dict):
    try:
        await fb_put(f"telegram_bot/requests/{rec['id']}", rec)
    except Exception:
        log.warning("could not save request %s", rec["id"])


async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()[:100]
    if not text:
        return
    now = time.time()
    wait = REQ_COOLDOWN - (now - _last_req.get(user.id, 0))
    if wait > 0:
        await update.message.reply_text(f"⏳ තව තත්පර {int(wait)}කින් ආයෙ request කරන්න.")
        return
    _last_req[user.id] = now

    rec = {
        "id": str(int(now * 1000)), "uid": user.id, "name": user.full_name or "User",
        "text": text, "status": "pending", "ts": int(now * 1000),
    }
    _requests[rec["id"]] = rec
    _req_msgs[rec["id"]] = []
    for admin in ADMIN_IDS:
        try:
            msg = await context.bot.send_message(
                admin, req_text(rec), parse_mode="HTML", reply_markup=req_keyboard(rec)
            )
            _req_msgs[rec["id"]].append((admin, msg.message_id))
        except Exception:
            pass
    await save_req(rec)
    await update.message.reply_text(
        "✅ ඔයාගේ request එක ලැබුණා!\nAdmin දැක්කම ඔයාට දැනුම් දෙන්නම් 🎬"
    )


async def handle_req_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, action, rid = q.data.split(":", 2)
    rec = _requests.get(rid)
    if rec is None:
        try:
            rec = await fb_get(f"telegram_bot/requests/{rid}")
        except Exception:
            rec = None
    if not isinstance(rec, dict):
        await q.edit_message_text("⚠️ ඒ request එක හොයාගන්න බෑ.")
        return
    _requests[rid] = rec
    if rec["status"] == action or rec["status"] in ("added", "rejected"):
        try:
            await q.answer("දැනටමත් update කරලා ✔️")
        except Exception:
            pass
        return

    rec["status"] = action
    rec["by"] = update.effective_user.first_name or "Admin"
    await save_req(rec)

    # update every admin's copy of the message
    targets = _req_msgs.get(rid) or [(q.message.chat_id, q.message.message_id)]
    for chat_id, msg_id in targets:
        try:
            await context.bot.edit_message_text(
                req_text(rec), chat_id=chat_id, message_id=msg_id,
                parse_mode="HTML", reply_markup=req_keyboard(rec),
            )
        except Exception:
            pass

    # tell the member
    title = html.escape(rec["text"])
    kb = None
    if action == "seen":
        msg = f"👀 <b>ඔයාගේ request එක admin දැක්කා!</b>\n🎬 {title}\nඉක්මනින් add කරන්නම්."
    elif action == "added":
        msg = f"✅ <b>ඔයාගේ request එක add කළා!</b>\n🎬 {title}\nදැන් site එකෙන් බලන්න 👇"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Website", url=SITE_URL)]])
    else:
        msg = f"❌ සමාවෙන්න, <b>{title}</b> දැනට ලබාගන්න අමාරුයි."
    try:
        await context.bot.send_message(rec["uid"], msg, parse_mode="HTML", reply_markup=kb)
    except Exception:
        try:
            await q.answer("Member ට message යවන්න බැරි වුණා", show_alert=True)
        except Exception:
            pass


async def requests_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        data = await fb_get("telegram_bot/requests", orderBy='"$key"', limitToLast="10") or {}
    except Exception:
        await update.message.reply_text("⚠️ Firebase error.")
        return
    recs = sorted(
        (r for r in data.values() if isinstance(r, dict)),
        key=lambda r: num(r.get("ts")), reverse=True,
    )
    if not recs:
        await update.message.reply_text("📭 Requests නෑ.")
        return
    pending = sum(1 for r in recs if r.get("status") in ("pending", "seen"))
    lines = [f"📩 <b>Requests</b> (අන්තිම {len(recs)}, pending: {pending})\n"]
    for r in recs:
        icon = STATUS_ICON.get(r.get("status"), "•")
        lines.append(f"{icon} {html.escape(str(r.get('text')))} — {html.escape(str(r.get('name')))}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def autopost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTOPOST
    if not is_admin(update):
        return
    arg = context.args[0].lower() if context.args else ""
    if arg in ("on", "off"):
        AUTOPOST = arg == "on"
        try:
            await fb_put("telegram_bot/autopost", AUTOPOST)
        except Exception:
            log.warning("could not save autopost setting")
    state = "ON ✅" if AUTOPOST else "OFF ⏸"
    await update.message.reply_text(f"🤖 Auto post: {state}\n\n/autopost on  |  /autopost off")


def num(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def fmt(n: int) -> str:
    return f"{n:,}"


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    wait = await update.message.reply_text("⏳ Stats ගන්නවා...")
    try:
        movies = await fb_get("movies") or {}
        deleted = await fb_get("analytics/deletedStats") or {}
        visitors_total = num(await fb_get("analytics/totalVisitors"))
        hist = await fb_get("telegram_bot/history") or {}
        daily = {}
        for name in ("viewsDaily", "downloadsDaily", "onlineWatchDaily", "visitorsDaily"):
            daily[name] = await fb_get(
                f"analytics/{name}", orderBy='"$key"', limitToLast="7"
            ) or {}
    except Exception:
        log.exception("stats failed")
        await wait.edit_text("⚠️ Firebase error. පස්සේ try කරන්න.")
        return

    items = [(k, v) for k, v in movies.items() if isinstance(v, dict)]
    views = sum(num(v.get("views")) for _, v in items) + num(deleted.get("totalViews"))
    dls = sum(num(v.get("downloads_count")) for _, v in items) + num(deleted.get("totalDownloads"))
    watch = sum(num(v.get("online_watch")) for _, v in items) + num(deleted.get("totalOnlineWatch"))

    # site stores day keys as YYYY-MM-DD (Sri Lanka time)
    lk = timezone(timedelta(hours=5, minutes=30))
    today_key = datetime.now(lk).strftime("%Y-%m-%d")
    week_keys = [(datetime.now(lk) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    def today(name):
        return num(daily[name].get(today_key))

    def week(name):
        return sum(num(daily[name].get(k)) for k in week_keys)

    now_ms = time.time() * 1000
    hist_items = [h for h in hist.values() if isinstance(h, dict)]
    posted_24h = sum(1 for h in hist_items if now_ms - num(h.get("ts")) < 86400000)

    def top(field, n):
        ranked = sorted(items, key=lambda kv: num(kv[1].get(field)), reverse=True)[:n]
        return [
            f"{i}. {html.escape(str(v.get('title', k)))} — <b>{fmt(num(v.get(field)))}</b>"
            for i, (k, v) in enumerate(ranked, 1) if num(v.get(field)) > 0
        ]

    lines = [
        "📊 <b>MovieMania Stats</b>",
        SEP,
        f"🎞 Titles: <b>{fmt(len(items))}</b>   📤 Bot posts: <b>{fmt(len(hist_items))}</b>",
        "",
        "🏆 <b>All time</b>",
        f"👁 Views: <b>{fmt(views)}</b>",
        f"📥 Downloads: <b>{fmt(dls)}</b>",
        f"▶️ Online Watch: <b>{fmt(watch)}</b>",
        f"👥 Visitors: <b>{fmt(visitors_total)}</b>",
        "",
        "📅 <b>Today</b>",
        f"👁 {fmt(today('viewsDaily'))}  |  📥 {fmt(today('downloadsDaily'))}  |  "
        f"▶️ {fmt(today('onlineWatchDaily'))}  |  👥 {fmt(today('visitorsDaily'))}",
        "",
        "📆 <b>Last 7 days</b>",
        f"👁 {fmt(week('viewsDaily'))}  |  📥 {fmt(week('downloadsDaily'))}  |  "
        f"▶️ {fmt(week('onlineWatchDaily'))}  |  👥 {fmt(week('visitorsDaily'))}",
    ]
    tv, td = top("views", 5), top("downloads_count", 3)
    if tv:
        lines += ["", "🔥 <b>Top viewed</b>"] + tv
    if td:
        lines += ["", "⬇️ <b>Top downloaded</b>"] + td
    lines += [
        "", SEP,
        f"🤖 Auto post: <b>{'ON' if AUTOPOST else 'OFF'}</b>   🕐 Posted 24h: <b>{posted_24h}</b>",
    ]
    await wait.edit_text("\n".join(lines), parse_mode="HTML")


async def last_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        hist = await fb_get("telegram_bot/history") or {}
    except Exception:
        await update.message.reply_text("⚠️ Firebase error.")
        return
    items = sorted(
        (h for h in hist.values() if isinstance(h, dict)),
        key=lambda h: float(h.get("ts", 0)), reverse=True,
    )[:5]
    if not items:
        await update.message.reply_text("තාම post history එකක් නෑ.")
        return
    lines = ["🕘 <b>Last posts</b>\n"]
    for i, h in enumerate(items, 1):
        lines.append(f"{i}. {html.escape(str(h.get('title', '?')))}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def repost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /repost movie-id\n(උදා: /repost buddy-21)")
        return
    movie_id = context.args[0]
    try:
        m = await fb_get(f"movies/{movie_id}")
        if not isinstance(m, dict):
            await update.message.reply_text("❌ ඒ ID එකෙන් movie එකක් නෑ.")
            return
        await post_site_movie(context.bot, movie_id, m)
        await update.message.reply_text(f"✅ Reposted: {m.get('title')}")
    except Exception as ex:
        log.exception("repost failed")
        await update.message.reply_text(f"❌ Failed: {ex}")


# ---------- AUTO POST (admin panel -> channel) ----------
async def fb_get(path: str, **params):
    if FIREBASE_API_KEY:
        params["key"] = FIREBASE_API_KEY
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{FIREBASE_DB_URL}/{path}.json", params=params)
        r.raise_for_status()
        return r.json()


async def fb_put(path: str, value):
    params = {"key": FIREBASE_API_KEY} if FIREBASE_API_KEY else {}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(f"{FIREBASE_DB_URL}/{path}.json", params=params, json=value)
        r.raise_for_status()


def site_caption(m: dict) -> str:
    try:
        rating = float(m.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0
    genres = [g.strip() for g in str(m.get("genre") or "").split(",") if g.strip()]
    kind = "📺" if m.get("type") in ("tv", "series") else "🎬"
    return render_card(
        m.get("title") or "Unknown", m.get("year") or "", kind, rating, genres,
        m.get("runtime"), m.get("quality"), m.get("country"),
        m.get("director"), m.get("cast"), m.get("description"),
    )


def movie_link(movie_id: str, m: dict) -> str:
    kind = "tv" if m.get("type") in ("tv", "series") else "movie"
    return f"{SITE_URL}/{kind}/{movie_id}-sinhala-subtitles"


async def post_site_movie(bot, movie_id: str, m: dict):
    caption = site_caption(m)
    kb = post_keyboard(movie_link(movie_id, m), (m.get("trailer") or "").strip() or None)
    poster = (m.get("poster") or m.get("backdrop") or "").strip()
    if poster.startswith("http"):
        try:
            await bot.send_photo(CHANNEL_ID, poster, caption=caption, parse_mode="HTML", reply_markup=kb)
            return
        except Exception:
            log.exception("photo failed, sending text")
    await bot.send_message(CHANNEL_ID, caption, parse_mode="HTML", reply_markup=kb)


def is_due(m: dict) -> bool:
    sched = m.get("scheduledAt")
    return not sched or float(sched) <= time.time() * 1000


async def check_new_movies(bot, posted: set):
    keys = await fb_get("movies", shallow="true") or {}
    for movie_id in keys:
        if movie_id in posted:
            continue
        m = await fb_get(f"movies/{movie_id}")
        if not isinstance(m, dict) or not is_due(m):
            continue  # scheduled for later - check again next round
        if m.get("adult"):
            posted.add(movie_id)  # never auto-post adult content
            continue
        try:
            await post_site_movie(bot, movie_id, m)
        except Exception:
            log.exception("auto post failed: %s", movie_id)
            continue
        posted.add(movie_id)
        try:
            await fb_put(f"{POSTED_PATH}/{movie_id}", True)
        except Exception:
            log.warning("could not persist posted flag for %s", movie_id)
        try:
            await fb_put(
                f"telegram_bot/history/{movie_id}",
                {"title": m.get("title"), "ts": int(time.time() * 1000)},
            )
        except Exception:
            pass
        for admin in ADMIN_IDS:
            try:
                await bot.send_message(admin, f"✅ Auto posted: {m.get('title')}")
            except Exception:
                pass
        await asyncio.sleep(3)  # Telegram flood control


async def auto_post_loop(app: Application):
    if not FIREBASE_DB_URL:
        log.warning("FIREBASE_DB_URL not set - auto post disabled")
        return
    bot = app.bot
    global AUTOPOST
    try:
        if await fb_get("telegram_bot/autopost") is False:
            AUTOPOST = False
    except Exception:
        pass
    # Load already-posted ids. First ever run: mark everything existing as posted
    # so the channel is not flooded with old movies.
    try:
        saved = await fb_get(POSTED_PATH)
        if saved is None:
            keys = await fb_get("movies", shallow="true") or {}
            posted = set(keys)
            try:
                await fb_put(POSTED_PATH, {k: True for k in posted} or {"_init": True})
            except Exception:
                log.warning("Firebase write not allowed - posted list kept in memory only")
        else:
            posted = set(saved)
    except Exception:
        log.exception("auto post init failed")
        return
    log.info("Auto post started (%d known movies)", len(posted))

    while True:
        try:
            if AUTOPOST:
                await check_new_movies(bot, posted)
        except Exception:
            log.exception("auto post check failed")
        await asyncio.sleep(POLL_SECONDS)


async def post_init(app: Application):
    asyncio.create_task(auto_post_loop(app))


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("autopost", autopost_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("last", last_cmd))
    app.add_handler(CommandHandler("repost", repost_cmd))
    app.add_handler(CommandHandler("requests", requests_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
