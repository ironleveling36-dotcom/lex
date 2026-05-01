import os
import logging
import asyncio
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, JobQueue
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = "https://api.goscorer.com/api/v3/getSV3?key={}"
HEADERS = {
    "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCIsImV4cGlyZXNJbiI6IjM2NWQifQ.eyJ0aW1lIjoxNjYwMDQ2NjIwMDAwfQ.bTEmMWlR7hLRUHxPPq6-1TP7cuuW7m6sZ9jcdbYzLRA",
    "origin": "https://crex.com",
    "referer": "https://crex.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

MATCH_KEYS = {
    "118N": "🏏 Live Match"
}

STATUS_MAP = {
    0: "⏳ Upcoming",
    1: "🟡 Starting Soon",
    2: "🔴 LIVE",
    3: "☕ Innings Break",
    4: "✅ Completed",
    5: "🏁 Result"
}

# Animation frames
FOUR_ANIMATION = [
    "🏏💨 . . . . . . . 🚧",
    "🏏 💨💨 . . . . . 🚧",
    "🏏 . 💨💨💨 . . . 🚧",
    "🏏 . . . 💨💨💨💨🚧",
    "🎯 𝗙𝗢𝗨𝗥! 🎯\n\n4️⃣ 𝗕𝗢𝗨𝗡𝗗𝗔𝗥𝗬! 4️⃣"
]

SIX_ANIMATION = [
    "🏏💥 . . . . . . . . ⛅",
    "🏏 💥💥 . . . . . . ⛅",
    "🏏 . 💥💥💥 . . . ☁️",
    "🏏 . . . 💥💥💥💥☁️🌤",
    "🏏 . . . . 🚀🚀🚀🌤☀️",
    "🚀 𝗦𝗜𝗫𝗘𝗥! 🚀\n\n6️⃣ 𝗠𝗔𝗫𝗜𝗠𝗨𝗠! 6️⃣\n\n🎆🎇🎆🎇🎆"
]

WICKET_ANIMATION = [
    "🎯 . . . . . 🏏",
    "🎯 . . . 🏏💢",
    "🎯 . 🏏💢💢💢",
    "💔 𝗢𝗨𝗧! 💔\n\n🎯 𝗪𝗜𝗖𝗞𝗘𝗧! 🎯"
]

# Track per-chat subscriptions & state
SUBSCRIPTIONS = {}  # {chat_id: {key: {"msg_id": int, "last_ball": str, "six_count": int, "last_six_milestone": 0}}}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# ---------- API ----------
def fetch_match(key):
    try:
        r = requests.get(BASE_URL.format(key), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
        log.warning(f"API {r.status_code} for key={key}")
        return None
    except Exception as e:
        log.error(f"Fetch Error: {e}")
        return None

# ---------- FORMATTER ----------
def parse_balls(over_str):
    if not over_str or ":" not in over_str:
        return ""
    ov, balls = over_str.split(":", 1)
    return f"Ov {ov}: " + " • ".join(balls.split("."))

def format_score(d, key):
    if not d:
        return f"⚠️ *No data for key `{key}`*\n\nMatch may be over or key expired."

    batting = d.get("a", "").split(".")[0] or "—"
    bowling = d.get("F", "").replace("^", "") or "—"
    score = d.get("ats", "—")
    overs = d.get("q", "0").replace("*", "")
    crr = d.get("s", "—")
    match_no = d.get("mn", "?")
    status = STATUS_MAP.get(d.get("ms", 0), "Unknown")
    fmt = "T20" if d.get("f") == 1 else "ODI/Test"

    inn1 = d.get("j", "")
    inn2 = d.get("k", "")

    last_ball = d.get("d", "").split("|")[-1] if d.get("d") else ""
    this_over = " • ".join(last_ball.split(".")) if last_ball else "—"

    mt = d.get("mt", 0)
    match_time = datetime.fromtimestamp(mt/1000).strftime("%d %b, %H:%M") if mt else ""

    text = (
        f"{status}  *Match #{match_no}* · {fmt}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏏 *{batting}*  —  `{score}`  ({overs} ov)\n"
        f"🎯 *vs {bowling}*\n\n"
        f"📊 *CRR:* `{crr}`\n"
    )

    if inn1:
        text += f"\n1️⃣ *1st Inns:* `{inn1}`"
    if inn2 and inn2 != inn1:
        text += f"\n2️⃣ *2nd Inns:* `{inn2}`"

    if this_over and this_over != "—":
        text += f"\n\n⚡ *This Over:* `{this_over}`"

    last_overs = []
    for k in ["l", "m", "n"]:
        ov = parse_balls(d.get(k, ""))
        if ov:
            last_overs.append(ov)
    if last_overs:
        text += "\n\n📜 *Recent Overs:*\n" + "\n".join(f"  `{o}`" for o in last_overs)

    pr = d.get("pr", {})
    if pr.get("ps"):
        text += "\n\n📈 *Projected Scores:*\n"
        for p in pr["ps"]:
            sc = p.get("sc", {})
            text += f"  • *{p.get('ov')}:* {sc.get('ps1','-')} / {sc.get('ps2','-')} / {sc.get('ps3','-')} / {sc.get('ps4','-')}\n"

    if match_time:
        text += f"\n\n🕐 _Started: {match_time}_"

    text += f"\n\n🔄 _Auto-refresh: 1.5s_  |  🔑 `{key}`"
    return text

# ---------- ANIMATIONS ----------
async def play_animation(bot, chat_id, frames, delay=0.4):
    """Play an animation as a temporary message."""
    try:
        msg = await bot.send_message(chat_id, frames[0])
        for frame in frames[1:]:
            await asyncio.sleep(delay)
            try:
                await bot.edit_message_text(frame, chat_id=chat_id, message_id=msg.message_id,
                                            parse_mode="Markdown")
            except Exception:
                pass
    except Exception as e:
        log.error(f"Animation error: {e}")

def detect_events(prev_ball, current_ball):
    """Detect new 4/6/W from current over string."""
    if not current_ball:
        return []
    prev_balls = prev_ball.split(".") if prev_ball else []
    curr_balls = current_ball.split(".")
    # New balls = those after prev count
    new_balls = curr_balls[len(prev_balls):] if len(curr_balls) > len(prev_balls) else []
    return new_balls

# ---------- AUTO REFRESH JOB ----------
async def auto_refresh(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 1.5s — refreshes all subscribed messages & detects events."""
    job = context.job
    chat_id = job.chat_id
    key = job.data["key"]

    sub = SUBSCRIPTIONS.get(chat_id, {}).get(key)
    if not sub:
        return

    data = fetch_match(key)
    if not data:
        return

    # Detect new boundaries
    current_ball = data.get("d", "").split("|")[-1] if data.get("d") else ""
    prev_ball = sub.get("last_ball", "")
    new_balls = detect_events(prev_ball, current_ball)

    for b in new_balls:
        b = b.strip()
        if b == "6":
            sub["six_count"] = sub.get("six_count", 0) + 1
            asyncio.create_task(play_animation(context.bot, chat_id, SIX_ANIMATION, 0.35))
            # Notify every 6 sixes
            milestone = sub["six_count"] // 6
            if milestone > sub.get("last_six_milestone", 0):
                sub["last_six_milestone"] = milestone
                await context.bot.send_message(
                    chat_id,
                    f"🎉 *MILESTONE!* 🎉\n\n"
                    f"💥 *{sub['six_count']} SIXES* hit in this match!\n"
                    f"🚀 That's {milestone * 36} runs from sixes alone!",
                    parse_mode="Markdown"
                )
        elif b == "4":
            asyncio.create_task(play_animation(context.bot, chat_id, FOUR_ANIMATION, 0.35))
        elif b.upper() in ("W", "WK"):
            asyncio.create_task(play_animation(context.bot, chat_id, WICKET_ANIMATION, 0.4))

    sub["last_ball"] = current_ball

    # Edit live scoreboard
    text = format_score(data, key)
    kb = [
        [
            InlineKeyboardButton("⏸ Stop Auto", callback_data=f"stop:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    try:
        await context.bot.edit_message_text(
            text, chat_id=chat_id, message_id=sub["msg_id"],
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            log.warning(f"Edit fail: {e}")

    # Stop if match is over
    if data.get("ms") in (4, 5):
        await stop_subscription(context, chat_id, key)
        await context.bot.send_message(chat_id, "🏁 *Match ended. Auto-refresh stopped.*",
                                        parse_mode="Markdown")

async def stop_subscription(context, chat_id, key):
    """Cancel auto-refresh job."""
    jobs = context.job_queue.get_jobs_by_name(f"{chat_id}:{key}")
    for j in jobs:
        j.schedule_removal()
    if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
        del SUBSCRIPTIONS[chat_id][key]

# ---------- HANDLERS ----------
def main_menu():
    kb = [[InlineKeyboardButton(name, callback_data=f"k:{k}")] for k, name in MATCH_KEYS.items()]
    kb.append([
        InlineKeyboardButton("➕ Add Match", callback_data="help"),
        InlineKeyboardButton("ℹ️ About", callback_data="about")
    ])
    kb.append([InlineKeyboardButton("📋 My Live", callback_data="mylive")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏏 *Live Cricket Score Bot*\n\n"
        "⚡ Real-time ball-by-ball updates\n"
        "🎯 Auto-refresh every 1.5s\n"
        "💥 Animated 4/6/Wicket alerts\n"
        "🎉 Milestone notifications\n\n"
        "👇 Pick a match to get started!",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def show_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("⚡ Loading live...")
    key = q.data.split(":", 1)[1]
    data = fetch_match(key)
    text = format_score(data, key)

    kb = [
        [
            InlineKeyboardButton("▶️ Start Auto", callback_data=f"start:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    try:
        await q.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        if "not modified" not in str(e).lower():
            log.error(e)

async def start_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start auto-refresh subscription."""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    msg_id = q.message.message_id

    SUBSCRIPTIONS.setdefault(chat_id, {})[key] = {
        "msg_id": msg_id,
        "last_ball": "",
        "six_count": 0,
        "last_six_milestone": 0
    }

    # Remove any existing job for this key/chat
    for j in ctx.job_queue.get_jobs_by_name(f"{chat_id}:{key}"):
        j.schedule_removal()

    ctx.job_queue.run_repeating(
        auto_refresh,
        interval=1.5,
        first=1.0,
        chat_id=chat_id,
        name=f"{chat_id}:{key}",
        data={"key": key}
    )
    await q.answer("✅ Auto-refresh started! (every 1.5s)", show_alert=False)

async def stop_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    await stop_subscription(ctx, chat_id, key)
    await q.answer("⏸ Auto-refresh stopped", show_alert=False)

    # Restore start button
    kb = [
        [
            InlineKeyboardButton("▶️ Start Auto", callback_data=f"start:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    try:
        await q.edit_message_reply_markup(InlineKeyboardMarkup(kb))
    except Exception:
        pass

async def back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🏏 *Live Cricket Score Bot*\n\nSelect a match:",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def help_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "➕ *Add a Match*\n\n"
        "1. Open [crex.com](https://crex.com) → live match\n"
        "2. F12 → Network tab → filter `getSV3`\n"
        "3. Copy the `key` from URL\n\n"
        "Then send: `/add <key> <name>`\n\n"
        "Example: `/add 118N IND vs AUS`",
        parse_mode="Markdown", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🤖 *Live Cricket Bot v2.0*\n\n"
        "• ⚡ Auto-refresh every 1.5s\n"
        "• 🎯 4/6/Wicket animations\n"
        "• 🎉 Six milestones (every 6 sixes)\n"
        "• 📊 Projected scores\n"
        "• 🚂 Hosted on Railway\n\n"
        "_Data via CREX API_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def mylive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    subs = SUBSCRIPTIONS.get(chat_id, {})
    if not subs:
        text = "📋 *No active live trackers.*\n\nStart one from the menu!"
    else:
        text = "📋 *Your Live Trackers:*\n\n"
        for key in subs:
            text += f"• `{key}` — {MATCH_KEYS.get(key, 'Unknown')}\n"
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]]))

# ---------- COMMANDS ----------
async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "Usage: `/add <key> <name>`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    name = " ".join(ctx.args[1:])
    MATCH_KEYS[key] = name
    await update.message.reply_text(f"✅ Added: *{name}* (`{key}`)", parse_mode="Markdown")

async def remove_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/remove <key>`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    if key in MATCH_KEYS:
        del MATCH_KEYS[key]
        await update.message.reply_text(f"🗑 Removed `{key}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Key not found.")

async def score_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/score <key>`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    data = fetch_match(key)
    kb = [[
        InlineKeyboardButton("▶️ Start Auto", callback_data=f"start:{key}"),
        InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
    ]]
    await update.message.reply_text(format_score(data, key), parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(kb))

async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not MATCH_KEYS:
        await update.message.reply_text("No matches added.")
        return
    text = "📋 *Saved Matches:*\n\n" + "\n".join(f"• `{k}` — {v}" for k, v in MATCH_KEYS.items())
    await update.message.reply_text(text, parse_mode="Markdown")

async def stop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Stop all auto-refreshes for the user."""
    chat_id = update.message.chat_id
    subs = list(SUBSCRIPTIONS.get(chat_id, {}).keys())
    for key in subs:
        await stop_subscription(ctx, chat_id, key)
    await update.message.reply_text(f"⏸ Stopped {len(subs)} active tracker(s).")

# ---------- MAIN ----------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN environment variable!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    app.add_handler(CallbackQueryHandler(show_match, pattern="^k:"))
    app.add_handler(CallbackQueryHandler(start_auto, pattern="^start:"))
    app.add_handler(CallbackQueryHandler(stop_auto, pattern="^stop:"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(help_btn, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(about, pattern="^about$"))
    app.add_handler(CallbackQueryHandler(mylive, pattern="^mylive$"))

    log.info("✅ Bot running with auto-refresh & animations")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()