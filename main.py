import os
import asyncio
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

# --- WEB SERVER FOR RENDER (PORT 10000) ---
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is running!")
    web_app = web.Application()
    web_app.router.add_get("/", handle)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

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
            pass

# --- HELPER: VTT & SRT GENERATORS ---
def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")

def generate_srt(segments, filename):
    with open(filename, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            start = format_time(segment.start)
            end = format_time(segment.end)
            f.write(f"{i}\n{start} --> {end}\n{segment.text.strip()}\n\n")

def generate_vtt(segments, filename):
    with open(filename, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for segment in segments:
            start = format_time(segment.start).replace(",", ".")
            end = format_time(segment.end).replace(",", ".")
            f.write(f"{start} --> {end}\n{segment.text.strip()}\n\n")

# --- COMMANDS ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "welcome 🤗 asi friend 🪄\nsubtitle loge\nselect video video reply\n#vtt #srt\nExtra command\n#refresh #skip",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Refresh #refresh", callback_data="refresh"),
             InlineKeyboardButton("Skip #skip", callback_data="skip")]
        ])
    )

@app.on_message(filters.regex(r"(?i)^#(vtt|srt|refresh|skip)"))
async def process_sub(client, message):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    
    # Permission Check
    if user_id not in [OWNER_ID, ALLOWED_USER] and chat_id != ALLOWED_GROUP:
        return

    cmd = message.text.lower().strip()
    
    if cmd in ["#refresh", "#skip"]:
        await message.reply_text("Command processing skipped/refreshed.")
        return

    is_link = False
    link_url = ""

    # Check reply to video or link
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
    timer_task = asyncio.create_task(timer_bar(msg, "Prosesing... ⏳ (Direct Audio Streaming)", stop_event))
    
    audio_path = f"audio_{message.id}.mp3"
    sub_file = f"output_{message.id}.{req_format}"

    try:
        if is_link:
            # yt-dlp direct link se sirf audio fetch karega, video nahi.
            command = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", audio_path, link_url]
            proc = await asyncio.create_subprocess_exec(*command)
            await proc.wait()
        else:
            # Telegram Cloud se Streaming (NO VIDEO DOWNLOAD)
            command = [
                "ffmpeg", "-y", "-i", "pipe:0",  # Input from Pipe (Stream)
                "-vn", "-acodec", "libmp3lame", "-q:a", "2", audio_path # Only audio extract
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )

            # Pyrogram stream video bytes directly to FFmpeg memory
            try:
                async for chunk in client.stream_media(target_msg):
                    proc.stdin.write(chunk)
                    await proc.stdin.drain()
            except Exception as stream_err:
                pass
            finally:
                proc.stdin.close()
                await proc.wait()

        stop_event.set() # Stop first timer
        await asyncio.sleep(1)
        
        # Start second timer
        stop_event.clear()
        timer_task = asyncio.create_task(timer_bar(msg, "Genreting... ⚙️ (AI Subtitles)", stop_event))

        # Faster Whisper - Gender aur Native Language perfectly detect karega (Memory safe for Render)
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, info = model.transcribe(audio_path, beam_size=5)
        
        segments_list = list(segments)
        
        if req_format == "vtt":
            generate_vtt(segments_list, sub_file)
            caption = "vtt format\nWEBVTT ✅"
        else:
            generate_srt(segments_list, sub_file)
            caption = "srt format\n1\nTiming\nDialogue ✅"

        stop_event.set()
        await msg.delete()
        
        # Output Send
        await message.reply_document(sub_file, caption=caption)
        await message.reply_text("massage 😉 ho gya naa")

    except Exception as e:
        stop_event.set()
        await msg.edit_text(f"Error: {str(e)}")
    
    finally:
        # Pura process khatam hone ke baad Audio aur Vtt delete (Data Clear)
        for f in [audio_path, sub_file]:
            if os.path.exists(f):
                os.remove(f)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server()) 
    app.run()
