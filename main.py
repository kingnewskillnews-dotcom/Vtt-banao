import os
import asyncio
import gc
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

# --- WEB SERVER (Render Alive) ---
async def web_server():
    async def handle(request): return web.Response(text="Bot is Running!")
    web_app = web.Application()
    web_app.router.add_get("/", handle)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

# --- HELPERS ---
def is_auth(message):
    u_id = message.from_user.id if message.from_user else 0
    return u_id in [OWNER_ID, ALLOWED_USER] or message.chat.id == ALLOWED_GROUP

def format_time(seconds):
    h, m = divmod(seconds, 3600)
    m, s = divmod(m, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".", ",")

# --- WHISPER LOGIC ---
def transcribe_audio(audio_path, req_format, sub_file, stop_event):
    try:
        # Load model only for this task to save RAM
        model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=1)
        segments, _ = model.transcribe(audio_path, beam_size=1, vad_filter=True)

        with open(sub_file, "w", encoding="utf-8") as f:
            if req_format == "vtt": f.write("WEBVTT\n\n")
            for i, s in enumerate(segments, 1):
                if stop_event.is_set(): return False
                start, end = format_time(s.start), format_time(s.end)
                text = s.text.strip()
                if not text: continue
                if req_format == "srt":
                    f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                else:
                    f.write(f"{start.replace(',', '.')} --> {end.replace(',', '.')}\n{text}\n\n")
        
        del model
        gc.collect()
        return True
    except Exception as e:
        print(f"Whisper Error: {e}")
        return False

# --- COMMANDS ---
@app.on_message(filters.command("start"))
async def start(c, m):
    if is_auth(m):
        await m.reply_text("✅ **Bot Connected!**\nReply to any Video (MKV/MP4) or Link with:\n/srt - For SRT file\n/vtt - For VTT file")

@app.on_message(filters.command(["skip", "refresh"]))
async def clean(c, m):
    if not is_auth(m): return
    u_id = m.from_user.id
    if u_id in active_tasks:
        active_tasks[u_id]["stop_event"].set()
        if active_tasks[u_id].get("process"):
            try: active_tasks[u_id]["process"].kill()
            except: pass
    gc.collect()
    await m.reply_text("🧹 Stopped & Memory Cleaned.")

@app.on_message(filters.command(["srt", "vtt"]))
async def process(c, m):
    if not is_auth(m): return
    u_id = m.from_user.id
    cmd = m.command[0].lower()
    target = m.reply_to_message

    if not target: return await m.reply_text("❌ Reply to a video or link first!")
    if u_id in active_tasks: return await m.reply_text("⚠️ Task already running. Use /skip")

    # Check if target is a Link or a File
    is_link = bool(target.text and "http" in target.text.lower())
    
    stop_event = asyncio.Event()
    active_tasks[u_id] = {"stop_event": stop_event, "process": None}
    
    audio_path = f"audio_{u_id}.wav"
    sub_file = f"sub_{u_id}.{cmd}"
    status = await m.reply_text("⏳ **Step 1:** Extracting Audio...")

    try:
        if is_link:
            # Step 1: Get Audio Link using yt-dlp
            ytdl_cmd = ["yt-dlp", "-g", "-f", "bestaudio/best", target.text]
            proc_ytdl = await asyncio.create_subprocess_exec(*ytdl_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await proc_ytdl.communicate()
            stream_url = stdout.decode().strip()
            
            if not stream_url:
                raise Exception("Could not extract stream URL from link.")
            
            # Step 2: Extract audio from URL
            ffmpeg_cmd = ["ffmpeg", "-y", "-i", stream_url, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path]
            proc = await asyncio.create_subprocess_exec(*ffmpeg_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        else:
            # Extract audio from Telegram File (MKV/MP4 support)
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-probesize", "50M", "-analyzeduration", "50M",
                "-fflags", "+genpts+discardcorrupt", "-i", "pipe:0",
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
        
        active_tasks[u_id]["process"] = proc

        if not is_link:
            # Stream Telegram File to FFmpeg
            async for chunk in c.stream_media(target):
                if stop_event.is_set(): break
                proc.stdin.write(chunk)
            if proc.stdin: proc.stdin.close()
        
        await proc.wait()

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 2000:
            raise Exception("Audio extraction failed. File might be too large or invalid.")

        await status.edit_text("🤖 **Step 2:** AI Generating Subtitles...")
        
        # Whisper Processing in Thread
        success = await asyncio.to_thread(transcribe_audio, audio_path, cmd, sub_file, stop_event)

        if success and not stop_event.is_set():
            await m.reply_document(sub_file, caption=f"✅ {cmd.upper()} Subtitles Generated.")
            await status.delete()
        else:
            raise Exception("AI processing failed or was skipped.")

    except Exception as e:
        await status.edit_text(f"❌ **Error:** {str(e)[:250]}")
    finally:
        for f in [audio_path, sub_file]:
            if os.path.exists(f): os.remove(f)
        if u_id in active_tasks: del active_tasks[user_id]
        gc.collect()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
