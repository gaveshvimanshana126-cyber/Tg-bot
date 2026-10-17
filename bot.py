import os
import re
import html
import random
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
SUB_BY = os.environ.get("SUB_BY", "Piratelk.com")
REQUEST_BOT_URL = os.environ.get("REQUEST_BOT_URL", "https://t.me/Moviemanialkrequest_bot")
POSTED_PATH = "telegram_bot/posted"
POSTED: set = set()  # ids already handled (shared by auto-post + /add)

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
        f"/{media_type}/{tmdb_id}", append_to_response="credits,videos,images",
        include_image_language="en,null",
    )


# ---------- POST BUILDER ----------
SEP = "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”"
SINHALA_LINE = "ðŸ‡±ðŸ‡° <b>à·ƒà·’à¶‚à·„à¶½ à¶‹à¶´à·ƒà·’à¶»à·ƒ à·ƒà¶¸à¶œ Download à¶šà¶»à¶œà·à¶±à·’à¶¸à¶§ à·„à· Online à¶±à·à¶»à¶¹à·’à¶¸à¶§ à¶´à·’à·€à·’à·ƒà·™à¶±à·Šà¶±</b> ðŸ‘‡"


def stars(rating: float) -> str:
    full = int(round(rating / 2))
    return "â˜…" * full + "â˜†" * (5 - full)


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
        lines.append(f"â­ <b>{rating:.1f}</b>/10  {stars(rating)}")
    if genres:
        lines.append("ðŸŽ­ " + " â€¢ ".join(e(g) for g in genres))
    meta = []
    if runtime:
        meta.append(f"â± {e(str(runtime))}")
    if quality:
        meta.append(f"ðŸ’¿ {e(str(quality))}")
    if country:
        meta.append(f"ðŸŒ {e(str(country))}")
    if meta:
        lines.append("  |  ".join(meta))
    lines.append(SEP)
    if director:
        lines.append(f"ðŸŽ¥ <b>Director:</b> {e(str(director))}")
    if cast:
        lines.append(f"ðŸ‘¥ <b>Cast:</b> {e(str(cast))}")

    tail = ["", SINHALA_LINE, "", hashtags(genres, str(year or ""))]
    overview = (overview or "").strip()
    limit = 300
    while True:
        body = list(lines)
        if overview:
            ov = overview if len(overview) <= limit else overview[: limit - 3].rsplit(" ", 1)[0] + "..."
            body += ["", f"<blockquote expandable>ðŸ“ {e(ov)}</blockquote>"]
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
        title, date[:4], "ðŸŽ¬" if media_type == "movie" else "ðŸ“º",
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
        btn("ðŸ“¥ Download Now", download_url, "primary"),   # blue
        btn("â–¶ï¸ Watch Online", download_url, "danger"),    # red
    ]]
    if trailer:
        rows.append([btn("ðŸŽž Watch Trailer", trailer)])
    rows.append([btn("ðŸŽ¬ Request Movie", REQUEST_BOT_URL, "success")])  # green
    rows.append([
        btn("ðŸ’¬ WhatsApp", WHATSAPP_URL, "success"),       # green
        btn("ðŸ‘ Facebook", FB_URL, "primary"),             # blue
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
            [btn("ðŸŒ Website", SITE_URL, "primary")],
            [
                btn("ðŸ’¬ WhatsApp", WHATSAPP_URL, "success"),
                btn("ðŸ‘ Facebook", FB_URL, "primary"),
            ],
        ])
        await update.message.reply_text(
            "ðŸŽ¬ <b>MovieMania LK</b>\n\n"
            "à·ƒà·’à¶‚à·„à¶½ à¶‹à¶´à·ƒà·’à¶»à·ƒ à·ƒà¶¸à¶œ Movies & TV Series ðŸ‡±ðŸ‡°\n\n"
            "ðŸ“© à¶”à¶ºà·à¶§ à¶•à¶± Movie / Series à¶‘à¶šà·š à¶±à¶¸ à¶¸à·™à¶­à¶± type à¶šà¶»à¶±à·Šà¶±, à¶…à¶´à·’ à¶’à¶š add à¶šà¶»à¶±à·Šà¶±à¶¸à·Š!",
            parse_mode="HTML", reply_markup=kb,
        )
        return
    await update.message.reply_text(
        "ðŸ‘‹ <b>Admin Panel</b>\n\n"
        "âž• /add â€“ Movie à¶‘à¶šà¶šà·Š site à¶‘à¶šà¶§ add à¶šà¶»à¶±à·Šà¶± (TMDB)\n"
        "ðŸ”Ž Movie à¶±à¶¸à¶šà·Š type à¶šà¶»à¶½à· manual post à¶‘à¶šà¶šà·Š à·„à¶¯à¶±à·Šà¶±\n\n"
        "<b>Commands</b>\n"
        "/autopost on|off â€“ auto post à¶´à·à¶½à¶±à¶º\n"
        "/add â€“ movie à¶‘à¶šà¶šà·Š site à¶‘à¶šà¶§ add à¶šà¶»à¶±à·Šà¶±\n"
        "/stats â€“ à·ƒà¶‚à¶›à·Šâ€à¶ºà· à¶½à·šà¶›à¶±\n"
        "/last â€“ à¶…à¶±à·Šà¶­à·’à¶¸à¶§ post à¶šà·… 5\n"
        "/requests â€“ members à¶½à·à¶œà·š requests\n"
        "/find &lt;name&gt; â€“ site à¶‘à¶šà·š movie à·„à·œà¶ºà¶±à·Šà¶±\n"
        "/version â€“ bot version\n"
        "/vip &lt;id&gt; â€“ VIP on/off\n"
        "/del &lt;id&gt; â€“ movie delete\n"
        "/repost &lt;id&gt; â€“ movie à¶‘à¶šà¶šà·Š à¶†à¶ºà·™ post à¶šà¶»à¶±à·Šà¶±",
        parse_mode="HTML",
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: {update.effective_user.id}")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await handle_request(update, context)
        return
    text = update.message.text.strip()

    # Add-to-site flow (waiting for links / player / description / subtitle by ...)
    if context.user_data.get("state") in ("add_links", "add_sub", "add_desc", "add_subby", "add_player"):
        await handle_add_input(update, context, text)
        return

    # Step 1: search
    context.user_data.clear()
    try:
        results = await search(text)
    except Exception:
        log.exception("search failed")
        await update.message.reply_text("âš ï¸ TMDB error. à¶´à·ƒà·Šà·ƒà·š try à¶šà¶»à¶±à·Šà¶±.")
        return
    if not results:
        await update.message.reply_text("ðŸ˜• à¶šà·’à·ƒà·’à·€à¶šà·Š à·„à¶¸à·Šà¶¶à·”à¶±à·š à¶±à·‘. à·€à·™à¶± à¶±à¶¸à¶šà·’à¶±à·Š try à¶šà¶»à¶±à·Šà¶±.")
        return

    lines = ["ðŸ”Ž <b>Results</b> â€” à¶…à¶‚à¶šà¶º à¶­à·œà¶»à¶±à·Šà¶±:\n"]
    buttons = []
    for i, r in enumerate(results, 1):
        t = r.get("title") or r.get("name")
        y = (r.get("release_date") or r.get("first_air_date") or "")[:4]
        icon = "ðŸŽ¬" if r["media_type"] == "movie" else "ðŸ“º"
        lines.append(f"{i}. {icon} {html.escape(t)} ({y}) â­{r.get('vote_average', 0):.1f}")
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
    if data.startswith(("add:", "del:", "vip:")):
        await handle_site_action(update, context)
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
        context.user_data["tmdb"] = (d, media_type)
        await send_post(context.bot, update.effective_chat.id, context.user_data["post"], DOWNLOAD_URL)
        await q.message.reply_text(
            "ðŸ‘† Preview à¶‘à¶š. à¶¸à·œà¶šà¶šà·Š à¶šà¶»à¶¸à·”à¶¯?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("âž• Site à¶‘à¶šà¶§ Add à¶šà¶»à¶±à·Šà¶±", callback_data="add:start")],
                    [
                        InlineKeyboardButton("ðŸ“£ Channel post only", callback_data="post"),
                        InlineKeyboardButton("âŒ Cancel", callback_data="cancel"),
                    ],
                ]
            ),
        )

    elif data == "post":
        post = context.user_data.get("post")
        url = context.user_data.get("download_url")
        if not post or not url:
            await q.message.reply_text("âš ï¸ Session expire. à¶†à¶ºà·™ à¶±à¶¸à¶šà·Š à¶‘à·€à¶±à·Šà¶±.")
            return
        try:
            await send_post(context.bot, CHANNEL_ID, post, url)
            await q.edit_message_text("âœ… Channel à¶‘à¶šà¶§ post à¶šà·…à·!")
        except Exception as ex:
            log.exception("post failed")
            await q.edit_message_text(f"âŒ Failed: {ex}\nBot à¶‘à¶š channel admin à¶¯ à¶¶à¶½à¶±à·Šà¶±.")
        context.user_data.clear()

    elif data == "cancel":
        context.user_data.clear()
        await q.edit_message_text("âŒ Cancel à¶šà·…à·.")


