import os
import logging
import asyncio
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
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

SUBSCRIPTIONS = {}

FOUR_ANIMATION = [
    "🏏💨 . . . . . . . 🚧",
    "🏏 💨💨 . . . . . 🚧",
    "🏏 . 💨💨💨 . . . 🚧",
    "🏏 . . . 💨💨💨💨 🚧",
    "🎯 *FOUR!* 🎯\n\n4️⃣ *BOUNDARY!* 4️⃣"
]

SIX_ANIMATION = [
    "🏏💥 . . . . . . . . ⛅",
    "🏏 💥💥 . . . . . . ⛅",
    "🏏 . 💥💥💥 . . . ☁️",
    "🏏 . . . 💥💥💥💥 ☁️",
    "🚀 *SIXER!* 🚀\n\n6️⃣ *MAXIMUM!* 6️⃣\n\n🎆 🎇 🎆"
]

WICKET_ANIMATION = [
    "🎯 . . . . . 🏏",
    "🎯 . . . 🏏💢",
    "🎯 . 🏏💢💢💢",
    "💔 *OUT!* 💔\n\n🎯 *WICKET!* 🎯"
]

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
        log.error(f"Fetch error: {e}")
        return None

# ---------- BALL DETECTION ----------
def extract_latest_balls(over_string):
    """Extract balls from over string like '4:0.5.1.1.0.6'"""
    if not over_string or ":" not in over_string:
        return []
    try:
        _, balls_str = over_string.split(":", 1)
        return balls_str.split(".")
    except:
        return []

def detect_new_events(prev_balls_list, curr_balls_list):
    """Compare ball lists to find NEW events."""
    if not curr_balls_list:
        return []
    
    # Find balls that weren't in previous list
    new_count = len(curr_balls_list) - len(prev_balls_list)
    if new_count <= 0:
        return []
    
    new_balls = curr_balls_list[-new_count:]
    events = []
    
    for ball in new_balls:
        ball = ball.strip()
        if ball == "4":
            events.append("4")
        elif ball == "6":
            events.append("6")
        elif ball.lower() in ("w", "wk", "wd"):
            events.append("W")
    
    return events

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
        f"🏏 *{batting}*  →  `{score}`  ({overs} ov)\n"
        f"🎯 *vs {bowling}*\n\n"
        f"📊 *CRR:* `{crr}`\n"
    )

    if inn1:
        text += f"\n1️⃣ *1st Inns:* `{inn1}`"
    if inn2 and inn2 != inn1:
        text += f"\n2️⃣ *2nd Inns:* `{inn2}`"

    if this_over and this_over != "—":
        text += f"\n\n⚡ *Current Over:* `{this_over}`"

    last_overs = []
    for k in ["l", "m", "n"]:
        ov = parse_balls(d.get(k, ""))
        if ov:
            last_overs.append(ov)
    if last_overs:
        text += "\n\n📜 *Recent Overs:*\n" + "\n".join(f"`{o}`" for o in last_overs)

    if match_time:
        text += f"\n\n🕐 _{match_time}_"

    text += f"\n\n🔄 *Auto-refresh: ON*  |  🔑 `{key}`"
    return text

# ---------- ANIMATIONS ----------
async def play_animation(bot, chat_id, frames, delay=0.3):
    """Play animation without blocking."""
    try:
        msg = await bot.send_message(chat_id, frames[0], parse_mode="Markdown")
        for frame in frames[1:]:
            await asyncio.sleep(delay)
            try:
                await bot.edit_message_text(
                    frame, chat_id=chat_id, message_id=msg.message_id,
                    parse_mode="Markdown"
                )
            except:
                pass
        # Delete after animation
        await asyncio.sleep(2)
        await bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        log.error(f"Animation error: {e}")

