import os, time, asyncio, subprocess, pysubs2, re
from pyrogram import Client
from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator
from unidecode import unidecode
import pyrogram.utils

def patched_get_peer_type(peer_id: int) -> str: return "user" if not str(peer_id).startswith("-") else "channel" if str(peer_id).startswith("-100") else "chat"
pyrogram.utils.get_peer_type = patched_get_peer_type

API_ID = int(os.getenv("API_ID")); API_HASH = os.getenv("API_HASH"); BOT_TOKEN = os.getenv("BOT_TOKEN")
TASK_TYPE = os.getenv("TASK_TYPE"); FILE_ID = os.getenv("FILE_ID"); FORMAT_TYPE = os.getenv("FORMAT_TYPE")
CHAT_ID = int(os.getenv("CHAT_ID")); MSG_ID = int(os.getenv("MSG_ID"))
FILE_NAME = os.getenv("FILE_NAME", "subtitle"); STYLE_TYPE = os.getenv("STYLE_TYPE", "normal")
app = None; last_edit_time = 0

async def edit_msg(text):
    try: await app.edit_message_text(CHAT_ID, MSG_ID, text)
    except: pass

async def progress_bar(current, total, action_text):
    global last_edit_time
    now = time.time()
    if now - last_edit_time > 8 or current == total:
        try: await edit_msg(f"{action_text}\n⏳ `{(current/total)*100:.1f}%`")
        except: pass
        last_edit_time = now

# --- ASI CUSTOM ASS FORMATTER ---
def apply_asi_style(file_path):
    subs = pysubs2.load(file_path)
    if len(subs) == 0: return
    max_end_ms = max(line.end for line in subs)
    def ms_to_time(ms):
        h, m, s, cs = ms // 3600000, (ms % 3600000) // 60000, (ms % 60000) // 1000, (ms % 1000) // 10
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    max_time_str = ms_to_time(max_end_ms)
    ass_content = f"""[Script Info]
Title: ASI ASS Script
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ASI ᴀɴɪᴍᴇ_Watermark,Arial,140,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,2,9,10,40,40,1
Style: Default,Arial,90,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,-1,0,0,100,100,0,0,1,3.8,2,2,100,100,58,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 10,0:00:00.00,{max_time_str},ASI ᴀɴɪᴍᴇ_Watermark,,0000,0000,0000,,{{\\bord8\\blur5\\shad3}} {{\\c&HFF00FF&}}𝙰{{\\c&HFFFFFF&}}𝚂{{\\c&H00A0FF&}}𝙸☠
"""
    for line in subs:
        text = line.text.replace('\n', '\\N')
        ass_content += f"Dialogue: 0,{ms_to_time(line.start)},{ms_to_time(line.end)},Default,,0000,0000,0000,,{text}\n"
    with open(file_path, "w", encoding="utf-8") as f: f.write(ass_content)

def clean_whatsapp_hinglish(hindi_text):
    # Perfect Hinglish mapping for natural chatting style
    roman = unidecode(hindi_text).lower()
    
    replacements = {
        "maim ": "me ", "mai ": "me ", "hum ": "hu ", "hun ": "hu ", "hūm": "hu",
        " hain": " hai", "thaa": "tha", "thii": "thi", "kyaa": "kya", 
        "jaa": "ja", "rahaa": "raha", "rahii": "rahi", "rahe": "rahe", 
        "mujhe": "muje", "mujhko": "muje", "tujhe": "tuje", "tujhko": "tuje",
        "kaise": "kese", "vaise": "vese", "aur": "our", "kyon": "kyu", 
        "kyun": "kyu", "nahin": "nahi", "nhi": "nahi", "gayaa": "gaya",
        "gayii": "gayi", "aayaa": "aaya", "aayii": "aayi", "karengi": "karengi",
        "karenga": "karega", "jaunga": "jaunga", "jaungi": "jaungi",
        "karoonga": "karunga", "karungi": "karungi", "chahiye": "chahiye",
        "achchha": "acha", "achha": "acha", "ghar": "gher"
    }
    
    for old, new in replacements.items():
        roman = roman.replace(old, new)
        
    return re.sub(r'[<>/\\]', '', roman).strip().capitalize()

def process_english(video_path):
    subprocess.run(["ffmpeg", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "audio.wav", "-y"], capture_output=True)
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe("audio.wav", task="translate", vad_filter=True)
    subs = pysubs2.SSAFile()
    for s in segments:
        if s.text: subs.append(pysubs2.SSAEvent(start=int(s.start*1000), end=int(s.end*1000), text=s.text.strip()))
    
    out = f"{FILE_NAME}.{FORMAT_TYPE}"
    subs.save(out)
    if FORMAT_TYPE == "ass" and STYLE_TYPE == "asi_style": apply_asi_style(out)
    return out

def process_hinglish(sub_path):
    subs = pysubs2.load(sub_path)
    translator = GoogleTranslator(source='en', target='hi')
    texts, indices = [], []
    
    for i, line in enumerate(subs):
        if line.text.strip():
            texts.append(line.text.strip())
            indices.append(i)

    if texts:
        hi_trans = translator.translate_batch(texts)
        for idx, hi_text in zip(indices, hi_trans):
            if hi_text: subs[idx].text = clean_whatsapp_hinglish(hi_text)

    out = f"{FILE_NAME}_Hinglish.{FORMAT_TYPE}"
    subs.save(out)
    if FORMAT_TYPE == "ass" and STYLE_TYPE == "asi_style": apply_asi_style(out)
    return out

async def main():
    global app
    app = Client("worker_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
    await app.start()
    try:
        await edit_msg("📥 Downloading file...")
        file_path = await app.download_media(FILE_ID, progress=progress_bar, progress_args=("📥 Downlading...",))
        loop = asyncio.get_event_loop()
        
        if TASK_TYPE == "extract_english":
            await edit_msg("⚙️ Generating English Subtitle...")
            out_file = await loop.run_in_executor(None, process_english, file_path)
            cap = f"✅ English Generated: `{FILE_NAME}.{FORMAT_TYPE}`"
        else:
            await edit_msg("⚡ Translating to Hinglish...")
            out_file = await loop.run_in_executor(None, process_hinglish, file_path)
            cap = f"✅ Hinglish Generated: `{FILE_NAME}_Hinglish.{FORMAT_TYPE}`"
            
        await app.send_document(CHAT_ID, document=out_file, caption=cap, reply_to_message_id=MSG_ID)
        await app.delete_messages(CHAT_ID, MSG_ID)
    except Exception as e: await edit_msg(f"❌ Error: {e}")
    finally: await app.stop()

if __name__ == "__main__": asyncio.run(main())