# ---------- PREMIUM EXTRAS ----------
AUTOPOST = True
REQ_COOLDOWN = 60
_last_req: dict = {}


_requests: dict = {}   # rid -> record (cache)
_req_msgs: dict = {}   # rid -> [(admin_chat_id, message_id)]

STATUS_LINE = {
    "pending": "â³ <b>Pending</b>",
    "seen": "ðŸ‘€ <b>Seen</b>",
    "added": "âœ… <b>Added</b>",
    "rejected": "âŒ <b>Not available</b>",
}
STATUS_ICON = {"pending": "â³", "seen": "ðŸ‘€", "added": "âœ…", "rejected": "âŒ"}


def req_text(rec: dict) -> str:
    line = STATUS_LINE.get(rec["status"], rec["status"])
    if rec.get("by") and rec["status"] != "pending":
        line += f" â€” {html.escape(rec['by'])}"
    return (
        "ðŸ“© <b>New Request</b>\n"
        f"ðŸŽ¬ {html.escape(rec['text'])}\n"
        f"ðŸ‘¤ <a href=\"tg://user?id={rec['uid']}\">{html.escape(rec['name'])}</a>\n"
        f"ðŸ“Œ {line}"
    )


def req_keyboard(rec: dict):
    rid, st = rec["id"], rec["status"]
    if st == "pending":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("ðŸ‘€ Seen", callback_data=f"rq:seen:{rid}")],
            [
                InlineKeyboardButton("âœ… Added", callback_data=f"rq:added:{rid}"),
                InlineKeyboardButton("âŒ Not available", callback_data=f"rq:rejected:{rid}"),
            ],
        ])
    if st == "seen":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("âœ… Added", callback_data=f"rq:added:{rid}"),
            InlineKeyboardButton("âŒ Not available", callback_data=f"rq:rejected:{rid}"),
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
        await update.message.reply_text(f"â³ à¶­à·€ à¶­à¶­à·Šà¶´à¶» {int(wait)}à¶šà·’à¶±à·Š à¶†à¶ºà·™ request à¶šà¶»à¶±à·Šà¶±.")
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
        "âœ… à¶”à¶ºà·à¶œà·š request à¶‘à¶š à¶½à·à¶¶à·”à¶«à·!\nAdmin à¶¯à·à¶šà·Šà¶šà¶¸ à¶”à¶ºà·à¶§ à¶¯à·à¶±à·”à¶¸à·Š à¶¯à·™à¶±à·Šà¶±à¶¸à·Š ðŸŽ¬"
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
        await q.edit_message_text("âš ï¸ à¶’ request à¶‘à¶š à·„à·œà¶ºà·à¶œà¶±à·Šà¶± à¶¶à·‘.")
        return
    _requests[rid] = rec
    if rec["status"] == action or rec["status"] in ("added", "rejected"):
        try:
            await q.answer("à¶¯à·à¶±à¶§à¶¸à¶­à·Š update à¶šà¶»à¶½à· âœ”ï¸")
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
        msg = f"ðŸ‘€ <b>à¶”à¶ºà·à¶œà·š request à¶‘à¶š admin à¶¯à·à¶šà·Šà¶šà·!</b>\nðŸŽ¬ {title}\nà¶‰à¶šà·Šà¶¸à¶±à·’à¶±à·Š add à¶šà¶»à¶±à·Šà¶±à¶¸à·Š."
    elif action == "added":
        msg = f"âœ… <b>à¶”à¶ºà·à¶œà·š request à¶‘à¶š add à¶šà·…à·!</b>\nðŸŽ¬ {title}\nà¶¯à·à¶±à·Š site à¶‘à¶šà·™à¶±à·Š à¶¶à¶½à¶±à·Šà¶± ðŸ‘‡"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("ðŸŒ Open Website", url=SITE_URL)]])
    else:
        msg = f"âŒ à·ƒà¶¸à·à·€à·™à¶±à·Šà¶±, <b>{title}</b> à¶¯à·à¶±à¶§ à¶½à¶¶à·à¶œà¶±à·Šà¶± à¶…à¶¸à·à¶»à·”à¶ºà·’."
    try:
        await context.bot.send_message(rec["uid"], msg, parse_mode="HTML", reply_markup=kb)
    except Exception:
        try:
            await q.answer("Member à¶§ message à¶ºà·€à¶±à·Šà¶± à¶¶à·à¶»à·’ à·€à·”à¶«à·", show_alert=True)
        except Exception:
            pass


