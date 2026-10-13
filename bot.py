import os
import html
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
        await update.message.reply_text("⛔admin only.")
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


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
