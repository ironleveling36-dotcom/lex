import os
import logging
import asyncio
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = "https://api.goscorer.com/api/v3/getSV3?key={}"
HEADERS = {
    "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCIsImV4cGlyZXNJbiI6IjM2NWQifQ.eyJ0aW1lIjoxNjYwMDQ2NjIwMDAwfQ.bTEmMWlR7hLRUHxPPq6-1TP7cuuW7m6sZ9jcdbYzLRA",
    "origin": "https://crex.com",
    "referer": "https://crex.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# Admin configuration
ADMIN_ID = 924622824

# Match storage
MATCH_KEYS = {}

# Active subscriptions: {chat_id: {key: {"msg_id": int, "last_balls": list, "six_count": int, "four_count": int}}}
SUBSCRIPTIONS = {}

# Store all bot users
BOT_USERS = set()

STATUS_MAP = {
    0: "⏳ Upcoming",
    1: "🟡 Starting Soon",
    2: "🔴 LIVE",
    3: "☕ Innings Break",
    4: "✅ Completed",
    5: "🏁 Result"
}

FOUR_ANIMATION = [
    "🏏💨━━━━━━━━━━🚧",
    "🏏━💨━━━━━━━━🚧",
    "🏏━━━💨━━━━━━🚧",
    "🏏━━━━━💨━━━━🚧",
    "🏏━━━━━━━💨━━🚧",
    "🏏━━━━━━━━━💨🚧",
    "🎯 **FOUR!** 🎯\n\n4️⃣ **Runs to the Boundary!** 4️⃣\n\n🏏💥━━━━━━━━━━🚧"
]

SIX_ANIMATION = [
    "🏏💥━━━━━━━━━━⛅",
    "🏏━💥━━━━━━━━━☁️",
    "🏏━━━💥━━━━━━━☁️",
    "🏏━━━━━💥━━━━━🌤️",
    "🏏━━━━━━━💥━━━🌥️",
    "🏏━━━━━━━━━💥━☁️",
    "🏏━━━━━━━━━━━💥⛅",
    "🚀 **IT'S A SIX!** 🚀\n\n6️⃣ **MAXIMUM INTO THE SKY!** 6️⃣\n\n✨🎆 Ball hit the sky! 🎇✨"
]

WICKET_ANIMATION = [
    "🎯━━━━━━━━━━🏏",
    "🎯━━━━━━━━🏏💢",
    "🎯━━━━━━🏏💢💢",
    "🎯━━━🏏💢💢💢",
    "🎯🏏💢💢💢💢💢",
    "💔 **WICKET!** 💔\n\n🎯 **THAT'S OUT!** 🎯\n\n🏏💥 Stumps are down!"
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# ========== UTILITY FUNCTIONS ==========
def is_admin(user_id):
    """Check if user is admin"""
    return user_id == ADMIN_ID

async def broadcast_message(app, message, parse_mode="Markdown"):
    """Broadcast message to all bot users"""
    success = 0
    failed = 0
    for chat_id in list(BOT_USERS):
        try:
            await app.bot.send_message(chat_id, message, parse_mode=parse_mode)
            success += 1
            await asyncio.sleep(0.05)  # Avoid rate limits
        except Exception as e:
            failed += 1
            log.warning(f"Broadcast failed for {chat_id}: {e}")
    return success, failed

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
    """Extract balls from over string"""
    if not over_string or ":" not in over_string:
        return []
    try:
        _, balls_str = over_string.split(":", 1)
        return balls_str.split(".")
    except:
        return []

def find_new_events(prev_balls, curr_balls):
    """Compare two ball lists and find NEW 4/6/W events"""
    if not curr_balls:
        return []
    
    new_count = len(curr_balls) - len(prev_balls)
    if new_count <= 0:
        return []
    
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
    ball_list = balls.split(".")
    
    # Add emoji to each ball
    formatted = []
    for b in ball_list:
        b = b.strip()
        if b == "4":
            formatted.append("4️⃣")
        elif b == "6":
            formatted.append("6️⃣")
        elif b.lower() in ("w", "wd", "wk"):
            formatted.append("🔴W")
        elif b == "0":
            formatted.append("⚪")
        elif b == "1":
            formatted.append("1⃣")
        elif b == "2":
            formatted.append("2⃣")
        elif b == "3":
            formatted.append("3⃣")
        else:
            formatted.append(b)
    
    return f" **Over {ov}:** " + " ".join(formatted)

def format_score(d, key):
    """Format complete match score message with enhanced UI"""
    if not d:
        return f"⚠️ **No data for key `{key}`** \n\nMatch may be over or key expired."

    batting = d.get("a", "").split(".")[0] or "—"
    bowling = d.get("F", "").replace("^", "") or "—"
    score = d.get("ats", "—")
    overs = d.get("q", "0").replace("*", "")
    crr = d.get("s", "—")
    rrr = d.get("r", "—")
    match_no = d.get("mn", "?")
    status = STATUS_MAP.get(d.get("ms", 0), "Unknown")
    fmt = "T20" if d.get("f") == 1 else "ODI/Test"

    inn1 = d.get("j", "")
    inn2 = d.get("k", "")

    last_ball = d.get("d", "").split("|")[-1] if d.get("d") else ""
    this_over = " • ".join(last_ball.split(".")) if last_ball else "—"

    mt = d.get("mt", 0)
    match_time = datetime.fromtimestamp(mt/1000).strftime("%d %b, %H:%M") if mt else ""

    # Enhanced UI with better formatting
    text = (
        f"{'🔴' if d.get('ms') == 2 else '🏏'} **{status}**  •  Match #{match_no}  •  {fmt}\n"
        f"{'━' * 30}\n\n"
        f"🏏 **{batting}** \n"
        f"📊 **{score}**  ({overs} ov)\n"
        f"🆚 **vs {bowling}** \n\n"
    )

    # Innings details
    if inn1:
        text += f"1️⃣ **1st Innings:** `{inn1}`\n"
    if inn2 and inn2 != inn1:
        text += f"2️⃣ **2nd Innings:** `{inn2}`\n"

    # Rate stats
    text += f"\n📈 **Run Rate:** \n"
    text += f"   • Current: `{crr}`\n"
    if rrr and rrr != "—":
        text += f"   • Required: `{rrr}`\n"

    # Current over with emoji
    if last_ball:
        formatted_balls = []
        for b in last_ball.split("."):
            b = b.strip()
            if b == "4":
                formatted_balls.append("4️⃣")
            elif b == "6":
                formatted_balls.append("6️⃣")
            elif b.lower() in ("w", "wd", "wk"):
                formatted_balls.append("🔴")
            elif b == "0":
                formatted_balls.append("⚪")
            else:
                formatted_balls.append(b)
        
        text += f"\n⚡ **This Over:** {' '.join(formatted_balls)}\n"

    # Recent overs
    last_overs = []
    for k in ["l", "m", "n"]:
        ov = parse_balls(d.get(k, ""))
        if ov:
            last_overs.append(ov)
    
    if last_overs:
        text += f"\n📜 **Recent Overs:** \n"
        for ov in last_overs:
            text += f"   {ov}\n"

    if match_time:
        text += f"\n🕐 {match_time}"

    text += f"\n\n🔄 Auto-refresh: **ON**  |  🔑 `{key}`"
    return text

# ========== ANIMATIONS ==========
async def play_animation(app, chat_id, frames, delay=0.3):
    """Play animation without blocking"""
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
        await asyncio.sleep(2)
        try:
            await app.bot.delete_message(chat_id, msg.message_id)
        except:
            pass
    except Exception as e:
        log.error(f"Animation error: {e}")

# ========== AUTO REFRESH LOOP ==========
async def auto_refresh_loop(app):
    """Main refresh loop with event broadcasting"""
    await asyncio.sleep(2)
    
    while True:
        try:
            await asyncio.sleep(1.5)
            
            subs_copy = {}
            for chat_id, matches in SUBSCRIPTIONS.items():
                subs_copy[chat_id] = dict(matches)
            
            for chat_id, matches in subs_copy.items():
                for key, sub in matches.items():
                    try:
                        await process_subscription(app, chat_id, key, sub)
                    except Exception as e:
                        log.error(f"Subscription error {chat_id}:{key}: {e}")
        
        except Exception as e:
            log.error(f"Auto-refresh loop error: {e}")

async def process_subscription(app, chat_id, key, sub):
    """Process subscription with broadcast on 4/6"""
    msg_id = sub.get("msg_id")
    prev_balls = sub.get("last_balls", [])
    
    data = fetch_match(key)
    if not data:
        return
    
    current_over = data.get("d", "").split("|")[-1] if data.get("d") else ""
    curr_balls = extract_balls_from_over(current_over)
    
    events = find_new_events(prev_balls, curr_balls)
    
    # Get match name for broadcast
    match_name = MATCH_KEYS.get(key, f"Match {key}")
    batting_team = data.get("a", "").split(".")[0] or "Team"
    
    for event_type, event_text in events:
        log.info(f"✅ Event: {event_text} in {key}")
        
        if event_type == "4":
            sub["four_count"] = sub.get("four_count", 0) + 1
            asyncio.create_task(play_animation(app, chat_id, FOUR_ANIMATION, 0.25))
            
            # Broadcast to all users
            broadcast_msg = (
                f"🎯 **FOUR HIT!** 🎯\n\n"
                f"🏏 **{match_name}** \n"
                f"🏏 {batting_team} hits a **BOUNDARY!** \n"
                f"4️⃣ Runs added to the scoreboard! 🚧"
            )
            asyncio.create_task(broadcast_message(app, broadcast_msg))
        
        elif event_type == "6":
            sub["six_count"] = sub.get("six_count", 0) + 1
            six_total = sub["six_count"]
            
            asyncio.create_task(play_animation(app, chat_id, SIX_ANIMATION, 0.25))
            
            # Broadcast to all users
            broadcast_msg = (
                f"🚀 **SIX HIT INTO THE SKY!** 🚀\n\n"
                f"🏏 **{match_name}** \n"
                f"⚡ {batting_team} launches a **MAXIMUM!** \n"
                f"6️⃣ Ball hit the sky! ⛅\n\n"
                f"💥 Total Sixes: **{six_total}** "
            )
            asyncio.create_task(broadcast_message(app, broadcast_msg))
            
            # Milestone
            if six_total % 6 == 0:
                milestone_msg = (
                    f"🎉 **MILESTONE ALERT!** 🎉\n\n"
                    f"🏏 {match_name}\n"
                    f"💥 **{six_total} SIXES** hit!\n"
                    f"🚀 **{six_total * 6} runs** from sixes!\n"
                    f"⚡ Raining sixes! 🌧️"
                )
                asyncio.create_task(app.bot.send_message(chat_id, milestone_msg, parse_mode="Markdown"))
        
        elif event_type == "W":
            asyncio.create_task(play_animation(app, chat_id, WICKET_ANIMATION, 0.35))
            
            # Broadcast wicket
            broadcast_msg = (
                f"💔 **WICKET!** 💔\n\n"
                f"🏏 **{match_name}** \n"
                f"🎯 {batting_team} loses a wicket!\n"
                f"🏏💥 Stumps are down!"
            )
            asyncio.create_task(broadcast_message(app, broadcast_msg))
    
    sub["last_balls"] = curr_balls
    
    # Update scoreboard
    text = format_score(data, key)
    kb = [
        [
            InlineKeyboardButton("⏸ Stop", callback_data=f"stop:{key}"),
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
        if "message to edit not found" in error_str or "message is not modified" in error_str:
            if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
                del SUBSCRIPTIONS[chat_id][key]
    
    # Match ended
    if data.get("ms") in (4, 5):
        if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
            six_total = SUBSCRIPTIONS[chat_id][key].get("six_count", 0)
            four_total = SUBSCRIPTIONS[chat_id][key].get("four_count", 0)
            del SUBSCRIPTIONS[chat_id][key]
            
            summary = (
                f"🏁 **Match Ended** \n\n"
                f"🏏 {match_name}\n"
                f"💥 Total Sixes: **{six_total}** \n"
                f"🎯 Total Fours: **{four_total}** \n"
                f"📊 Boundary Runs: **{(six_total * 6) + (four_total * 4)}** "
            )
            await app.bot.send_message(chat_id, summary, parse_mode="Markdown")

# ========== HANDLERS ==========
def main_menu():
    """Generate main menu"""
    if not MATCH_KEYS:
        kb = [[InlineKeyboardButton("➕ No Live Matches", callback_data="help")]]
    else:
        kb = [[InlineKeyboardButton(f"🔴 {name}", callback_data=f"k:{k}")] for k, name in MATCH_KEYS.items()]
    
    kb.append([
        InlineKeyboardButton("ℹ️ About", callback_data="about"),
        InlineKeyboardButton("📊 Stats", callback_data="stats")
    ])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start command - track users"""
    user_id = update.effective_user.id
    BOT_USERS.add(user_id)
    log.info(f"New user: {user_id} | Total users: {len(BOT_USERS)}")
    
    await update.message.reply_text(
        "🏏 **Live Cricket Score Bot** \n\n"
        "⚡ Real-time updates every 1.5s\n"
        "💥 Animated 4/6/Wicket alerts\n"
        "📢 Instant broadcast on boundaries\n"
        "🎉 Milestone notifications\n"
        "📊 Enhanced live scorecard\n\n"
        "👇 **Select a live match:** ",
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
            InlineKeyboardButton("▶️ Start Live (1.5s)", callback_data=f"start:{key}"),
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
    """Start auto-refresh"""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    
    await q.answer("✅ Live updates started!")
    
    if chat_id not in SUBSCRIPTIONS:
        SUBSCRIPTIONS[chat_id] = {}
    
    SUBSCRIPTIONS[chat_id][key] = {
        "msg_id": q.message.message_id,
        "last_balls": [],
        "six_count": 0,
        "four_count": 0
    }
    
    log.info(f"🟢 Started: {key} in {chat_id}")
    
    data = fetch_match(key)
    text = format_score(data, key)
    kb = [
        [
            InlineKeyboardButton("⏸ Stop", callback_data=f"stop:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    
    try:
        await q.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        log.error(f"start_auto: {e}")

async def stop_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Stop auto-refresh"""
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id
    
    if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
        stats = SUBSCRIPTIONS[chat_id][key]
        del SUBSCRIPTIONS[chat_id][key]
        await q.answer(f"⏸ Stopped (6s: {stats.get('six_count', 0)}, 4s: {stats.get('four_count', 0)})")
    else:
        await q.answer("⏸ Not running")
    
    log.info(f"🔴 Stopped: {key} in {chat_id}")
    await q.edit_message_reply_markup(reply_markup=main_menu())

async def back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Back to menu"""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🏏 **Live Cricket Score Bot** \n\n👇 Select a match:",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """About bot"""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🤖 **Live Cricket Bot v2.0** \n\n"
        "✨ **Features:** \n"
        "• ⚡ 1.5s auto-refresh\n"
        "• 💥 Animated 4/6/W alerts\n"
        "• 📢 Live broadcast to all users\n"
        "• 🎉 Six milestones\n"
        "• 📊 Enhanced UI with emojis\n"
        "• 🔴 Ball-by-ball tracking\n"
        "• 🚀 Admin controls\n\n"
        f"👥 Active Users: **{len(BOT_USERS)}** \n"
        f"🏏 Live Matches: **{len(MATCH_KEYS)}** \n\n"
        "_Data via CREX API_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def stats_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show bot stats"""
    q = update.callback_query
    await q.answer()
    
    active_subs = sum(len(matches) for matches in SUBSCRIPTIONS.values())
    total_sixes = sum(
        sub.get("six_count", 0)
        for matches in SUBSCRIPTIONS.values()
        for sub in matches.values()
    )
    total_fours = sum(
        sub.get("four_count", 0)
        for matches in SUBSCRIPTIONS.values()
        for sub in matches.values()
    )
    
    text = (
        "📊 **Bot Statistics** \n\n"
        f"👥 Total Users: **{len(BOT_USERS)}** \n"
        f"🏏 Live Matches: **{len(MATCH_KEYS)}** \n"
        f"🔴 Active Trackers: **{active_subs}** \n\n"
        f"💥 Sixes Tracked: **{total_sixes}** \n"
        f"🎯 Fours Tracked: **{total_fours}** \n"
        f"📊 Total Boundaries: **{total_sixes + total_fours}** \n"
        f"🏃 Boundary Runs: **{(total_sixes * 6) + (total_fours * 4)}** "
    )
    
    await q.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

# ========== ADMIN COMMANDS ==========
async def admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: Add match"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    
    if len(ctx.args) < 2:
        await update.message.reply_text(
            " **Admin: Add Match** \n\n"
            "Usage: `/add <key> <match_name>`\n\n"
            "Example:\n"
            "`/add 118N India vs Australia`",
            parse_mode="Markdown"
        )
        return
    
    key = ctx.args[0]
    name = " ".join(ctx.args[1:])
    MATCH_KEYS[key] = name
    
    await update.message.reply_text(
        f"✅ **Match Added** \n\n"
        f"🏏 {name}\n"
        f"🔑 Key: `{key}`",
        parse_mode="Markdown"
    )
    
    # Broadcast to all users
    broadcast_msg = (
        f"🔴 **NEW LIVE MATCH!** \n\n"
        f"🏏 **{name}** \n\n"
        f"Use /start to watch live!"
    )
    success, failed = await broadcast_message(ctx.application, broadcast_msg)
    
    await update.message.reply_text(
        f"📢 Broadcast sent!\n✅ Success: {success}\n❌ Failed: {failed}"
    )
    
    log.info(f"Admin added match: {key} - {name}")

async def admin_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: Delete match"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    
    if not ctx.args:
        await update.message.reply_text(
            " **Admin: Delete Match** \n\n"
            "Usage: `/delete <key>`\n\n"
            "Example: `/delete 118N`",
            parse_mode="Markdown"
        )
        return
    
    key = ctx.args[0]
    if key in MATCH_KEYS:
        name = MATCH_KEYS[key]
        del MATCH_KEYS[key]
        
        # Remove all subscriptions for this match
        for chat_id in list(SUBSCRIPTIONS.keys()):
            if key in SUBSCRIPTIONS[chat_id]:
                del SUBSCRIPTIONS[chat_id][key]
        
        await update.message.reply_text(
            f"🗑️ **Match Deleted** \n\n"
            f"🏏 {name}\n"
            f"🔑 Key: `{key}`",
            parse_mode="Markdown"
        )
        log.info(f"Admin deleted match: {key}")
    else:
        await update.message.reply_text("❌ Match key not found")

async def admin_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: List all matches"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    
    if not MATCH_KEYS:
        await update.message.reply_text("📋 No matches added")
        return
    
    text = "📋 **Live Matches:** \n\n"
    for k, v in MATCH_KEYS.items():
        text += f"🏏 {v}\n🔑 `{k}`\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: Broadcast message"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    
    if not ctx.args:
        await update.message.reply_text(
            " **Admin: Broadcast** \n\n"
            "Usage: `/broadcast <message>`\n\n"
            "Example:\n"
            "`/broadcast Big match starting in 10 minutes!`",
            parse_mode="Markdown"
        )
        return
    
    message = " ".join(ctx.args)
    success, failed = await broadcast_message(ctx.application, f"📢 **Announcement** \n\n{message}")
    
    await update.message.reply_text(
        f"✅ Broadcast complete!\n\n"
        f"📤 Sent: {success}\n"
        f"❌ Failed: {failed}",
        parse_mode="Markdown"
    )

async def admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: Detailed stats"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    
    active_subs = sum(len(matches) for matches in SUBSCRIPTIONS.values())
    
    text = (
        "📊 **Admin Dashboard** \n\n"
        f"👥 Total Users: **{len(BOT_USERS)}** \n"
        f"🏏 Live Matches: **{len(MATCH_KEYS)}** \n"
        f"🔴 Active Watchers: **{active_subs}** \n\n"
        " **Matches:** \n"
    )
    
    for key, name in MATCH_KEYS.items():
        watchers = sum(1 for matches in SUBSCRIPTIONS.values() if key in matches)
        text += f"• {name}: {watchers} 👁️\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ========== MAIN ==========
def main():
    """Initialize and run bot"""
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set!")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # User commands
    app.add_handler(CommandHandler("start", start))
    
    # Admin commands
    app.add_handler(CommandHandler("add", admin_add))
    app.add_handler(CommandHandler("delete", admin_delete))
    app.add_handler(CommandHandler("list", admin_list))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("adminstats", admin_stats))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(show_match, pattern="^k:"))
    app.add_handler(CallbackQueryHandler(start_auto, pattern="^start:"))
    app.add_handler(CallbackQueryHandler(stop_auto, pattern="^stop:"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(about, pattern="^about$"))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    
    # Start background loop
    async def post_init_handler(app_instance):
        asyncio.create_task(auto_refresh_loop(app_instance))
    
    app.post_init = post_init_handler
    
    log.info("✅ Bot started - Admin: 924622824")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
