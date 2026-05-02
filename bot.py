import os
import logging
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# ========== CONFIGURATION ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 924622824

BASE_URL = "https://api.goscorer.com/api/v3/getSV3?key={}"
HEADERS = {
    "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCIsImV4cGlyZXNJbiI6IjM2NWQifQ.eyJ0aW1lIjoxNjYwMDQ2NjIwMDAwfQ.bTEmMWlR7hLRUHxPPq6-1TP7cuuW7m6sZ9jcdbYzLRA",
    "origin": "https://crex.com",
    "referer": "https://crex.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# ========== DATABASE (IN-MEMORY) ==========
MATCH_KEYS = {}       # {key: "Match Name"}
BOT_USERS = set()     # Tracks every user chat_id who starts the bot

# Tracking user screens: {chat_id: {key: {"msg_id": 123, "last_text": "..."}}}
SUBSCRIPTIONS = {}

# Tracking game engine: {key: {"over": "19", "balls": ['1', '2', '4']}}
MATCH_STATES = {}

STATUS_MAP = {
    0: "⏳ Upcoming", 1: "🟡 Starting Soon", 2: "🔴 LIVE",
    3: "☕ Innings Break", 4: "✅ Completed", 5: "🏁 Result"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

# ========== UTILITIES ==========
def is_admin(user_id):
    return user_id == ADMIN_ID

async def broadcast_to_all(app, message):
    """Broadcasts a message to ALL users who have ever started the bot."""
    success = 0
    # Copy the set to a list to avoid runtime modification errors
    for chat_id in list(BOT_USERS):
        try:
            await app.bot.send_message(chat_id, message, parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)  # Safe delay to prevent Telegram rate limit
        except Exception:
            pass
    log.info(f"📢 Broadcast sent to {success} users.")

# ========== CORE MATCH LOGIC ==========
def fetch_match(key):
    """Fetches match data from API."""
    try:
        r = requests.get(BASE_URL.format(key), headers=HEADERS, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.error(f"API Error: {e}")
        return None

def detect_new_events(key, data):
    """Flawlessly detects new 4s, 6s, and Wickets."""
    curr_d = data.get("d", "")
    if not curr_d or "|" not in curr_d:
        return []
        
    curr_over_str = curr_d.split("|")[-1]
    if ":" not in curr_over_str:
        return []
        
    curr_ov, curr_balls_str = curr_over_str.split(":", 1)
    curr_balls = curr_balls_str.split(".")
    
    # Initialize state if missing
    if key not in MATCH_STATES:
        MATCH_STATES[key] = {"over": "-1", "balls": []}
        
    state = MATCH_STATES[key]
    new_events = []
    
    if curr_ov == state["over"]:
        # We are in the same over, find the newly added balls
        prev_count = len(state["balls"])
        if len(curr_balls) > prev_count:
            new_events = curr_balls[prev_count:]
    else:
        # Over changed, all balls in this new over are new
        new_events = curr_balls
        
    # Update the state to the new reality
    MATCH_STATES[key] = {"over": curr_ov, "balls": curr_balls}
    
    return new_events

# ========== UI & FORMATTING ==========
def format_balls(over_str):
    """Converts a string of balls into beautiful UI emojis."""
    if not over_str or ":" not in over_str: return ""
    ov, balls = over_str.split(":", 1)
    
    fmt = []
    for b in balls.split("."):
        b = b.strip().upper()
        if b == "4": fmt.append("4️⃣")
        elif b == "6": fmt.append("6️⃣")
        elif b in ("W", "WK", "WD"): fmt.append("🔴W")
        elif b == "0": fmt.append("⚪")
        elif b == "1": fmt.append("1️⃣")
        elif b == "2": fmt.append("2️⃣")
        elif b == "3": fmt.append("3️⃣")
        else: fmt.append(b)
        
    return f" **Ov {ov}:** " + " ".join(fmt)

def format_score(d, key):
    """Builds the live scoreboard."""
    if not d: return f"⚠️ **Data unavailable for `{key}`** "

    match_name = MATCH_KEYS.get(key, "Live Match")
    batting = d.get("a", "").split(".")[0] or "Batting Team"
    bowling = d.get("F", "").replace("^", "") or "Bowling Team"
    score = d.get("ats", "—")
    overs = d.get("q", "0").replace("*", "")
    crr = d.get("s", "—")
    match_no = d.get("mn", "?")
    status = STATUS_MAP.get(d.get("ms", 0), "Unknown")
    
    last_ball_str = d.get("d", "").split("|")[-1] if d.get("d") else ""
    current_over_ui = format_balls(last_ball_str) if last_ball_str else "—"

    text = (
        f"{'🔴' if d.get('ms')==2 else '🏏'} **{status}** • {match_name}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏏 **{batting}** \n"
        f"🎯 **{score}**  ({overs} Ov)\n"
        f"🆚 **vs {bowling}** \n\n"
        f"📊 **CRR:** `{crr}`\n\n"
        f"⚡ {current_over_ui}\n"
    )

    last_overs = [format_balls(d.get(k, "")) for k in ["l", "m", "n"] if d.get(k)]
    if last_overs:
        text += f"\n📜 **Recent Overs:** \n" + "\n".join(f"  {ov}" for ov in last_overs if ov)

    text += f"\n\n🔄 Auto-refresh: **ON** | 🔑 `{key}`"
    return text

# ========== BACKGROUND WORKER ==========
async def auto_refresh_loop(app):
    """Fetches data from API and updates UI for all watchers."""
    await asyncio.sleep(2)
    
    while True:
        try:
            # Find all matches that people are currently watching
            active_keys = set(k for subs in SUBSCRIPTIONS.values() for k in subs.keys())
            
            for key in active_keys:
                data = fetch_match(key)
                if not data: continue
                
                match_name = MATCH_KEYS.get(key, f"Match {key}")
                batting_team = data.get("a", "").split(".")[0] or "Batting Team"
                
                # 1. Detect Boundaries and Broadcast!
                new_balls = detect_new_events(key, data)
                for ball in new_balls:
                    ball = ball.strip().upper()
                    if ball == "4":
                        await broadcast_to_all(app, f"🎯 **FOUR!** 🎯\n\n🏏 **{match_name}** \n⚡ {batting_team} hits a boundary! 4️⃣ runs added!")
                    elif ball == "6":
                        await broadcast_to_all(app, f"🚀 **SIXER!** 🚀\n\n🏏 **{match_name}** \n⚡ {batting_team} hit the six on sky! ⛅")
                    elif ball in ("W", "WK", "WD"):
                        await broadcast_to_all(app, f"💔 **WICKET!** 💔\n\n🏏 **{match_name}** \n🎯 {batting_team} loses a wicket! Stumps down! 🏏💥")
                
                # 2. Update Live Message for Subscribers
                new_text = format_score(data, key)
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏸ Stop Auto", callback_data=f"stop:{key}"),
                     InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")],
                    [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
                ])
                
                # Find all users watching this specific key
                for chat_id, subs in list(SUBSCRIPTIONS.items()):
                    if key in subs:
                        sub_data = subs[key]
                        
                        # Fix: Only edit if the text actually changed to prevent Telegram errors
                        if sub_data.get("last_text") != new_text:
                            try:
                                await app.bot.edit_message_text(
                                    new_text, chat_id=chat_id, message_id=sub_data["msg_id"],
                                    parse_mode="Markdown", reply_markup=kb
                                )
                                # Save new text to prevent duplicate edits
                                SUBSCRIPTIONS[chat_id][key]["last_text"] = new_text
                                
                            except BadRequest as e:
                                err = str(e).lower()
                                if "not modified" in err:
                                    pass # Safe to ignore
                                elif "not found" in err:
                                    del SUBSCRIPTIONS[chat_id][key] # Message deleted by user
                            except Exception as e:
                                log.error(f"Edit error for {chat_id}: {e}")
                                
                # 3. Handle Match Completion
                if data.get("ms") in (4, 5):
                    for chat_id in list(SUBSCRIPTIONS.keys()):
                        if key in SUBSCRIPTIONS[chat_id]:
                            del SUBSCRIPTIONS[chat_id][key]
                    if key in MATCH_STATES:
                        del MATCH_STATES[key]

        except Exception as e:
            log.error(f"Main loop error: {e}")
        
        # 1.5 Seconds delay for fast updates
        await asyncio.sleep(1.5)

# ========== HANDLERS ==========
def main_menu():
    if not MATCH_KEYS:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🚫 No Live Matches Yet", callback_data="none")]])
    kb = [[InlineKeyboardButton(f"🔴 {name}", callback_data=f"k:{k}")] for k, name in MATCH_KEYS.items()]
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start bot and add user to global broadcast list."""
    chat_id = update.effective_user.id
    BOT_USERS.add(chat_id) # Save user for broadcasting
    
    await update.message.reply_text(
        "🏏 **Live Cricket Score Bot** \n\n"
        "⚡ Auto-updates every 1.5s\n"
        "📢 Global Alerts for 4s, 6s, and Wickets\n"
        "✨ Premium Ball-by-Ball UI\n\n"
        "👇 **Select a Match:** ",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def show_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show details when clicking a match."""
    q = update.callback_query
    if q.data == "none":
        await q.answer("No matches right now!")
        return
        
    await q.answer("⚡ Loading...")
    key = q.data.split(":", 1)[1]
    
    data = fetch_match(key)
    text = format_score(data, key)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start Live Tracking", callback_data=f"start:{key}")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ])
    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception: pass

async def start_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User starts auto-refresh."""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    
    await q.answer("✅ Live Tracking Started!")
    
    if chat_id not in SUBSCRIPTIONS:
        SUBSCRIPTIONS[chat_id] = {}
        
    # Get initial text to store in tracker
    data = fetch_match(key)
    initial_text = format_score(data, key)
    
    SUBSCRIPTIONS[chat_id][key] = {
        "msg_id": q.message.message_id,
        "last_text": initial_text
    }
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏸ Stop Auto", callback_data=f"stop:{key}"),
         InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ])
    try:
        await q.edit_message_text(initial_text, parse_mode="Markdown", reply_markup=kb)
    except Exception: pass

async def stop_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User stops auto-refresh."""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    
    if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
        del SUBSCRIPTIONS[chat_id][key]
        await q.answer("⏸ Live tracking stopped")
    else:
        await q.answer("⏸ Not tracking currently")
        
    await q.edit_message_reply_markup(reply_markup=main_menu())

async def back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🏏 **Select a Match:** ", parse_mode="Markdown", reply_markup=main_menu())

# ========== ADMIN COMMANDS ==========
async def admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only!")
        return
        
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: `/add <key> <Match Name>`\nExample: `/add 118N IND vs AUS`", parse_mode="Markdown")
        return
    
    key = ctx.args[0]
    name = " ".join(ctx.args[1:])
    MATCH_KEYS[key] = name
    
    await update.message.reply_text(f"✅ Added: {name} (`{key}`)", parse_mode="Markdown")
    # Broadcast to everyone!
    await broadcast_to_all(ctx.application, f"🔴 **NEW LIVE MATCH ADDED!** \n\n🏏 **{name}** \n\nUse /start to watch live!")

async def admin_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Usage: `/delete <key>`", parse_mode="Markdown")
        return
        
    key = ctx.args[0]
    if key in MATCH_KEYS:
        name = MATCH_KEYS.pop(key)
        for c_id in list(SUBSCRIPTIONS.keys()):
            if key in SUBSCRIPTIONS[c_id]: del SUBSCRIPTIONS[c_id][key]
        if key in MATCH_STATES: del MATCH_STATES[key]
        await update.message.reply_text(f"🗑️ Deleted Match: {name}")
    else:
        await update.message.reply_text("❌ Key not found.")

async def admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin sends a custom broadcast to everyone."""
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode="Markdown")
        return
        
    message = " ".join(ctx.args)
    await broadcast_to_all(ctx.application, f"📢 **Admin Announcement** \n\n{message}")
    await update.message.reply_text("✅ Broadcast sent to all users!")

# ========== MAIN RUNNER ==========
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing!")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", admin_add))
    app.add_handler(CommandHandler("delete", admin_delete))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    
    app.add_handler(CallbackQueryHandler(show_match, pattern="^k:"))
    app.add_handler(CallbackQueryHandler(start_auto, pattern="^start:"))
    app.add_handler(CallbackQueryHandler(stop_auto, pattern="^stop:"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(show_match, pattern="^none$"))
    
    async def post_init_handler(app_instance):
        asyncio.create_task(auto_refresh_loop(app_instance))
        
    app.post_init = post_init_handler
    
    log.info("✅ Bot Started. Admin ID: 924622824")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
