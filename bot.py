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

ADMIN_ID = 924622824
MATCH_KEYS = {}
SUBSCRIPTIONS = {}
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

# ========== UTILS ==========
def is_admin(user_id):
    return user_id == ADMIN_ID

async def broadcast_message(app, message, parse_mode="HTML"):
    success = 0
    failed = 0
    for chat_id in list(BOT_USERS):
        try:
            await app.bot.send_message(chat_id, message, parse_mode=parse_mode)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            log.warning(f"Broadcast fail {chat_id}: {e}")
    return success, failed

# ========== API ==========
def fetch_match(key):
    try:
        r = requests.get(BASE_URL.format(key), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
        log.warning(f"API {r.status_code} key={key}")
        return None
    except Exception as e:
        log.error(f"Fetch {key}: {e}")
        return None

# ========== BALL DETECTION ==========
def extract_balls_from_over(over_string):
    if not over_string or ":" not in over_string:
        return []
    try:
        _, balls_str = over_string.split(":", 1)
        return balls_str.split(".")
    except:
        return []

def find_new_events(prev_balls, curr_balls):
    if not curr_balls:
        return [], None
    new_count = len(curr_balls) - len(prev_balls)
    if new_count <= 0:
        return [], None
    new_balls = curr_balls[-new_count:]
    events = []
    ball_idx = len(curr_balls) - new_count
    for i, ball in enumerate(new_balls, start=ball_idx):
        ball = ball.strip()
        if ball == "4":
            events.append(("4", "🎯 FOUR!"))
        elif ball == "6":
            events.append(("6", "🚀 SIXER!"))
        elif ball.lower() in ("w", "wd", "wk"):
            events.append(("W", "💔 WICKET!"))
    return events, ball_idx

# ========== FORMATTER (HTML) ==========
def format_score_html(d, key):
    if not d:
        return f"⚠️ <b>No data for key</b> <code>{key}</code>\n\nMatch may be over or key expired."

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
    recent_overs = []
    for k in ["l", "m", "n"]:
        ov_str = d.get(k, "")
        if ov_str and ":" in ov_str:
            ov_num, balls = ov_str.split(":", 1)
            recent_overs.append((ov_num, balls.split(".")))

    lines = []
    lines.append("┌──────────────────────────────────┐")
    lines.append(f"│  {status}  •  Match #{match_no}  •  {fmt}  │")
    lines.append("├──────────────────────────────────┤")
    lines.append(f"│ 🏏 <b>{batting}</b>                       │")
    lines.append(f"│ 📊 <b>{score}</b>  ({overs} ov)               │")
    lines.append(f"│ 🆚 {bowling}                  │")
    if inn1:
        lines.append(f"│ 1st Inns: {inn1}              │")
    if inn2 and inn2 != inn1:
        lines.append(f"│ 2nd Inns: {inn2}              │")
    lines.append("├──────────────────────────────────┤")
    lines.append(f"│ 📈 CRR: {crr}  RRR: {rrr}       │")
    lines.append("├──────────────────────────────────┤")
    if last_ball:
        this_over_balls = []
        for b in last_ball.split("."):
            b = b.strip()
            if b == "4":   emoji = "4️⃣"
            elif b == "6": emoji = "6️⃣"
            elif b.lower() in ("w","wd","wk"): emoji = "🔴"
            elif b == "0": emoji = "⚪"
            elif b == "1": emoji = "1⃣"
            elif b == "2": emoji = "2⃣"
            elif b == "3": emoji = "3⃣"
            else: emoji = b
            this_over_balls.append(emoji)
        lines.append(f"│ ⚡ This Over: {' '.join(this_over_balls)}    │")
    else:
        lines.append("│ ⚡ This Over: —                   │")
    lines.append("├──────────────────────────────────┤")
    for ov_num, balls in recent_overs:
        formatted = []
        for b in balls:
            b = b.strip()
            if b == "4":   formatted.append("4️⃣")
            elif b == "6": formatted.append("6️⃣")
            elif b.lower() in ("w","wd","wk"): formatted.append("🔴")
            elif b == "0": formatted.append("⚪")
            else: formatted.append(b)
        lines.append(f"│ Over {ov_num}: {' '.join(formatted)}     │")
    lines.append("└──────────────────────────────────┘")

    mt = d.get("mt", 0)
    match_time = datetime.fromtimestamp(mt/1000).strftime("%d %b, %H:%M") if mt else ""
    time_line = f"\n🕐 {match_time}" if match_time else ""

    text = (
        f"<b>{status}</b>  •  Match #{match_no}  •  {fmt}\n"
        f"<pre>{'\n'.join(lines)}</pre>"
        f"{time_line}\n"
        f"<code>🔑 {key}</code>\n\n"
        "<i>🔄 Auto-refresh: ON</i>"
    )
    return text

# ========== ANIMATIONS ==========
async def play_animation(app, chat_id, frames, delay=0.3):
    try:
        msg = await app.bot.send_message(chat_id, frames[0], parse_mode="Markdown")
        for frame in frames[1:]:
            await asyncio.sleep(delay)
            try:
                await app.bot.edit_message_text(frame, chat_id=chat_id, message_id=msg.message_id, parse_mode="Markdown")
            except:
                pass
        await asyncio.sleep(2)
        try:
            await app.bot.delete_message(chat_id, msg.message_id)
        except:
            pass
    except Exception as e:
        log.error(f"Anim error: {e}")

# ========== AUTO REFRESH ==========
async def auto_refresh_loop(app):
    await asyncio.sleep(2)
    while True:
        try:
            await asyncio.sleep(1.5)
            subs_copy = {}
            for chat_id, matches in SUBSCRIPTIONS.items():
                subs_copy[chat_id] = dict(matches)
            for chat_id, matches in subs_copy.items():
                for key, sub in matches.items():
                    await process_subscription(app, chat_id, key, sub)
        except Exception as e:
            log.error(f"Loop error: {e}")

async def process_subscription(app, chat_id, key, sub):
    msg_id = sub.get("msg_id")
    prev_balls = sub.get("last_balls", [])

    data = fetch_match(key)
    if not data:
        return

    current_over = data.get("d", "").split("|")[-1] if data.get("d") else ""
    curr_balls = extract_balls_from_over(current_over)

    events, first_new_ball_idx = find_new_events(prev_balls, curr_balls)

    match_name = MATCH_KEYS.get(key, f"Match {key}")
    batting_team = data.get("a", "").split(".")[0] or "Team"

    overs_str = data.get("q", "0").replace("*", "")
    if "." in overs_str:
        completed_overs, balls_bowled = overs_str.split(".")
        over_num = int(completed_overs) + 1
        ball_num = int(balls_bowled) if balls_bowled else 1
    else:
        over_num = 1
        ball_num = 1

    for event_type, event_text in events:
        log.info(f"✅ {event_text} in {key}")

        if event_type == "4":
            sub["four_count"] = sub.get("four_count", 0) + 1
            asyncio.create_task(play_animation(app, chat_id, FOUR_ANIMATION, 0.25))
            broadcast_msg = (
                f"<b>🎯 FOUR!</b>\n\n"
                f"🏏 <b>{match_name}</b>\n"
                f"🏏 {batting_team} hits a <b>BOUNDARY</b> off ball {ball_num} of over {over_num}!\n"
                f"4️⃣ Runs added to the board! 🚧"
            )
            asyncio.create_task(broadcast_message(app, broadcast_msg))

        elif event_type == "6":
            sub["six_count"] = sub.get("six_count", 0) + 1
            six_total = sub["six_count"]
            asyncio.create_task(play_animation(app, chat_id, SIX_ANIMATION, 0.25))
            broadcast_msg = (
                f"<b>🚀 SIX!</b>\n\n"
                f"🏏 <b>{match_name}</b>\n"
                f"⚡ {batting_team} launches a <b>MAXIMUM</b> over {over_num} (ball {ball_num})!\n"
                f"6️⃣ Runs into the crowd! ⛅\n\n"
                f"💥 Total Sixes: <b>{six_total}</b>"
            )
            asyncio.create_task(broadcast_message(app, broadcast_msg))

            if six_total % 6 == 0:
                milestone_msg = (
                    f"🎉 <b>MILESTONE!</b> 🎉\n\n"
                    f"🏏 {match_name}\n"
                    f"💥 <b>{six_total} SIXES</b> hit!\n"
                    f"🚀 <b>{six_total * 6} runs</b> from sixes!\n"
                    f"⚡ Raining sixes! 🌧️"
                )
                asyncio.create_task(app.bot.send_message(chat_id, milestone_msg, parse_mode="HTML"))

        elif event_type == "W":
            asyncio.create_task(play_animation(app, chat_id, WICKET_ANIMATION, 0.35))
            broadcast_msg = (
                f"<b>💔 WICKET!</b>\n\n"
                f"🏏 <b>{match_name}</b>\n"
                f"🎯 {batting_team} loses a wicket (over {over_num}, ball {ball_num})!\n"
                f"🏏💥 Stumps shattered!"
            )
            asyncio.create_task(broadcast_message(app, broadcast_msg))

    sub["last_balls"] = curr_balls

    # Update scorecard (HTML)
    text = format_score_html(data, key)
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
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        err = str(e).lower()
        if "message to edit not found" in err or "message is not modified" in err:
            if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
                del SUBSCRIPTIONS[chat_id][key]

    # Match ended
    if data.get("ms") in (4, 5):
        if chat_id in SUBSCRIPTIONS and key in SUBSCRIPTIONS[chat_id]:
            six_total = SUBSCRIPTIONS[chat_id][key].get("six_count", 0)
            four_total = SUBSCRIPTIONS[chat_id][key].get("four_count", 0)
            del SUBSCRIPTIONS[chat_id][key]
            summary = (
                f"<b>🏁 Match Ended</b>\n\n"
                f"🏏 {match_name}\n"
                f"💥 Total Sixes: <b>{six_total}</b>\n"
                f"🎯 Total Fours: <b>{four_total}</b>\n"
                f"📊 Boundary Runs: <b>{(six_total * 6) + (four_total * 4)}</b>"
            )
            await app.bot.send_message(chat_id, summary, parse_mode="HTML")

# ========== MENU ==========
def main_menu():
    if not MATCH_KEYS:
        kb = [[InlineKeyboardButton("➕ No Live Matches", callback_data="help")]]
    else:
        kb = [[InlineKeyboardButton(f"🔴 {name}", callback_data=f"k:{k}")] for k, name in MATCH_KEYS.items()]
    kb.append([
        InlineKeyboardButton("ℹ️ About", callback_data="about"),
        InlineKeyboardButton("📊 Stats", callback_data="stats")
    ])
    return InlineKeyboardMarkup(kb)

# ========== HANDLERS ==========
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    BOT_USERS.add(user_id)
    log.info(f"New user: {user_id} | Total users: {len(BOT_USERS)}")
    await update.message.reply_text(
        "🏏 <b>Live Cricket Score Bot</b>\n\n"
        "⚡ Real-time updates every 1.5s\n"
        "💥 Animated 4/6/Wicket alerts\n"
        "📢 Instant broadcast on boundaries\n"
        "🎉 Milestone notifications\n"
        "📊 Enhanced live scorecard\n\n"
        "👇 <b>Select a live match:</b>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def show_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("⚡ Loading...")
    key = q.data.split(":", 1)[1]
    data = fetch_match(key)
    text = format_score_html(data, key)
    kb = [
        [
            InlineKeyboardButton("▶️ Start Live (1.5s)", callback_data=f"start:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    try:
        await q.edit_message_text(text, parse_mode="HTML",
                                   reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        log.error(f"show_match: {e}")

async def start_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    text = format_score_html(data, key)
    kb = [
        [
            InlineKeyboardButton("⏸ Stop", callback_data=f"stop:{key}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")
        ],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    try:
        await q.edit_message_text(text, parse_mode="HTML",
                                   reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        log.error(f"start_auto: {e}")

async def stop_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🏏 <b>Live Cricket Score Bot</b>\n\n👇 Select a match:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🤖 <b>Live Cricket Bot v2.0</b>\n\n"
        "✨ <b>Features:</b>\n"
        "• ⚡ 1.5s auto-refresh\n"
        "• 💥 Animated 4/6/W alerts\n"
        "• 📢 Live broadcast to all users\n"
        "• 🎉 Six milestones\n"
        "• 📊 Enhanced UI with emojis\n"
        "• 🔴 Ball-by-ball tracking\n"
        "• 🚀 Admin controls\n\n"
        f"👥 Active Users: <b>{len(BOT_USERS)}</b>\n"
        f"🏏 Live Matches: <b>{len(MATCH_KEYS)}</b>\n\n"
        "<i>Data via CREX API</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def stats_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total Users: <b>{len(BOT_USERS)}</b>\n"
        f"🏏 Live Matches: <b>{len(MATCH_KEYS)}</b>\n"
        f"🔴 Active Trackers: <b>{active_subs}</b>\n\n"
        f"💥 Sixes Tracked: <b>{total_sixes}</b>\n"
        f"🎯 Fours Tracked: <b>{total_fours}</b>\n"
        f"📊 Total Boundaries: <b>{total_sixes + total_fours}</b>\n"
        f"🏃 Boundary Runs: <b>{(total_sixes * 6) + (total_fours * 4)}</b>"
    )
    await q.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

# ========== ADMIN COMMANDS ==========
async def admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "⚙️ <b>Admin: Add Match</b>\n\n"
            "Usage: <code>/add key match_name</code>\n\n"
            "Example: <code>/add 118N India vs Australia</code>",
            parse_mode="HTML"
        )
        return
    key = ctx.args[0]
    name = " ".join(ctx.args[1:])
    MATCH_KEYS[key] = name
    await update.message.reply_text(
        f"✅ <b>Match Added</b>\n\n"
        f"🏏 {name}\n"
        f"🔑 Key: <code>{key}</code>",
        parse_mode="HTML"
    )
    broadcast_msg = (
        f"🔴 <b>NEW LIVE MATCH!</b>\n\n"
        f"🏏 <b>{name}</b>\n\n"
        f"Use /start to watch live!"
    )
    success, failed = await broadcast_message(ctx.application, broadcast_msg)
    await update.message.reply_text(
        f"📢 Broadcast sent!\n✅ Success: {success}\n❌ Failed: {failed}"
    )
    log.info(f"Admin added: {key} - {name}")

async def admin_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    if not ctx.args:
        await update.message.reply_text(
            "⚙️ <b>Admin: Delete Match</b>\n\n"
            "Usage: <code>/delete key</code>\n\n"
            "Example: <code>/delete 118N</code>",
            parse_mode="HTML"
        )
        return
    key = ctx.args[0]
    if key in MATCH_KEYS:
        name = MATCH_KEYS[key]
        del MATCH_KEYS[key]
        # Remove all subscriptions
        for chat_id in list(SUBSCRIPTIONS.keys()):
            if key in SUBSCRIPTIONS[chat_id]:
                del SUBSCRIPTIONS[chat_id][key]
        await update.message.reply_text(
            f"🗑️ <b>Match Deleted</b>\n\n"
            f"🏏 {name}\n"
            f"🔑 Key: <code>{key}</code>",
            parse_mode="HTML"
        )
        log.info(f"Admin deleted: {key}")
    else:
        await update.message.reply_text("❌ Match key not found")

async def admin_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    if not MATCH_KEYS:
        await update.message.reply_text("📋 No matches added")
        return
    text = "📋 <b>Live Matches:</b>\n\n"
    for k, v in MATCH_KEYS.items():
        text += f"🏏 {v}\n<code>{k}</code>\n\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    if not ctx.args:
        await update.message.reply_text(
            "⚙️ <b>Admin: Broadcast</b>\n\n"
            "Usage: <code>/broadcast message</code>\n\n"
            "Example: <code>/broadcast Big match coming up!</code>",
            parse_mode="HTML"
        )
        return
    message = " ".join(ctx.args)
    success, failed = await broadcast_message(ctx.application, f"📢 <b>Announcement</b>\n\n{message}")
    await update.message.reply_text(
        f"✅ Broadcast complete!\n\n"
        f"📤 Sent: {success}\n"
        f"❌ Failed: {failed}",
        parse_mode="HTML"
    )

async def admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return
    active_subs = sum(len(matches) for matches in SUBSCRIPTIONS.values())
    text = (
        "📊 <b>Admin Dashboard</b>\n\n"
        f"👥 Total Users: <b>{len(BOT_USERS)}</b>\n"
        f"🏏 Live Matches: <b>{len(MATCH_KEYS)}</b>\n"
        f"🔴 Active Watchers: <b>{active_subs}</b>\n\n"
        "✅ <b>Matches:</b>\n"
    )
    for key, name in MATCH_KEYS.items():
        watchers = sum(1 for matches in SUBSCRIPTIONS.values() if key in matches)
        text += f"• {name}: {watchers} 👁️\n"
    await update.message.reply_text(text, parse_mode="HTML")

# ========== MAIN ==========
def main():
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