async def requests_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        data = await fb_get("telegram_bot/requests", orderBy='"$key"', limitToLast="10") or {}
    except Exception:
        await update.message.reply_text("âš ï¸ Firebase error.")
        return
    recs = sorted(
        (r for r in data.values() if isinstance(r, dict)),
        key=lambda r: num(r.get("ts")), reverse=True,
    )
    if not recs:
        await update.message.reply_text("ðŸ“­ Requests à¶±à·‘.")
        return
    pending = sum(1 for r in recs if r.get("status") in ("pending", "seen"))
    lines = [f"ðŸ“© <b>Requests</b> (à¶…à¶±à·Šà¶­à·’à¶¸ {len(recs)}, pending: {pending})\n"]
    for r in recs:
        icon = STATUS_ICON.get(r.get("status"), "â€¢")
        lines.append(f"{icon} {html.escape(str(r.get('text')))} â€” {html.escape(str(r.get('name')))}")
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
    state = "ON âœ…" if AUTOPOST else "OFF â¸"
    await update.message.reply_text(f"ðŸ¤– Auto post: {state}\n\n/autopost on  |  /autopost off")


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
    wait = await update.message.reply_text("â³ Stats à¶œà¶±à·Šà¶±à·€à·...")
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
        await wait.edit_text("âš ï¸ Firebase error. à¶´à·ƒà·Šà·ƒà·š try à¶šà¶»à¶±à·Šà¶±.")
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
            f"{i}. {html.escape(str(v.get('title', k)))} â€” <b>{fmt(num(v.get(field)))}</b>"
            for i, (k, v) in enumerate(ranked, 1) if num(v.get(field)) > 0
        ]

    lines = [
        "ðŸ“Š <b>MovieMania Stats</b>",
        SEP,
        f"ðŸŽž Titles: <b>{fmt(len(items))}</b>   ðŸ“¤ Bot posts: <b>{fmt(len(hist_items))}</b>",
        "",
        "ðŸ† <b>All time</b>",
        f"ðŸ‘ Views: <b>{fmt(views)}</b>",
        f"ðŸ“¥ Downloads: <b>{fmt(dls)}</b>",
        f"â–¶ï¸ Online Watch: <b>{fmt(watch)}</b>",
        f"ðŸ‘¥ Visitors: <b>{fmt(visitors_total)}</b>",
        "",
        "ðŸ“… <b>Today</b>",
        f"ðŸ‘ {fmt(today('viewsDaily'))}  |  ðŸ“¥ {fmt(today('downloadsDaily'))}  |  "
        f"â–¶ï¸ {fmt(today('onlineWatchDaily'))}  |  ðŸ‘¥ {fmt(today('visitorsDaily'))}",
        "",
        "ðŸ“† <b>Last 7 days</b>",
        f"ðŸ‘ {fmt(week('viewsDaily'))}  |  ðŸ“¥ {fmt(week('downloadsDaily'))}  |  "
        f"â–¶ï¸ {fmt(week('onlineWatchDaily'))}  |  ðŸ‘¥ {fmt(week('visitorsDaily'))}",
    ]
    tv, td = top("views", 5), top("downloads_count", 3)
    if tv:
        lines += ["", "ðŸ”¥ <b>Top viewed</b>"] + tv
    if td:
        lines += ["", "â¬‡ï¸ <b>Top downloaded</b>"] + td
    lines += [
        "", SEP,
        f"ðŸ¤– Auto post: <b>{'ON' if AUTOPOST else 'OFF'}</b>   ðŸ• Posted 24h: <b>{posted_24h}</b>",
    ]
    await wait.edit_text("\n".join(lines), parse_mode="HTML")


