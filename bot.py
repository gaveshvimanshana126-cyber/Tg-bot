import os
import html
import time
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
def build_caption(d: dict, media_type: str) -> str:
    e = html.escape
    title = d.get("title") or d.get("name") or "Unknown"
    date = d.get("release_date") or d.get("first_air_date") or ""
    year = date[:4]
    rating = d.get("vote_average") or 0
    genres = ", ".join(g["name"] for g in d.get("genres", [])) or "N/A"
    lang = (d.get("original_language") or "").upper()

    if media_type == "movie":
        mins = d.get("runtime") or 0
        runtime = f"{mins // 60}h {mins % 60}m" if mins else "N/A"
    else:
        eps = d.get("episode_run_time") or []
        runtime = f"{eps[0]}m / ep" if eps else "N/A"

    credits = d.get("credits", {})
    cast = ", ".join(c["name"] for c in credits.get("cast", [])[:5]) or "N/A"
    directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"]
    director = ", ".join(directors[:2]) or "N/A"

    overview = (d.get("overview") or "").strip()
    if len(overview) > 350:
        overview = overview[:347].rsplit(" ", 1)[0] + "..."

    lines = [
        f"🎬 <b>{e(title)}</b> ({e(year)})" if year else f"🎬 <b>{e(title)}</b>",
        "",
        f"⭐ <b>Rating:</b> {rating:.1f}/10",
        f"🎭 <b>Genre:</b> {e(genres)}",
        f"⏱ <b>Runtime:</b> {e(runtime)}",
        f"🌐 <b>Language:</b> {e(lang)}",
        f"🎥 <b>Director:</b> {e(director)}",
        f"👥 <b>Cast:</b> {e(cast)}",
    ]
    if overview:
        lines += ["", f"📝 <i>{e(overview)}</i>"]
    lines += ["", "🇱🇰 <b>සිංහල උපසිරස සමග Download කරගැනිමට හා Online නැරඹිමට පිවිසෙන්න</b> 👇"]
    return "\n".join(lines)


def trailer_url(d: dict):
    for v in d.get("videos", {}).get("results", []):
        if v.get("site") == "YouTube" and v.get("type") == "Trailer":
            return f"https://www.youtube.com/watch?v={v['key']}"
    return None


def post_keyboard(download_url: str, trailer: str | None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📥 Download Now", url=download_url)]]
    if trailer:
        rows.append([InlineKeyboardButton("▶️ Trailer", url=trailer)])
    rows.append(
        [
            InlineKeyboardButton("💬 WhatsApp Channel", url=WHATSAPP_URL),
            InlineKeyboardButton("👍 Facebook Page", url=FB_URL),
        ]
    )
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
        await update.message.reply_text("⛔ මේ bot එක admin ලාට විතරයි.")
        return
    await update.message.reply_text(
        "👋 Admin Panel\n\nMovie / TV series නමක් type කරන්න 🔎"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: {update.effective_user.id}")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
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
    e = html.escape
    title = m.get("title") or "Unknown"
    year = m.get("year") or ""
    kind = "📺" if m.get("type") in ("tv", "series") else "🎬"
    lines = [f"{kind} <b>{e(title)}</b>" + (f" ({e(str(year))})" if year else ""), ""]

    def add(icon, label, val):
        if val:
            lines.append(f"{icon} <b>{label}:</b> {e(str(val))}")

    try:
        rating = float(m.get("rating") or 0)
    except ValueError:
        rating = 0
    if rating:
        lines.append(f"⭐ <b>Rating:</b> {rating:.1f}/10")
    add("🎭", "Genre", m.get("genre"))
    add("⏱", "Runtime", m.get("runtime"))
    add("💿", "Quality", m.get("quality"))
    add("🌍", "Country", m.get("country"))
    add("🎥", "Director", m.get("director"))
    add("👥", "Cast", m.get("cast"))

    desc = (m.get("description") or "").strip()
    if len(desc) > 300:
        desc = desc[:297].rsplit(" ", 1)[0] + "..."
    if desc:
        lines += ["", f"📝 <i>{e(desc)}</i>"]
    lines += ["", "🇱🇰 <b>සිංහල උපසිරස සමග Download කරගැනිමට හා Online නැරඹිමට පිවිසෙන්න</b> 👇"]
    return "\n".join(lines)[:1024]


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
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
