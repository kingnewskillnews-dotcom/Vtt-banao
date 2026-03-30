import os
import asyncio
import subprocess
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from faster_whisper import WhisperModel
from aiohttp import web

# --- CONFIGURATION ---
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

OWNER_ID = 5351848105
ALLOWED_USER = 5344078567
ALLOWED_GROUP = -1003899919015
PORT = int(os.getenv("PORT", 10000))

app = Client("subtitle_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- GLOBAL VARIABLES ---
active_tasks = {} # User ke current running tasks track karne ke liye

# --- WEB SERVER FOR RENDER ---
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is running FAST with Skip/Refresh!")
    web_app = web.Application()
    web_app.router.add_get("/", handle)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# --- HELPER: TASK CANCELLER ---
def cancel_user_task(user_id):
    if user_id in active_tasks:
        task = active_tasks[user_id]
        task["stop_event"].set() # Timer aur AI loop rok dega
        
        # FFmpeg ya yt-dlp background process ko kill karna
        if task.get("process"):
            try:
                task["process"].kill()
            except Exception:
                pass
                
        del active_tasks[user_id]
        return "Process Skipped/Cancelled ⏭️"
    return "Koi process active nahi hai."

# --- HELPER: TIMER BAR ---
async def timer_bar(message, text, stop_event):
    count = 0
    while not stop_event.is_set():
        try:
            bar_fill = (count % 10) + 1
            bar = "█" * bar_fill + "▒" * (10 - bar_fill)
            await message.edit_text(f"{text}\n[{bar}] {count}s")
            await asyncio.sleep(2)
            count += 2
        except:
            break

# --- HELPER: FORMATTING ---
def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")

def generate_srt(segments, filename):
    with open(filename, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            f.write(f"{i}\n{format_time(segment.start)} --> {format_time(segment.end)}\n{segment.text.strip()}\n\n")

def generate_vtt(segments, filename):
    with open(filename, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for segment in segments:
            start = format_time(segment.start).replace(",", ".")
            end = format_time(segment.end).replace(",", ".")
            f.write(f"{start} --> {end}\n{segment.text.strip()}\n\n")

# --- HELPER: AI PROCESSING (Background Thread) ---
def process_audio(audio_path, req_format, sub_file, stop_event):
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        audio_path, beam_size=1, vad_filter=True, 
        vad_parameters=dict(min_silence_duration_ms=500)
    )
    
    segments_list = []
    # Agar user bich me skip dabaye toh AI ruk jaye
    for segment in segments:
        if stop_event.is_set():
            return False 
        segments_list.append(segment)
        
    if req_format == "vtt":
        generate_vtt(segments_list, sub_file)
    else:
        generate_srt(segments_list, sub_file)
    return True

# --- COMMANDS & BUTTONS ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "welcome 🤗 asi friend 🪄\nsubtitle loge\nselect video video reply\n#vtt #srt\nExtra command\n#refresh #skip",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Refresh #refresh", callback_data="refresh"),
             InlineKeyboardButton("Skip #skip", callback_data="skip")]
        ])
    )

# Button Clicks (Skip/Refresh Handle)
@app.on_callback_query(filters.regex("^(skip|refresh)$"))
async def handle_buttons(client, query):
    user_id = query.from_user.id
    if user_id not in [OWNER_ID, ALLOWED_USER]:
        return await query.answer("Aap authorized nahi ho!", show_alert=True)
        
    msg = cancel_user_task(user_id)
    if query.data == "refresh":
        msg = "Bot Refreshed! 🔄 Nayi file send karein."
    
    await query.answer(msg, show_alert=True)
    await query.message.reply_text(msg)