async def last_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        hist = await fb_get("telegram_bot/history") or {}
    except Exception:
        await update.message.reply_text("âš ï¸ Firebase error.")
        return
    items = sorted(
        (h for h in hist.values() if isinstance(h, dict)),
        key=lambda h: float(h.get("ts", 0)), reverse=True,
    )[:5]
    if not items:
        await update.message.reply_text("à¶­à·à¶¸ post history à¶‘à¶šà¶šà·Š à¶±à·‘.")
        return
    lines = ["ðŸ•˜ <b>Last posts</b>\n"]
    for i, h in enumerate(items, 1):
        lines.append(f"{i}. {html.escape(str(h.get('title', '?')))}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def repost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /repost movie-id\n(à¶‹à¶¯à·: /repost buddy-21)")
        return
    movie_id = context.args[0]
    try:
        m = await fb_get(f"movies/{movie_id}")
        if not isinstance(m, dict):
            await update.message.reply_text("âŒ à¶’ ID à¶‘à¶šà·™à¶±à·Š movie à¶‘à¶šà¶šà·Š à¶±à·‘.")
            return
        await post_site_movie(context.bot, movie_id, m)
        await update.message.reply_text(f"âœ… Reposted: {m.get('title')}")
    except Exception as ex:
        log.exception("repost failed")
        await update.message.reply_text(f"âŒ Failed: {ex}")


# ---------- SITE ADMIN (add / manage movies from Telegram) ----------
TMDB_IMG = "https://image.tmdb.org/t/p/"
QUALITIES = ["WEB-RIP", "WEB-DL", "BLURAY", "HD-RIP", "CAM", "CAMCOPY", "ORIGINAL WEB", "4K"]
SUB_BY = os.environ.get("SUB_BY", "Piratelk.com")


def pd_convert(url: str) -> str:
    """Same logic as pdConvert() in the admin panel (Pixeldrain share -> stream link)."""
    url = (url or "").strip()
    if not url:
        return url
    if re.search(r"pixeldrain\.com/api/file/[A-Za-z0-9_-]+$", url) and "?download" not in url:
        return url
    if "/api/file/" in url and "?download" in url:
        return url.replace("?download", "")
    m = re.search(r"pixeldrain\.com/[ul]/([A-Za-z0-9_-]+)", url)
    if m:
        return f"https://pixeldrain.com/api/file/{m.group(1)}"
    return url


def slugify(t: str) -> str:
    t = re.sub(r"['â€™`]", "", (t or "").lower())
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80] or "untitled"


async def unique_movie_id(title: str) -> str:
    import random
    base = slugify(title)
    for _ in range(8):
        cid = f"{base}-{random.randint(10, 99)}"
        if await fb_get(f"movies/{cid}") is None:
            return cid
    return f"{base}-{str(int(time.time() * 1000))[-4:]}"


def draft_from_tmdb(d: dict, media_type: str) -> dict:
    """Builds the same record the admin panel's saveMovie() writes."""
    vids = d.get("videos", {}).get("results", [])
    yt = [v for v in vids if v.get("site") == "YouTube"]
    trailer = (
        next((v for v in yt if v.get("type") == "Trailer" and v.get("official")), None)
        or next((v for v in yt if v.get("type") == "Trailer"), None)
        or (yt[0] if yt else None)
    )
    crew = d.get("credits", {}).get("crew", [])
    cast = d.get("credits", {}).get("cast", [])
    if d.get("production_countries"):
        country = ", ".join(c["name"] for c in d["production_countries"])
    else:
        country = ", ".join(d.get("origin_country") or [])
    mins = d.get("runtime") or 0
    backdrops = d.get("images", {}).get("backdrops", [])[:6]
    date = d.get("release_date") or d.get("first_air_date") or ""
    vote = d.get("vote_average") or 0
    coll = (d.get("belongs_to_collection") or {}).get("name", "")
    return {
        "title": d.get("title") or d.get("name") or "",
        "year": date[:4],
        "genre": ", ".join(g["name"] for g in d.get("genres", [])),
        "runtime": f"{mins // 60}h {mins % 60}m" if mins else "",
        "rating": f"{vote:.1f}" if vote else "",
        "description": d.get("overview") or "",
        "describedBy": "",
        "poster": f"{TMDB_IMG}original{d['poster_path']}" if d.get("poster_path") else "",
        "backdrop": f"{TMDB_IMG}original{d['backdrop_path']}" if d.get("backdrop_path") else "",
        "director": ", ".join(c["name"] for c in crew if c.get("job") == "Director"),
        "cast": ", ".join(c["name"] for c in cast[:8]),
        "country": country,
        "trailer": f"https://www.youtube.com/watch?v={trailer['key']}" if trailer else "",
        "screenshots": [f"{TMDB_IMG}original{b['file_path']}" for b in backdrops],
        "quality": "WEB-RIP",
        "type": media_type,
        "players": [],
        "subBy": SUB_BY,
        "subtitleUrl": "",
        "subUrl": "",
        "dlSubUrl": "",
        "adult": bool(d.get("adult")),
        "tmdbId": str(d.get("id") or ""),
        "collection": coll,
        "collectionOrder": 0,
        "adminNote": "",
        "downloads": [],
        "seasons": [],
        "seriesStatus": "ongoing",
        "isVip": False,
        "showSubNotice": False,
        "scheduledAt": None,
    }


