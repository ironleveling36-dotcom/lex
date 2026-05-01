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

# Active subscriptions: {chat_id: {key: {"msg_id": int, "last_balls": list, "six_count": int}}}
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

# ========== API ==========
def fetch_match(key):
    """Fetch match data from CREX API"""
    try:
        r = requests.get(BASE_URL.format(key), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
        log.warning(f"API {r.status_code} for key={key}")
        return None
    except Exception as e:
        log.error(f"Fetch error: {e}")
        return None

# ========== BALL DETECTION ==========
def extract_balls_from_over(over_string):
    """
    Extract balls from over string
    Example: '4:0.5.1.1.0.6' → ['0', '5', '1', '1', '0', '6']
    """
    if not over_string or ":" not in over_string:
        return []
    try:
        _, balls_str = over_string.split(":", 1)
        return balls_str.split(".")
    except:
        return []

def find_new_events(prev_balls, curr_balls):
    """
    Compare two ball lists and find NEW 4/6/W events
    Returns: [('4', '🎯 FOUR!'), ('6', '🚀 SIXER!'), ('W', '💔 WICKET!')]
    """
    if not curr_balls:
        return []
    
    # How many new balls appeared?
    new_count = len(curr_balls) - len(prev_balls)
    if new_count <= 0:
        return []
    
    # Get only the new balls
    new_balls = curr_balls[-new_count:]
    events = []
    
    for ball in new_balls:
        ball = ball.strip()
        if ball == "4":
            events.append(("4", "🎯 FOUR!"))
        elif ball == "6":
            events.append(("6", "🚀 SIXER!"))
        elif ball.lower() in ("w", "wd", "wk"):
            events.append(("W", "💔 WICKET!"))
    
    return events

# ========== FORMATTER ==========
def parse_balls(over_str):
    """Format over string for display"""
    if not over_str or ":" not in over_str:
        return ""
    ov, balls = over_str.split(":", 1)
    return f"Ov {ov}: " + " • ".join(balls.split("."))

def format_score(d, key):
    """Format complete match score message"""
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

# ========== ANIMATIONS ==========
async def play_animation(app, chat_id, frames, delay=0.3):
    """Play animation in background without blocking"""
    try:
        msg = await app.bot.send_message(chat_id, frames[0], parse_mode="Markdown")
        for frame in frames[1:]:
            await asyncio.sleep(delay)
            try:
                await app.bot.edit_message_text(
                    frame, chat_id=chat_id, message_id=msg.message_id,
                    parse_mode="Markdown"
                )
            except:
                pass
        # Auto-delete after animation
        await asyncio.sleep(2)
        try:
            await app.bot.delete_message(chat_id, msg.message_id)
        except:
            pass
    except Exception as e:
        log.error(f"Animation error: {e}")

# ========== AUTO REFRESH LOOP ==========
async def auto_refresh_loop(app):
    """
    Main loop that refreshes ALL subscriptions every 1.5s
    Runs in background continuously
    """
    await asyncio.sleep(2)  # Wait for bot to start
    
    while True:
        try:
            await asyncio.sleep(1.5)
            
            # Copy to avoid "dict changed during iteration"
            subs_copy = {}
            for chat_id, matches in SUBSCRIPTIONS.items():
                subs_copy[chat_id] = dict(matches)
            
            # Process each subscription
            for chat_id, matches in subs_copy.items():
                for key, sub in matches.items():
                    try:
                        await process_subscription(app, chat_id, key, sub)
                    except Exception as e:
                        log.error(f"Subscription error {chat_id}:{key}: {e}")
        
        except Exception as e:
            log.error(f"Auto-refresh loop error: {e}")

async def process_subscription(app, chat_id, key, sub):
    """Process a single subscription - update score & detect events"""
    msg_id = sub.get("msg_id")
    prev_balls = sub.get("last_balls", [])
    
    # Fetch fresh data
    data = fetch_match(key)
    if not data:
        return
    
    # Extract current over balls
    current_over = data.get("d", "").split("|")[-1] if data.get("d") else ""
    curr_balls = extract_balls_from_over(current_over)
    
    # Detect 4/6/W events
    events = find_new_events(prev_balls, curr_balls)
    
    for event_type, event_text in events:
        log.info(f"✅ Event detected: {event_text} in {key}")
        
        if event_type == "4":
            asyncio.create_task(play_animation(app, chat_id, FOUR_ANIMATION, 0.3))
            asyncio.create_task(app.bot.send_message(chat_id, "🎯 *FOUR!*", parse_mode="Markdown"))
        
        elif event_type == "6":
            sub["six_count"] = sub.get("six_count", 0) + 1
            six_total = sub["six_count"]
            
            asyncio.create_task(play_animation(app, chat_id, SIX_ANIMATION, 0.3))
            asyncio.create_task(app.bot.send_message(chat_id, f"🚀 *SIXER!*\n\n_Total: {six_total} sixes_", parse_mode="Markdown"))
            
            # Milestone at every 6 sixes
            if six_total % 6 == 0:
                asyncio.create_task(app.bot.send_message(
                    chat_id,
                    f"🎉 *MILESTONE!* 🎉\n\n"
                    f"💥 *{six_total} SIXES* hit!\n"
                    f"🚀 *{six_total * 6}* runs from sixes!",
                    parse_mode="Markdown"
                ))
        
        elif event_type == "W":
            asyncio.create_task(play_animation(app, chat_id, WICKET_ANIMATION, 0.4))
            asyncio.create_task(app.bot.send_message(chat_id, "💔 *WICKET!*", parse_mode="Markdown"))
    
    # Update state
    sub["last_balls"] = curr_balls
    
    # Update scoreboard message
    text = format_score(data, key)
    kb = [
        [
            InlineKeyboardButton("⏸ Stop Auto", callback_data=f"stop:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    
    try:
        await app.bot.edit_message_text(
            text, chat_id=chat_id, message_id=msg_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        error_str = str(e).lower()
        if "message to edit not found" in error_str:
            # Message deleted, remove subscription
            if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
                del SUBSCRIPTIONS[chat_id][key]
                log.info(f"Removed subscription: message deleted for {key} in {chat_id}")
    
    # Stop if match ended
    if data.get("ms") in (4, 5):
        if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
            six_total = SUBSCRIPTIONS[chat_id][key].get("six_count", 0)
            del SUBSCRIPTIONS[chat_id][key]
            await app.bot.send_message(
                chat_id,
                f"🏁 *Match Ended*\n\n"
                f"💥 Total Sixes: *{six_total}*",
                parse_mode="Markdown"
            )
            log.info(f"Match ended: {key} - Total sixes: {six_total}")

# ========== HANDLERS ==========
def main_menu():
    """Generate main menu keyboard"""
    kb = [[InlineKeyboardButton(name, callback_data=f"k:{k}")] for k, name in MATCH_KEYS.items()]
    kb.append([
        InlineKeyboardButton("➕ Add Match", callback_data="help"),
        InlineKeyboardButton("ℹ️ About", callback_data="about")
    ])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    await update.message.reply_text(
        "🏏 *Live Cricket Score Bot*\n\n"
        "⚡ Real-time updates every 1.5s\n"
        "💥 Animated 4/6/Wicket alerts\n"
        "🎉 Six-sixes milestone notifications\n\n"
        "👇 Pick a match to start!",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def show_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show match details"""
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
        log.error(f"show_match: {e}")

async def start_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start auto-refresh for this match"""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    
    await q.answer("✅ Auto-refresh started! Updates every 1.5s")
    
    # Initialize subscription
    if chat_id not in SUBSCRIPTIONS:
        SUBSCRIPTIONS[chat_id] = {}
    
    SUBSCRIPTIONS[chat_id][key] = {
        "msg_id": q.message.message_id,
        "last_balls": [],
        "six_count": 0
    }
    
    log.info(f"🟢 Auto-refresh STARTED for {key} in chat {chat_id}")
    
    # Send updated message
    data = fetch_match(key)
    text = format_score(data, key)
    kb = [
        [
            InlineKeyboardButton("⏸ Stop Auto", callback_data=f"stop:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    
    try:
        await q.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        log.error(f"start_auto edit: {e}")

async def stop_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Stop auto-refresh"""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    
    # Remove subscription
    if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
        six_count = SUBSCRIPTIONS[chat_id][key].get("six_count", 0)
        del SUBSCRIPTIONS[chat_id][key]
        await q.answer(f"⏸ Stopped (Sixes: {six_count})")
    else:
        await q.answer("⏸ Not running")
    
    log.info(f"🔴 Auto-refresh STOPPED for {key} in chat {chat_id}")
    await q.edit_message_reply_markup(reply_markup=main_menu())

async def back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Back to main menu"""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🏏 *Live Cricket Score Bot*\n\nSelect a match:",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def help_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Help - How to add matches"""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "➕ *Add a Match*\n\n"
        "1. Go to [crex.com](https://crex.com)\n"
        "2. Open F12 → Network tab\n"
        "3. Filter: `getSV3`\n"
        "4. Copy the `key` value from URL\n\n"
        "Then send:\n"
        "`/add <key> <name>`\n\n"
        "_Example:_\n"
        "`/add 118N IND vs AUS`",
        parse_mode="Markdown", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """About bot"""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🤖 *Live Cricket Bot*\n\n"
        "✨ Features:\n"
        "• ⚡ 1.5s auto-refresh\n"
        "• 💥 4/6 animations\n"
        "• 🎉 Six milestones\n"
        "• 📊 Live CRR tracking\n"
        "• 🚀 Railway hosted\n\n"
        "_Data via CREX API_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Add new match"""
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: `/add <key> <name>`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    name = " ".join(ctx.args[1:])
    MATCH_KEYS[key] = name
    await update.message.reply_text(f"✅ Added: *{name}* (`{key}`)", parse_mode="Markdown")
    log.info(f"Added match: {key} - {name}")

async def remove_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Remove match"""
    if not ctx.args:
        await update.message.reply_text("Usage: `/remove <key>`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    if key in MATCH_KEYS:
        name = MATCH_KEYS[key]
        del MATCH_KEYS[key]
        await update.message.reply_text(f"🗑 Removed: *{name}*", parse_mode="Markdown")
        log.info(f"Removed match: {key}")
    else:
        await update.message.reply_text("❌ Key not found")

async def score_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Get score by key"""
    if not ctx.args:
        await update.message.reply_text("Usage: `/score <key>`\n\nExample: `/score 118N`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    data = fetch_match(key)
    kb = [[InlineKeyboardButton("▶️ Start Auto", callback_data=f"start:{key}")]]
    await update.message.reply_text(format_score(data, key), parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(kb))

async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """List all matches"""
    if not MATCH_KEYS:
        await update.message.reply_text("No matches added. Use `/add`")
        return
    text = "📋 *Saved Matches:*\n\n" + "\n".join(f"• `{k}` — {v}" for k, v in MATCH_KEYS.items())
    await update.message.reply_text(text, parse_mode="Markdown")

# ========== MAIN ==========
def main():
    """Initialize and run bot"""
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable not set!")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    
    # Button callbacks
    app.add_handler(CallbackQueryHandler(show_match, pattern="^k:"))
    app.add_handler(CallbackQueryHandler(start_auto, pattern="^start:"))
    app.add_handler(CallbackQueryHandler(stop_auto, pattern="^stop:"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(help_btn, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(about, pattern="^about$"))
    
    # Start auto-refresh background loop
    async def post_init_handler(app_instance):
        """Called when bot starts"""
        asyncio.create_task(auto_refresh_loop(app_instance))
    
    app.post_init = post_init_handler
    
    log.info("✅ Bot started with auto-refresh loop")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