# Text Commands (Skip/Refresh Handle)
@app.on_message(filters.regex(r"(?i)^#(skip|refresh)"))
async def handle_text_commands(client, message):
    user_id = message.from_user.id if message.from_user else 0
    if user_id not in [OWNER_ID, ALLOWED_USER] and message.chat.id != ALLOWED_GROUP:
        return
        
    msg = cancel_user_task(user_id)
    if "#refresh" in message.text.lower():
        msg = "Bot Refreshed! 🔄 Nayi file send karein."
    await message.reply_text(msg)

# Main Processing (#vtt / #srt)
@app.on_message(filters.regex(r"(?i)^#(vtt|srt)"))
async def process_sub(client, message):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    
    if user_id not in [OWNER_ID, ALLOWED_USER] and chat_id != ALLOWED_GROUP:
        return

    # Ek waqt me ek hi task ho
    if user_id in active_tasks:
        await message.reply_text("Ek process pehle se chal raha hai. Pehle use #skip karein.")
        return

    cmd = message.text.lower().strip()
    is_link = False
    link_url = ""

    if message.reply_to_message:
        target_msg = message.reply_to_message
        if target_msg.text and "http" in target_msg.text:
            is_link = True
            link_url = target_msg.text
        elif not (target_msg.video or target_msg.document):
            await message.reply_text("Bhai, video, document, ya video link ko reply kar ke command do.")
            return
    else:
        await message.reply_text("Please select a video/link and reply with #vtt or #srt.")
        return

    req_format = "vtt" if "#vtt" in cmd else "srt"
    msg = await message.reply_text("Prosesing... ⏳")
    
    stop_event = asyncio.Event()
    active_tasks[user_id] = {"process": None, "stop_event": stop_event}
    
    audio_path = f"audio_{message.id}.wav"
    sub_file = f"output_{message.id}.{req_format}"

    timer_task = asyncio.create_task(timer_bar(msg, "Prosesing... ⏳ (Fast Audio Stream)", stop_event))

    try:
        if is_link:
            command = ["yt-dlp", "-x", "--audio-format", "wav", "-o", audio_path, link_url]
            proc = await asyncio.create_subprocess_exec(*command)
            active_tasks[user_id]["process"] = proc
            await proc.wait()
        else:
            command = [
                "ffmpeg", "-y", "-i", "pipe:0",
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            active_tasks[user_id]["process"] = proc

            try:
                # Video direct stream to ffmpeg
                async for chunk in client.stream_media(target_msg):
                    if stop_event.is_set():
                        raise Exception("User Skipped")
                    proc.stdin.write(chunk)
                    await proc.stdin.drain()
            except Exception:
                pass
            finally:
                if proc.stdin: proc.stdin.close()
                await proc.wait()

        if stop_event.is_set():
            raise Exception("Process Cancelled by User")

        # Extraction completed, start AI Generating timer
        stop_event.set()
        await asyncio.sleep(1)
        
        stop_event.clear()
        timer_task = asyncio.create_task(timer_bar(msg, "Genreting... ⚙️ (AI Subtitles)", stop_event))

        # AI processing ko background thread me chalana (Taaki bot aur commands sun sake)
        success = await asyncio.to_thread(process_audio, audio_path, req_format, sub_file, stop_event)
        
        if not success or stop_event.is_set():
            raise Exception("AI Processing Cancelled by User")

        stop_event.set()
        await msg.delete()
        
        caption = "vtt format\nWEBVTT ✅" if req_format == "vtt" else "srt format\n1\nTiming\nDialogue ✅"
        await message.reply_document(sub_file, caption=caption)
        await message.reply_text("massage 😉 ho gya naa")

    except Exception as e:
        stop_event.set()
        err_msg = str(e)
        if "Cancelled" not in err_msg and "Skipped" not in err_msg:
            await msg.edit_text(f"Error: {err_msg}")
        else:
            await msg.delete()
    
    finally:
        # Pura process khatam hone par safai
        if user_id in active_tasks:
            del active_tasks[user_id]
        for f in [audio_path, sub_file]:
            if os.path.exists(f):
                os.remove(f)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server()) 
    app.run()