def parse_links(text: str, quality: str):
    """Each line: any mix of resolution (720p), size (1.2GB) and a URL."""
    downloads, players = [], []
    for line in text.splitlines():
        um = re.search(r"https?://\S+", line)
        if not um:
            continue
        url = um.group(0)
        rm = re.search(r"\b(2160|1080|720|480|360)p?\b", line, re.I)
        sm = re.search(r"(\d+(?:\.\d+)?)\s?(GB|MB)", line, re.I)
        res = int(rm.group(1)) if rm else 720
        res_s = f"{res}p"
        size = f"{sm.group(1)} {sm.group(2).upper()}" if sm else ""
        pdv = pd_convert(url)
        is_pd = "pixeldrain.com/api/file/" in pdv
        downloads.append({
            "quality": quality, "res": res_s, "size": size, "url": url,
            "pd480": pdv if is_pd and res == 480 else "",
            "pd720": pdv if is_pd and res == 720 else "",
            "pd1080": pdv if is_pd and res == 1080 else "",
            "tgLink": "", "srv1": "", "srv2": "", "srv3": "",
        })
        if is_pd:
            players.append({"name": "MovieManiaLK", "quality": res_s, "url": pdv, "type": "direct"})
    return downloads, players


def detect_player_type(name: str, url: str) -> str:
    if name == "Facebook":
        return "facebook"
    if name == "VLC":
        return "vlc"
    return "hls" if ".m3u8" in url else "direct"