# ---------- AUTO REFRESH JOB ----------
async def auto_refresh_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 1.5s — updates score & detects events."""
    job = context.job
    chat_id = job.chat_id
    key = job.data
    
    # Get subscription
    if chat_id not in SUBSCRIPTIONS or key not in SUBSCRIPTIONS[chat_id]:
        job.schedule_removal()
        return
    
    sub = SUBSCRIPTIONS[chat_id][key]
    msg_id = sub["msg_id"]
    
    # Fetch latest data
    data = fetch_match(key)
    if not data:
        return
    
    # Get current over
    current_over = data.get("d", "").split("|")[-1] if data.get("d") else ""
    prev_balls = sub.get("last_balls", [])
    curr_balls = extract_latest_balls(current_over)
    
    # Detect new 4/6/W
    events = detect_new_events(prev_balls, curr_balls)
    
    for event in events:
        if event == "4":
            log.info(f"🎯 FOUR detected in {key}")
            asyncio.create_task(play_animation(context.bot, chat_id, FOUR_ANIMATION))
        elif event == "6":
            log.info(f"🚀 SIX detected in {key}")
            sub["six_count"] = sub.get("six_count", 0) + 1
            asyncio.create_task(play_animation(context.bot, chat_id, SIX_ANIMATION))
            
            # Milestone alert every 6 sixes
            if sub["six_count"] % 6 == 0:
                await context.bot.send_message(
                    chat_id,
                    f"🎉 *MILESTONE!* 🎉\n\n"
                    f"💥 *{sub['six_count']} SIXES* in this match!\n"
                    f"🚀 That's *{sub['six_count'] * 6}* runs from sixes!",
                    parse_mode="Markdown"
                )
        elif event == "W":
            log.info(f"💔 WICKET detected in {key}")
            asyncio.create_task(play_animation(context.bot, chat_id, WICKET_ANIMATION))
    
    # Update subscription state
    sub["last_balls"] = curr_balls
    
    # Update scoreboard
    text = format_score(data, key)
    kb = [
        [
            InlineKeyboardButton("⏸ Stop Auto", callback_data=f"stop:{key}"),
            InlineKeyboardButton("🔄 Manual Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    
    try:
        await context.bot.edit_message_text(
            text, chat_id=chat_id, message_id=msg_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        error_str = str(e).lower()
        if "not modified" not in error_str and "message to edit not found" not in error_str:
            log.error(f"Edit error: {e}")
        if "message to edit not found" in error_str:
            job.schedule_removal()
    
    # Stop if match over
    if data.get("ms") in (4, 5):
        job.schedule_removal()
        if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
            del SUBSCRIPTIONS[chat_id][key]
        await context.bot.send_message(
            chat_id,
            f"🏁 *Match Ended*\n\n"
            f"Total Sixes: *{sub.get('six_count', 0)}*",
            parse_mode="Markdown"
        )

# ---------- HANDLERS ----------
def main_menu():
    kb = [[InlineKeyboardButton(name, callback_data=f"k:{k}")] for k, name in MATCH_KEYS.items()]
    kb.append([
        InlineKeyboardButton("➕ Add Match", callback_data="help"),
        InlineKeyboardButton("ℹ️ About", callback_data="about")
    ])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏏 *Live Cricket Score Bot*\n\n"
        "⚡ Real-time updates every 1.5s\n"
        "💥 Animated 4/6/Wicket alerts\n"
        "🎉 6-sixes milestone notifications\n\n"
        "👇 Pick a match to start!",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def show_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("⚡ Loading...")
    
    key = q.data.split(":", 1)[1]
    data = fetch_match(key)
    text = format_score(data, key)
    
    kb = [
        [
            InlineKeyboardButton("▶️ Start Auto (1.5s)", callback_data=f"start:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    
    try:
        await q.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        log.error(f"show_match error: {e}")

async def start_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start 1.5s auto-refresh."""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    
    await q.answer("✅ Auto-refresh started!")
    
    # Initialize subscription
    if chat_id not in SUBSCRIPTIONS:
        SUBSCRIPTIONS[chat_id] = {}
    
    SUBSCRIPTIONS[chat_id][key] = {
        "msg_id": q.message.message_id,
        "last_balls": [],
        "six_count": 0
    }
    
    # Create job
    job_name = f"{chat_id}:{key}"
    ctx.job_queue.run_repeating(
        auto_refresh_job,
        interval=1.5,
        first=0.1,
        name=job_name,
        chat_id=chat_id,
        data=key
    )
    
    log.info(f"✅ Auto-refresh started for {key} in {chat_id}")

async def stop_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Stop auto-refresh."""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    
    # Remove job
    jobs = ctx.job_queue.get_jobs_by_name(f"{chat_id}:{key}")
    for j in jobs:
        j.schedule_removal()
    
    # Remove subscription
    if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
        del SUBSCRIPTIONS[chat_id][key]
    
    await q.answer("⏸ Stopped")
    await q.edit_message_reply_markup(reply_markup=main_menu())
    
    log.info(f"⏸ Auto-refresh stopped for {key} in {chat_id}")

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
        "1. Open [crex.com](https://crex.com)\n"
        "2. Press F12 → Network tab\n"
        "3. Filter: `getSV3`\n"
        "4. Copy `key` from URL\n\n"
        "`/add <key> <name>`",
        parse_mode="Markdown", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🤖 *Cricket Live Bot*\n\n"
        "✨ Features:\n"
        "• ⚡ 1.5s refresh rate\n"
        "• 💥 4/6 animations\n"
        "• 🎉 Six milestones\n"
        "• 📊 CRR tracking\n"
        "• 🚀 Hosted on Railway",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: `/add <key> <name>`", parse_mode="Markdown")
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
        await update.message.reply_text("❌ Key not found")

async def score_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/score <key>`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    data = fetch_match(key)
    kb = [[InlineKeyboardButton("▶️ Start Auto", callback_data=f"start:{key}")]]
    await update.message.reply_text(format_score(data, key), parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(kb))

async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not MATCH_KEYS:
        await update.message.reply_text("No matches. Use `/add`")
        return
    text = "📋 *Matches:*\n\n" + "\n".join(f"• `{k}` — {v}" for k, v in MATCH_KEYS.items())
    await update.message.reply_text(text, parse_mode="Markdown")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set!")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    
    # Buttons
    app.add_handler(CallbackQueryHandler(show_match, pattern="^k:"))
    app.add_handler(CallbackQueryHandler(start_auto, pattern="^start:"))
    app.add_handler(CallbackQueryHandler(stop_auto, pattern="^stop:"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(help_btn, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(about, pattern="^about$"))
    
    log.info("✅ Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
