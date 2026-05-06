import os
import time
import asyncio
import threading
import requests
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from http.server import HTTPServer, BaseHTTPRequestHandler

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME")
PORT = 10000

OWNER_ID = 5351848105       
ALLOWED_USERS = [5344078567]             
ALLOWED_GROUPS = [-1003899919015] 

app = Client("AllInOneBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

users_data = {}
UNAUTHORIZED_CAPTURED = set() 
BANNED_USERS = set()
BOT_BUSY = False
SLEEP_UNTIL = 0

def is_authorized(message: Message) -> bool:
    if not message.from_user: return False
    u_id = message.from_user.id    
    if u_id in BANNED_USERS: return False
    if u_id == OWNER_ID or u_id in ALLOWED_USERS or message.chat.id in ALLOWED_GROUPS:
        return True
    UNAUTHORIZED_CAPTURED.add(u_id)
    return False

# Dynamic GitHub Trigger (Ab workflow name pass kar sakte ho)
def _send_to_github(workflow_name, task):
    url = f"https://api.github.com/repos/{REPO_NAME}/actions/workflows/{workflow_name}/dispatches"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    payload = {"ref": "main", "inputs": task}
    try:
        r = requests.post(url, headers=headers, json=payload)
        if r.status_code == 204:
            return True, "Success"
        else:
            return False, f"Code {r.status_code}: {r.text}"
    except Exception as e:
        return False, str(e)

async def trigger_github(workflow_name, task):
    return await asyncio.to_thread(_send_to_github, workflow_name, task)

# ================= ADMIN CONTROLS =================
@app.on_message(filters.command("add") & filters.user(OWNER_ID))
async def add_user(client, message: Message):
    try:
        new_id = int(message.command[1])
        if new_id not in ALLOWED_USERS:
            ALLOWED_USERS.append(new_id)
            if new_id in UNAUTHORIZED_CAPTURED: UNAUTHORIZED_CAPTURED.remove(new_id)
            await message.reply(f"✅ User `{new_id}` allowed.")
        else: await message.reply("⚠️ User already authorized.")
    except: await message.reply("❌ Use: `/add user_id`")

@app.on_message(filters.command(["cancel", "skip", "remm"]))
async def cancel_task(client, message: Message):
    global BOT_BUSY
    uid = message.from_user.id
    if uid in users_data:
        del users_data[uid]
    BOT_BUSY = False 
    await message.reply("🛑 Task memory cleared. Bot is now FREE.")

# ================= MAIN MENU =================
@app.on_message(filters.command("start"))
async def start(client, message: Message):
    if not is_authorized(message): return
    if time.time() < SLEEP_UNTIL: return
    text = (
        "<b>🔥 All-in-One Subtitle & Encode Bot 🔥</b>\n\n"
        "<b>Video Encoding & Hardsub:</b>\n"
        "/hsub - Add subtitle to video\n"
        "/extracttrack - Extract Softsub from video\n"
        "/1080pdd, /720pdd, /480pdd - Compress Video\n\n"
        "<b>AI Subtitle Generation:</b>\n"
        "Reply video with: `/vtt`, `/srt`, `/ass`\n"
        "Reply sub file with: `/hienglish` (Hinglish Translate)\n\n"
        "/cancel - Clear Memory"
    )
    await message.reply(text)

# ================= PART 1: ENCODE / HARDSUB / COMPRESS =================
@app.on_message(filters.command(["1080pdd", "720pdd", "480pdd"]))
async def resize_command(client, message: Message):
    global BOT_BUSY
    if not is_authorized(message): return
    if BOT_BUSY: return await message.reply("❌ Bot is busy. Please wait or use /cancel.")

    target = message.command[0].replace("pdd", "")
    media = message.reply_to_message.video or message.reply_to_message.document if message.reply_to_message else None
    if not media: return await message.reply("❌ Reply to a video.")

    BOT_BUSY = True
    status = await message.reply(f"⏳ Sending {target}p Task to GitHub...")
    task = {"task_type": "resize", "video_id": media.file_id, "sub_id": "none", "wm_id": "none", "wm_pos": "none", "rename": f"resized_{target}p.mp4", "chat_id": str(message.chat.id), "resolution": target}
    
    success, err = await trigger_github("encode.yml", task)
    if success: await status.edit("✅ **Sent to GitHub!** *(Bot is free)*")
    else: await status.edit(f"❌ **Failed:** `{err}`")
    BOT_BUSY = False

@app.on_message(filters.command("extracttrack"))
async def extract_cmd(client, message: Message):
    global BOT_BUSY
    if not is_authorized(message): return
    if BOT_BUSY: return await message.reply("❌ Bot is busy. Please wait or use /cancel.")

    media = message.reply_to_message.video or message.reply_to_message.document if message.reply_to_message else None
    if not media: return await message.reply("❌ Reply to a video.")

    BOT_BUSY = True
    status = await message.reply("⏳ Sending Extract Task to GitHub...")
    task = {"task_type": "extract", "video_id": media.file_id, "sub_id": "none", "wm_id": "none", "wm_pos": "none", "rename": "extracted_sub.srt", "chat_id": str(message.chat.id), "resolution": "none"}
    
    success, err = await trigger_github("encode.yml", task)
    if success: await status.edit("✅ **Extract Task Sent!**")
    else: await status.edit(f"❌ **Failed:** `{err}`")
    BOT_BUSY = False

@app.on_message(filters.command("hsub"))
async def hsub_cmd(client, message: Message):
    global BOT_BUSY
    if not is_authorized(message): return
    if BOT_BUSY: return await message.reply("❌ Bot is busy.")

    media = message.reply_to_message.video or message.reply_to_message.document if message.reply_to_message else None
    if not media: return await message.reply("❌ Reply to a video.")
    
    BOT_BUSY = True
    users_data[message.from_user.id] = {"type": "encode", "video_id": media.file_id, "chat_id": str(message.chat.id), "state": "WAIT_SUB", "file_name": media.file_name or "video.mp4"}
    await message.reply("📄 Send Subtitle (.srt/.ass)", reply_to_message_id=message.id)

# ================= PART 2: AI SUBTITLE / TRANSLATION =================
@app.on_message(filters.command(["vtt", "srt", "ass"]))
async def generate_sub(client, message: Message):
    if not is_authorized(message): return
    format_type = message.command[0].lower()
    media = message.reply_to_message.video or message.reply_to_message.document if message.reply_to_message else None
    if not media: return await message.reply("❌ Please video pe reply karo.")
    
    base_name = getattr(media, "file_name", "video.mp4").rsplit(".", 1)[0]
    
    if format_type == "ass":
        users_data[message.from_user.id] = {
            "type": "generate", "task_type": "extract_english", "file_id": media.file_id, 
            "format_type": "ass", "chat_id": str(message.chat.id), "file_name": base_name
        }
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎨 ASI Style + WM", callback_data="style_asi")], [InlineKeyboardButton("📄 Normal Style", callback_data="style_normal")]])
        return await message.reply("❓ **Kaunsa Style lagana hai?**", reply_markup=keyboard)

    status = await message.reply("⏳ Sending Task to GitHub Queue...")
    task = {"task_type": "extract_english", "file_id": media.file_id, "format_type": format_type, "chat_id": str(message.chat.id), "msg_id": str(status.id), "file_name": base_name, "style_type": "normal"}
    
    success, err = await trigger_github("generate.yml", task)
    if success: await status.edit(f"✅ **AI Gen Task Sent!**\nFormat: `.{format_type}`")
    else: await status.edit(f"❌ **Failed:** {err}")

@app.on_message(filters.command(["hienglish"]))
async def translate_sub(client, message: Message):
    if not is_authorized(message): return
    doc = message.reply_to_message.document if message.reply_to_message else None
    if not doc or not doc.file_name.endswith((".srt", ".vtt", ".ass")): return await message.reply("❌ Please generated Subtitle file pe reply karo.")
        
    base_name = doc.file_name.rsplit(".", 1)[0]
    format_type = doc.file_name.split('.')[-1]
    
    if format_type == "ass":
        users_data[message.from_user.id] = {
            "type": "generate", "task_type": "translate_hinglish", "file_id": doc.file_id, 
            "format_type": "ass", "chat_id": str(message.chat.id), "file_name": base_name
        }
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎨 ASI Style + WM", callback_data="style_asi")], [InlineKeyboardButton("📄 Normal Style", callback_data="style_normal")]])
        return await message.reply("❓ **Kaunsa Style lagana hai?**", reply_markup=keyboard)

    status = await message.reply("⏳ Sending Translation to Queue...")
    task = {"task_type": "translate_hinglish", "file_id": doc.file_id, "format_type": format_type, "chat_id": str(message.chat.id), "msg_id": str(status.id), "file_name": base_name, "style_type": "normal"}
    
    success, err = await trigger_github("generate.yml", task)
    if success: await status.edit("✅ **Sent to Queue!** Translating to Hinglish...")
    else: await status.edit(f"❌ **Failed:** {err}")

# ================= HANDLERS & CALLBACKS =================
@app.on_message(filters.document | filters.photo | filters.text)
async def handle_inputs(client, message: Message):
    uid = message.from_user.id
    if uid not in users_data: return
    d = users_data[uid]
    state = d.get("state")
    
    if d.get("type") == "encode":
        if state == "WAIT_SUB" and message.document and message.document.file_name.endswith((".srt", ".ass")):
            d["sub_id"] = message.document.file_id
            d["state"] = "WAIT_WM_CHOICE"
            await message.reply("Add Watermark?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data="wm_yes"), InlineKeyboardButton("No", callback_data="wm_skip")]]))
        elif state == "WAIT_WM_PIC" and message.photo:
            d["wm_id"] = message.photo.file_id
            d["state"] = "WAIT_WM_POS"
            await message.reply("Position:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Top-Left", callback_data="pos_TL"), InlineKeyboardButton("Top-Right", callback_data="pos_TR")]]))
        elif state == "WAIT_RENAME_TEXT" and message.text:
            d["file_name"] = message.text.strip() + ".mp4" if not message.text.endswith(".mp4") else message.text.strip()
            await send_hsub_queue(uid, message)