def parse_players(text: str):
    """Each line: [Facebook|VLC|MovieManiaLK] [720p] <video url or Facebook video ID>."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        name = "Facebook" if "facebook" in low else "VLC" if "vlc" in low else "MovieManiaLK"
        um = re.search(r"https?://\S+", line)
        rest = line
        if um:
            url = um.group(0)
            rest = line.replace(url, " ")
        else:
            fm = re.search(r"\b\d{8,}\b", line)
            if not (name == "Facebook" and fm):
                continue
            url = f"https://fb-con.vercel.app/video?video_id={fm.group(0)}"
            rest = line.replace(fm.group(0), " ")
        rm = re.search(r"\b(2160|1080|720|480|360)p?\b", rest)
        quality = f"{rm.group(1)}p" if rm else "720p"
        if name != "Facebook":
            url = pd_convert(url)
        out.append({"name": name, "quality": quality, "url": url,
                    "type": detect_player_type(name, url)})
    return out


def draft_summary(dr: dict, meta: dict) -> str:
    e = html.escape
    links = ", ".join(f"{x['res']}{(' ' + x['size']) if x['size'] else ''}" for x in dr["downloads"]) or "à¶±à·‘"
    lines = [
        "âž• <b>Add to Site</b>", SEP,
        f"ðŸŽ¬ <b>{e(dr['title'])}</b> ({e(dr['year'])})",
        f"ðŸ’¿ Quality: <b>{e(dr['quality'])}</b>   â­ VIP: <b>{'ON' if dr['isVip'] else 'OFF'}</b>",
        f"ðŸ“¥ Links: <b>{e(links)}</b>",
        f"â–¶ï¸ Players: <b>{len(dr['players']) or 'â€”'}</b>   ðŸ’¬ Subtitle file: <b>{'âœ…' if dr['dlSubUrl'] else 'â€”'}</b>",
        f"ðŸ· Subtitle by: <b>{e(dr['subBy'])}</b>",
        f"ðŸ“ Description: <b>{len(dr['description'])} chars</b>" + (" âœï¸" if meta.get("custom_desc") else ""),
    ]
    if meta.get("dup"):
        lines.append(f"âš ï¸ Site à¶‘à¶šà·š à¶¯à·à¶±à¶§à¶¸à¶­à·Š à¶­à·’à¶ºà·™à¶±à·€à·: <code>{e(meta['dup'])}</code>")
    return "\n".join(lines)


def draft_keyboard(dr: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"ðŸ’¿ {dr['quality']}", callback_data="add:qual"),
            InlineKeyboardButton(f"â­ VIP: {'ON' if dr['isVip'] else 'OFF'}", callback_data="add:vip"),
        ],
        [
            InlineKeyboardButton("ðŸ”— Links", callback_data="add:links"),
            InlineKeyboardButton("â–¶ï¸ Player", callback_data="add:player"),
        ],
        [
            InlineKeyboardButton("ðŸ“ Description", callback_data="add:desc"),
            InlineKeyboardButton("ðŸ· Subtitle By", callback_data="add:subby"),
        ],
        [InlineKeyboardButton("ðŸ’¬ Subtitle file link", callback_data="add:sub")],
        [cbtn("âœ… Save & Post to Channel", "add:savepost", "success")],
        [
            InlineKeyboardButton("ðŸ’¾ Save only", callback_data="add:saveonly"),
            cbtn("âŒ Cancel", "add:cancel", "danger"),
        ],
    ])


LINKS_PROMPT = (
    "ðŸ”— <b>Download links à¶‘à·€à¶±à·Šà¶±</b> (à¶´à·šà·…à·’à¶ºà¶šà¶§ à¶‘à¶š link à¶‘à¶šà¶šà·Š)\n\n"
    "<code>720p 1.2GB https://pixeldrain.com/u/abc123\n"
    "1080p 2.4GB https://pixeldrain.com/u/xyz789</code>\n\n"
    "Resolution (480p/720p/1080p) à·ƒà·„ size optional. Pixeldrain link à¶±à¶¸à·Š Watch Online à¶‘à¶šà¶§à¶­à·Š auto set à·€à·™à¶±à·€à·."
)


async def handle_add_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    ud = context.user_data
    dr = ud.get("draft")
    if not dr:
        ud.clear()
        await update.message.reply_text("âš ï¸ Session expire. à¶†à¶ºà·™ à¶±à¶¸à¶šà·Š à¶‘à·€à¶±à·Šà¶±.")
        return
    meta = ud.setdefault("draft_meta", {})
    skip = text.lower() in ("/skip", "skip", "-")
    st = ud["state"]
    if st == "add_links":
        downloads, players = parse_links(text, dr["quality"])
        if not downloads:
            await update.message.reply_text("âŒ http:// à·„à· https:// link à¶‘à¶šà¶šà·Š à·„à·œà¶ºà·à¶œà¶±à·Šà¶± à¶¶à·‘. à¶†à¶ºà·™ à¶‘à·€à¶±à·Šà¶±.")
            return
        dr["downloads"] = downloads
        if not meta.get("custom_players"):  # keep hand-made players
            dr["players"] = players
    elif st == "add_player":
        if not skip:
            players = parse_players(text)
            if not players:
                await update.message.reply_text("âŒ Video link à¶‘à¶šà¶šà·Š à·„à·œà¶ºà·à¶œà¶±à·Šà¶± à¶¶à·‘. à¶†à¶ºà·™ à¶‘à·€à¶±à·Šà¶± (à¶±à·à¶­à·Šà¶±à¶¸à·Š /skip).")
                return
            dr["players"] = players
            meta["custom_players"] = True
    elif st == "add_desc":
        if not skip:
            dr["description"] = text
            meta["custom_desc"] = True
    elif st == "add_subby":
        if not skip:
            dr["subBy"] = text[:60]
    else:  # add_sub
        if not skip:
            if not text.startswith("http"):
                await update.message.reply_text("âŒ Link à¶‘à¶š http:// à·€à¶½à·’à¶±à·Š à¶´à¶§à¶±à·Š à¶œà¶±à·Šà¶± à¶•à¶±à·š. à¶±à·à¶­à·Šà¶±à¶¸à·Š /skip")
                return
            dr["dlSubUrl"] = text
            if text.lower().split("?")[0].endswith((".srt", ".vtt")):
                dr["subUrl"] = dr["subtitleUrl"] = text
    ud["state"] = None
    await update.message.reply_text(
        draft_summary(dr, ud.get("draft_meta", {})), parse_mode="HTML",
        reply_markup=draft_keyboard(dr),
    )


async def handle_site_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    ud = context.user_data
    parts = q.data.split(":", 2)
    kind, action = parts[0], parts[1]

    # ---- delete / vip (from /del and /vip) ----
    if kind == "del":
        if action == "no":
            await q.edit_message_text("âŒ Cancel à¶šà·…à·.")
            return
        mid = parts[2]
        try:
            m = await fb_get(f"movies/{mid}")
            if not isinstance(m, dict):
                await q.edit_message_text("âŒ à¶’ movie à¶‘à¶š à¶±à·‘.")
                return
            v, dl, sub = num(m.get("views")), num(m.get("downloads_count")), num(m.get("subtitle_downloads_count"))
            if v or dl or sub:  # keep history, same as the admin panel
                cur = await fb_get("analytics/deletedStats") or {}
                await fb_put("analytics/deletedStats", {
                    "totalViews": num(cur.get("totalViews")) + v,
                    "totalDownloads": num(cur.get("totalDownloads")) + dl,
                    "totalSubDownloads": num(cur.get("totalSubDownloads")) + sub,
                    "deletedCount": num(cur.get("deletedCount")) + 1,
                })
            await fb_delete(f"movies/{mid}")
            await q.edit_message_text(f"ðŸ—‘ Deleted: {html.escape(str(m.get('title')))}", parse_mode="HTML")
        except Exception as ex:
            log.exception("delete failed")
            await q.edit_message_text(f"âŒ Failed: {ex}")
        return
    if kind == "vip":
        mid = action if len(parts) == 2 else f"{action}:{parts[2]}"
        try:
            m = await fb_get(f"movies/{mid}")
            if not isinstance(m, dict):
                await q.edit_message_text("âŒ à¶’ movie à¶‘à¶š à¶±à·‘.")
                return
            new = not bool(m.get("isVip"))
            await fb_put(f"movies/{mid}/isVip", new)
            await q.edit_message_text(
                f"â­ <b>{html.escape(str(m.get('title')))}</b>\nVIP: <b>{'ON' if new else 'OFF'}</b>",
                parse_mode="HTML",
            )
        except Exception as ex:
            await q.edit_message_text(f"âŒ Failed: {ex}")
        return

    # ---- add flow ----
    if action == "start":
        tmdb = ud.get("tmdb")
        if not tmdb:
            await q.message.reply_text("âš ï¸ Session expire. à¶†à¶ºà·™ à¶±à¶¸à¶šà·Š à¶‘à·€à¶±à·Šà¶±.")
            return
        d, media_type = tmdb
        if media_type == "tv":
            await q.message.reply_text(
                "ðŸ“º TV Series (seasons/episodes) bot à¶‘à¶šà·™à¶±à·Š add à¶šà¶»à¶±à·Šà¶± à¶­à·à¶¸ à¶¶à·‘.\n"
                "Admin panel à¶‘à¶šà·™à¶±à·Š add à¶šà¶»à¶±à·Šà¶±. (Channel post only à·€à·à¶© à¶šà¶»à¶±à·€à·.)"
            )
            return
        dr = draft_from_tmdb(d, media_type)
        meta = {}
        try:  # warn if this TMDB id is already on the site
            for k, v in (await fb_get("movies") or {}).items():
                if isinstance(v, dict) and str(v.get("tmdbId")) == dr["tmdbId"]:
                    meta["dup"] = k
                    break
        except Exception:
            pass
        ud["draft"], ud["draft_meta"], ud["state"] = dr, meta, "add_links"
        await q.message.reply_text(LINKS_PROMPT, parse_mode="HTML")
        return

    dr = ud.get("draft")
    if not dr:
        await q.edit_message_text("âš ï¸ Session expire. à¶†à¶ºà·™ à¶±à¶¸à¶šà·Š à¶‘à·€à¶±à·Šà¶±.")
        return
    meta = ud.get("draft_meta", {})

    if action == "cancel":
        ud.clear()
        await q.edit_message_text("âŒ Cancel à¶šà·…à·.")
    elif action in ("qual", "vip"):
        if action == "qual":
            i = QUALITIES.index(dr["quality"]) if dr["quality"] in QUALITIES else -1
            dr["quality"] = QUALITIES[(i + 1) % len(QUALITIES)]
            for x in dr["downloads"]:
                x["quality"] = dr["quality"]
        else:
            dr["isVip"] = not dr["isVip"]
        await q.edit_message_text(draft_summary(dr, meta), parse_mode="HTML", reply_markup=draft_keyboard(dr))
    elif action == "links":
        ud["state"] = "add_links"
        await q.message.reply_text(LINKS_PROMPT, parse_mode="HTML")
    elif action == "player":
        ud["state"] = "add_player"
        cur = "\n".join(f"{p['name']} {p['quality']} {p['url']}" for p in dr["players"]) or "â€”"
        await q.message.reply_text(
            "â–¶ï¸ <b>Player link(s) à¶‘à·€à¶±à·Šà¶±</b> (à¶´à·šà·…à·’à¶ºà¶šà¶§ à¶‘à¶šà¶šà·Š)\n\n"
            "<code>720p https://example.com/video.mp4\n"
            "VLC 1080p https://example.com/stream.m3u8\n"
            "Facebook 720p 1234567890123</code>\n\n"
            "à¶±à¶¸ à¶±à·œà¶¯à·”à¶±à·Šà¶±à·œà¶­à·Š <b>MovieManiaLK</b>. Facebook à¶±à¶¸à·Š video ID à¶‘à¶šà¶­à·Š à¶‡à¶­à·’.\n"
            f"à¶¯à·à¶±à·Š: <code>{html.escape(cur)[:400]}</code>\n\nà·€à·™à¶±à·ƒà·Š à¶±à·œà¶šà¶»à¶±à·Šà¶± /skip",
            parse_mode="HTML",
        )
    elif action == "desc":
        ud["state"] = "add_desc"
        await q.message.reply_text(
            "ðŸ“ <b>Description à¶‘à¶š à¶‘à·€à¶±à·Šà¶±</b> (à·ƒà·’à¶‚à·„à¶½à·™à¶±à·Š à·€à·”à¶«à¶­à·Š à¶‰à¶­à·’à¶‚).\n"
            f"à¶¯à·à¶±à·Š: <i>{html.escape(dr['description'])[:300]}</i>\n\nà·€à·™à¶±à·ƒà·Š à¶±à·œà¶šà¶»à¶±à·Šà¶± /skip",
            parse_mode="HTML",
        )
    elif action == "subby":
        ud["state"] = "add_subby"
        await q.message.reply_text(
            f"ðŸ· <b>Subtitle By</b> à¶±à¶¸ à¶‘à·€à¶±à·Šà¶±.\nà¶¯à·à¶±à·Š: <b>{html.escape(dr['subBy'])}</b>\n\nà·€à·™à¶±à·ƒà·Š à¶±à·œà¶šà¶»à¶±à·Šà¶± /skip",
            parse_mode="HTML",
        )
    elif action == "sub":
        ud["state"] = "add_sub"
        await q.message.reply_text("ðŸ’¬ Subtitle download link à¶‘à¶š (.zip / .srt) à¶‘à·€à¶±à·Šà¶±. à¶±à·à¶­à·Šà¶±à¶¸à·Š /skip")
    elif action in ("savepost", "saveonly"):
        if not dr["downloads"]:
            await q.answer("Download link à¶‘à¶šà¶šà·Š à¶¸à·”à¶½à·’à¶±à·Š à¶¯à·à¶±à·Šà¶±!", show_alert=True)
            return
        try:
            movie = dict(dr)
            movie["addedAt"] = int(time.time() * 1000)
            cid = await unique_movie_id(movie["title"])
            POSTED.add(cid)  # so the auto-post loop doesn't post it a second time
            await fb_put(f"movies/{cid}", movie)
        except Exception as ex:
            log.exception("site save failed")
            await q.edit_message_text(f"âŒ Save failed: {ex}")
            return
        ud.clear()
        result = (
            f"âœ… <b>Site à¶‘à¶šà¶§ add à¶šà·…à·!</b>\nðŸŽ¬ {html.escape(movie['title'])}\n"
            f"ðŸ†” <code>{html.escape(cid)}</code>"
        )
        try:
            await fb_put(f"{POSTED_PATH}/{cid}", True)
        except Exception:
            pass
        if action == "savepost":
            try:
                await post_site_movie(context.bot, cid, movie)
                result += "\nðŸ“¢ Channel à¶‘à¶šà¶§ post à¶šà·…à·"
                await fb_put(
                    f"telegram_bot/history/{cid}",
                    {"title": movie["title"], "ts": int(time.time() * 1000)},
                )
            except Exception as ex:
                log.exception("post after save failed")
                result += f"\nâš ï¸ Post failed: {ex}\n(/repost {cid})"
        else:
            result += "\nðŸ’¾ Channel à¶‘à¶šà¶§ post à¶šà·…à·š à¶±à·‘ (/repost " + cid + ")"
        await q.edit_message_text(
            result, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[btn("ðŸŒ Open on site", movie_link(cid, movie), "primary")]]),
        )


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    context.user_data.clear()
    await update.message.reply_text(
        "âž• <b>Add Movie</b>\n\nðŸŽ¬ Movie à¶‘à¶šà·š à¶±à¶¸ type à¶šà¶»à¶±à·Šà¶± (TMDB à¶‘à¶šà·™à¶±à·Š à·„à·œà¶ºà¶±à·€à·)\n\n/cancel â€“ à¶±à·€à¶­à·Šà·€à¶±à·Šà¶±",
        parse_mode="HTML",
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    context.user_data.clear()
    await update.message.reply_text("âŒ Cancel à¶šà·…à·.")


def cbtn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    if not style:
        return InlineKeyboardButton(text, callback_data=data)
    try:
        return InlineKeyboardButton(text, callback_data=data, style=style)
    except TypeError:
        return InlineKeyboardButton(text, callback_data=data, api_kwargs={"style": style})


async def find_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    term = " ".join(context.args).strip().lower()
    if not term:
        await update.message.reply_text("Usage: /find movie-name")
        return
    try:
        movies = await fb_get("movies") or {}
    except Exception:
        await update.message.reply_text("âš ï¸ Firebase error.")
        return
    hits = [(k, v) for k, v in movies.items()
            if isinstance(v, dict) and term in str(v.get("title", "")).lower()][:8]
    if not hits:
        await update.message.reply_text("ðŸ˜• à¶šà·’à·ƒà·’à·€à¶šà·Š à·„à¶¸à·Šà¶¶à·”à¶±à·š à¶±à·‘.")
        return
    lines = ["ðŸ”Ž <b>Results</b>\n"]
    for k, v in hits:
        vip = " â­VIP" if v.get("isVip") else ""
        lines.append(
            f"ðŸŽ¬ <b>{html.escape(str(v.get('title')))}</b> ({html.escape(str(v.get('year', '')))}){vip}\n"
            f"   <code>{html.escape(k)}</code>  ðŸ‘ {fmt(num(v.get('views')))}  ðŸ“¥ {fmt(num(v.get('downloads_count')))}"
        )
    lines.append("\n/vip id  â€¢  /del id  â€¢  /repost id")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /del movie-id  (id à¶‘à¶š /find à¶‘à¶šà·™à¶±à·Š à¶œà¶±à·Šà¶±)")
        return
    mid = context.args[0]
    m = await fb_get(f"movies/{mid}")
    if not isinstance(m, dict):
        await update.message.reply_text("âŒ à¶’ ID à¶‘à¶šà·™à¶±à·Š movie à¶‘à¶šà¶šà·Š à¶±à·‘.")
        return
    await update.message.reply_text(
        f"ðŸ—‘ <b>{html.escape(str(m.get('title')))}</b> delete à¶šà¶»à¶±à·Šà¶±à¶¯?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("ðŸ—‘ Yes, delete", callback_data=f"del:yes:{mid}"),
            InlineKeyboardButton("âŒ No", callback_data="del:no"),
        ]]),
    )


async def vip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /vip movie-id")
        return
    mid = context.args[0]
    m = await fb_get(f"movies/{mid}")
    if not isinstance(m, dict):
        await update.message.reply_text("âŒ à¶’ ID à¶‘à¶šà·™à¶±à·Š movie à¶‘à¶šà¶šà·Š à¶±à·‘.")
        return
    new = not bool(m.get("isVip"))
    await fb_put(f"movies/{mid}/isVip", new)
    await update.message.reply_text(
        f"â­ <b>{html.escape(str(m.get('title')))}</b>\nVIP: <b>{'ON' if new else 'OFF'}</b>", parse_mode="HTML"
    )


# ---------- AUTO POST (admin panel -> channel) ----------
async def fb_get(path: str, **params):
    if FIREBASE_API_KEY:
        params["key"] = FIREBASE_API_KEY
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{FIREBASE_DB_URL}/{path}.json", params=params)
        r.raise_for_status()
        return r.json()


async def fb_delete(path: str):
    params = {"key": FIREBASE_API_KEY} if FIREBASE_API_KEY else {}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.delete(f"{FIREBASE_DB_URL}/{path}.json", params=params)
        r.raise_for_status()


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
    kind = "ðŸ“º" if m.get("type") in ("tv", "series") else "ðŸŽ¬"
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
    poster = poster.replace("/t/p/original/", "/t/p/w780/")  # Telegram photo size limit
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
                await bot.send_message(admin, f"âœ… Auto posted: {m.get('title')}")
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
            POSTED.update(keys)
            posted = POSTED
            try:
                await fb_put(POSTED_PATH, {k: True for k in posted} or {"_init": True})
            except Exception:
                log.warning("Firebase write not allowed - posted list kept in memory only")
        else:
            POSTED.update(saved)
            posted = POSTED
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


BOT_VERSION = "2026-10-17 Â· site-admin v4"


async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        f"ðŸ¤– Bot version: {BOT_VERSION}\n"
        "âœ… Add to Site â€¢ Description â€¢ Subtitle By â€¢ Player â€¢ Links"
    )


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("handler error", exc_info=context.error)
    if update is None:  # network / polling errors - don't spam admins
        return
    err = f"{type(context.error).__name__}: {context.error}"[:300]
    for admin in ADMIN_IDS:
        try:
            await context.bot.send_message(admin, f"âš ï¸ Bot error:\n{err}")
        except Exception:
            pass


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("autopost", autopost_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("last", last_cmd))
    app.add_handler(CommandHandler("repost", repost_cmd))
    app.add_handler(CommandHandler("requests", requests_cmd))
    app.add_handler(CommandHandler("find", find_cmd))
    app.add_handler(CommandHandler("version", version_cmd))
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("del", del_cmd))
    app.add_handler(CommandHandler("vip", vip_cmd))
    app.add_handler(CommandHandler("skip", on_text))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
