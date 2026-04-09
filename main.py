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

# --- WEB SERVER (Keep Render Alive) ---
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is running! Optimized for 512MB RAM.")
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
            try:
                task["process"].kill()
            except:
                pass
        return True
    return False

def format_time(seconds):
    h, m = divmod(seconds, 3600)
    m, s = divmod(m, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".", ",")

# --- AI PROCESSING (Memory Efficient) ---
def generate_subs(audio_path, req_format, sub_file, stop_event):
    try:
        # Load model only when needed to save RAM
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        
        segments, _ = model.transcribe(
            audio_path,
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=700)
        )

        with open(sub_file, "w", encoding="utf-8") as f:
            if req_format == "vtt":
                f.write("WEBVTT\n\n")
            
            for i, segment in enumerate(segments, 1):
                if stop_event.is_set():
                    return False
                
                start = format_time(segment.start)
                end = format_time(segment.end)
                text = segment.text.strip()

                if req_format == "srt":
                    f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                else:  # vtt
                    f.write(f"{start.replace(',', '.')} --> {end.replace(',', '.')}\n{text}\n\n")
        
        del model
        gc.collect()
        return True
    except Exception as e:
        print(f"Whisper Error: {e}")
        return False

# --- COMMANDS ---
@app.on_message(filters.command("start"))
async def start(client, message):
    if not check_auth(message): return
    await message.reply_text(
        "👋 **Welcome Friend!**\n\n"
        "Reply to a **Video file** or **Link** with:\n"
        "`/srt` - Get SRT file\n"
        "`/vtt` - Get VTT file\n\n"
        "**Extra:**\n"
        "`/skip` - Stop current process\n"
        "`/refresh` - Clear bot memory"
    )

@app.on_message(filters.command(["skip", "refresh"]))
async def clean(client, message):
    if not check_auth(message): return
    user_id = message.from_user.id
    if cancel_task(user_id):
        await message.reply_text("✅ Stopped and Cleared!")
    else:
        await message.reply_text("No active task.")
    gc.collect()

@app.on_message(filters.command(["srt", "vtt"]))
async def process(client, message):
    if not check_auth(message): return
    user_id = message.from_user.id
    cmd = message.command[0].lower()
    
    target = message.reply_to_message
    if not target:
        return await message.reply_text("❌ Reply to a video or link!")

    is_link = bool(target.text and "http" in target.text.lower())
    
    if user_id in active_tasks:
        return await message.reply_text("⚠️ Task already running. Use /skip first.")

    stop_event = asyncio.Event()
    active_tasks[user_id] = {"stop_event": stop_event, "process": None}

    audio_path = f"audio_{user_id}.wav"
    sub_file = f"sub_{user_id}.{cmd}"
    
    status = await message.reply_text("⏳ Extracting audio... (Direct Stream)")

    try:
        if is_link:
            # Direct Audio Extraction from Link
            proc_cmd = [
                "yt-dlp", "-x", "--audio-format", "wav", 
                "--audio-quality", "0", "--no-playlist",
                "-o", audio_path, target.text
            ]
            proc = await asyncio.create_subprocess_exec(*proc_cmd)
            active_tasks[user_id]["process"] = proc
            await proc.wait()
        else:
            # Direct Audio Extraction from Telegram Video Pipe
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-probesize", "50M", "-analyzeduration", "30M",
                "-i", "pipe:0", "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd, stdin=asyncio.subprocess.PIPE, 
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            active_tasks[user_id]["process"] = proc

            try:
                async for chunk in client.stream_media(target, chunk_size=512*1024):
                    if stop_event.is_set(): break
                    if proc.stdin:
                        proc.stdin.write(chunk)
                        await proc.stdin.drain()
            except:
                pass
            finally:
                if proc.stdin: proc.stdin.close()
                await proc.wait()

        if stop_event.is_set(): raise Exception("Cancelled")

        await status.edit_text("🤖 Generating Subtitles (AI)...")
        
        # Run AI in background thread
        success = await asyncio.to_thread(generate_subs, audio_path, cmd, sub_file, stop_event)

        if success and not stop_event.is_set():
            await message.reply_document(sub_file, caption=f"✅ {cmd.upper()} Subtitles Generated.")
            await status.delete()
        else:
            await status.edit_text("❌ Failed or Skipped.")

    except Exception as e:
        if "Cancelled" in str(e):
            await message.reply_text("⏭️ Process Skipped!")
        else:
            await status.edit_text(f"❌ Error: {str(e)[:200]}")
    finally:
        # Final Cleanup
        for f in [audio_path, sub_file]:
            if os.path.exists(f): os.remove(f)
        if user_id in active_tasks: del active_tasks[user_id]
        gc.collect()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