@app.on_callback_query()
async def callbacks(client, query: CallbackQuery):
    uid = query.from_user.id
    if uid not in users_data: return await query.answer("No active task!", show_alert=True)
    d = users_data[uid]
    c_data = query.data
    
    # Encode Callbacks
    if d.get("type") == "encode":
        if c_data == "wm_yes":
            d["state"] = "WAIT_WM_PIC"
            await query.message.edit("🖼️ Send Photo for Watermark.")
        elif c_data == "wm_skip":
            d["wm_id"] = "none"; d["wm_pos"] = "none"; d["state"] = "WAIT_RENAME_CHOICE"
            await query.message.edit("Rename file?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data="rn_yes"), InlineKeyboardButton("Skip", callback_data="rn_skip")]]))
        elif c_data.startswith("pos_"):
            d["wm_pos"] = "TL" if c_data == "pos_TL" else "TR"
            d["state"] = "WAIT_RENAME_CHOICE"
            await query.message.edit("Rename file?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data="rn_yes"), InlineKeyboardButton("Skip", callback_data="rn_skip")]]))
        elif c_data == "rn_yes":
            d["state"] = "WAIT_RENAME_TEXT"
            await query.message.edit("📝 Send new file name.")
        elif c_data == "rn_skip":
            await send_hsub_queue(uid, query.message)
            
    # Generate Style Callbacks
    elif d.get("type") == "generate":
        style_choice = "asi_style" if c_data == "style_asi" else "normal"
        task = {
            "task_type": d["task_type"], "file_id": d["file_id"], "format_type": d["format_type"],
            "chat_id": d["chat_id"], "msg_id": str(query.message.id), "file_name": d["file_name"], "style_type": style_choice
        }
        del users_data[uid]
        await query.message.edit_text("⏳ Sending Task to Queue...")
        success, err = await trigger_github("generate.yml", task)
        if success: await query.message.edit_text(f"✅ **Task Sent!** Style: `{style_choice}`")
        else: await query.message.edit_text(f"❌ **Failed:** {err}")

async def send_hsub_queue(uid, msg):
    global BOT_BUSY
    d = users_data.pop(uid)
    task = {
        "task_type": "hsub", "video_id": d["video_id"], "sub_id": d.get("sub_id", "none"),
        "wm_id": d.get("wm_id", "none"), "wm_pos": d.get("wm_pos", "none"),
        "rename": d.get("file_name", "output.mp4"), "chat_id": d["chat_id"], "resolution": "none"
    }
    status = await msg.reply("⏳ Sending Task to GitHub...")
    success, err = await trigger_github("encode.yml", task)
    if success: await status.edit("✅ **Sent to GitHub! Process started.**")
    else: await status.edit(f"❌ **Failed:** `{err}`")
    BOT_BUSY = False

# ================= SERVER & KEEP ALIVE =================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bot is Running")

async def keep_alive():
    while True:
        await asyncio.sleep(4 * 60) # Pings every 4 minutes to prevent sleep
        try: requests.get("http://127.0.0.0:10000")
        except: pass

async def main():
    await app.start()
    print("🚀 All-In-One Bot Started: Anti-Sleep Enabled.")
    asyncio.create_task(keep_alive())
    await idle()

if __name__ == "__main__":
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever(), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main())
