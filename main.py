import os
import asyncio
import gc
import subprocess
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from faster_whisper import WhisperModel
from aiohttp import web

# --- CONFIGURATION ---
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

OWNER_ID = 5351848105
ALLOWED_USER = 5344078567
ALLOWED_GROUP = -1003899919015
PORT = int(os.getenv("PORT", 10000))

app = Client("subtitle_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
active_tasks = {}

# --- WEB SERVER ---
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is running! Optimized for Render 512MB.")
    web_app = web.Application()
    web_app.router.add_get("/", handle)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

# --- HELPERS ---
def check_auth(message):
    user_id = message.from_user.id if message.from_user else 0
    return user_id in [OWNER_ID, ALLOWED_USER] or message.chat.id == ALLOWED_GROUP

def cancel_task(user_id):
    if user_id in active_tasks:
        task = active_tasks[user_id]
        task["stop_event"].set()
        if task.get("process"):
            try: task["process"].kill()
            except: pass
        return True
    return False

def format_time(seconds):
    h, m = divmod(seconds, 3600)
    m, s = divmod(m, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".", ",")

# --- AI PROCESSING (SUPER OPTIMIZED) ---
def generate_subs(audio_path, req_format, sub_file, stop_event):
    try:
        # Clear memory before loading AI model
        gc.collect()
        
        # Load model with specific settings for low RAM
        model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=1)
        
        segments, _ = model.transcribe(
            audio_path,
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=1000)
        )

        with open(sub_file, "w", encoding="utf-8") as f:
            if req_format == "vtt": f.write("WEBVTT\n\n")
            for i, segment in enumerate(segments, 1):
                if stop_event.is_set(): return False
                start, end = format_time(segment.start), format_time(segment.end)
                text = segment.text.strip()
                if not text: continue
                
                if req_format == "srt":
                    f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                else:
                    f.write(f"{start.replace(',', '.')} --> {end.replace(',', '.')}\n{text}\n\n")
        
        del model
        gc.collect()
        return True
    except Exception as e:
        print(f"AI Error: {e}")
        return False

# --- COMMANDS ---
@app.on_message(filters.command("start"))
async def start(client, message):
    if not check_auth(message): return
    await message.reply_text("🤖 **Bot Ready!**\nReply to Video/Link with /srt or /vtt")

@app.on_message(filters.command(["skip", "refresh"]))
async def clean(client, message):
    if not check_auth(message): return
    user_id = message.from_user.id
    cancel_task(user_id)
    if user_id in active_tasks: del active_tasks[user_id]
    gc.collect()
    await message.reply_text("🧹 Process stopped and memory cleaned.")

@app.on_message(filters.command(["srt", "vtt"]))
async def process(client, message):
    if not check_auth(message): return
    user_id = message.from_user.id
    cmd = message.command[0].lower()
    
    target = message.reply_to_message
    if not target: return await message.reply_text("❌ Reply to a video or link!")

    is_link = bool(target.text and "http" in target.text.lower())
    if user_id in active_tasks: return await message.reply_text("⚠️ Task running. Use /skip")

    stop_event = asyncio.Event()
    active_tasks[user_id] = {"stop_event": stop_event, "process": None}
    audio_path = f"audio_{user_id}.wav"
    sub_file = f"sub_{user_id}.{cmd}"
    
    status = await message.reply_text("⏳ **Step 1:** Extracting Audio...")

    try:
        if is_link:
            # yt-dlp extraction
            proc_cmd = ["yt-dlp", "-x", "--audio-format", "wav", "-o", audio_path, target.text]
            proc = await asyncio.create_subprocess_exec(*proc_cmd)
            active_tasks[user_id]["process"] = proc
            await proc.wait()
        else:
            # FFmpeg Stream
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-probesize", "32M", "-analyzeduration", "20M",
                "-i", "pipe:0", "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            active_tasks[user_id]["process"] = proc
            
            async for chunk in client.stream_media(target, chunk_size=256*1024):
                if stop_event.is_set(): break
                proc.stdin.write(chunk)
                await proc.stdin.drain()
            
            proc.stdin.close()
            await proc.wait()

        # Check if audio file exists and is not empty
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            raise Exception("Audio extraction failed (Empty File)")

        if stop_event.is_set(): raise Exception("Cancelled")

        await status.edit_text("🤖 **Step 2:** AI Generating Subtitles...")
        success = await asyncio.to_thread(generate_subs, audio_path, cmd, sub_file, stop_event)

        if success and not stop_event.is_set():
            await message.reply_document(sub_file, caption=f"✅ Done! Format: {cmd.upper()}")
            await status.delete()
        else:
            raise Exception("AI Processing Failed")

    except Exception as e:
        await status.edit_text(f"❌ **Error:** {str(e)}")
    finally:
        for f in [audio_path, sub_file]:
            if os.path.exists(f): os.remove(f)
        if user_id in active_tasks: del active_tasks[user_id]
        gc.collect()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
