import os, sys, time, asyncio, subprocess, pyrogram.utils
from pyrogram import Client

def patched_get_peer_type(peer_id: int) -> str:
    val = str(peer_id)
    if val.startswith("-100"): return "channel"
    elif val.startswith("-"): return "chat"
    else: return "user"
pyrogram.utils.get_peer_type = patched_get_peer_type

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
TASK_TYPE = os.getenv("TASK_TYPE")
VIDEO_ID = os.getenv("VIDEO_ID")
SUB_ID = os.getenv("SUB_ID")
CHAT_ID = int(os.getenv("CHAT_ID"))
RESO = os.getenv("RESOLUTION")
WM_ID = os.getenv("WM_ID")
WM_POS = os.getenv("WM_POS")
RENAME = os.getenv("RENAME")

last_edit_time = 0

async def progress_bar(current, total, app, msg_id, action_text):
    global last_edit_time
    now = time.time()
    if now - last_edit_time > 10 or current == total:
        try:
            percent = (current / total) * 100 if total > 0 else 0
            curr_mb = current / (1024 * 1024)
            tot_mb = total / (1024 * 1024) if total > 0 else 0
            await app.edit_message_text(CHAT_ID, msg_id, f"⚙️ {action_text}\n⏳ `{percent:.1f}%`\n📦 `{curr_mb:.1f}MB / {tot_mb:.1f}MB`")
            last_edit_time = now
        except: pass

async def download_phase():
    app = Client("worker_down", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    await app.start()
    status_msg = await app.send_message(CHAT_ID, "⚙️ Preparing Download...")
    msg_id = status_msg.id
    try:
        video_path = await app.download_media(VIDEO_ID, file_name="video.mp4", progress=progress_bar, progress_args=(app, msg_id, "📥 Downloading Video..."))
        sub_path, wm_path = None, None
        if TASK_TYPE == "hsub":
            sub_path = await app.download_media(SUB_ID, progress=progress_bar, progress_args=(app, msg_id, "📥 Downloading Subtitle..."))
            if WM_ID != "none":
                wm_path = await app.download_media(WM_ID, file_name="wm.png", progress=progress_bar, progress_args=(app, msg_id, "📥 Downloading Watermark..."))
        await app.edit_message_text(CHAT_ID, msg_id, "🔥 **Processing Started!** *(Please wait)*")
        await app.stop()
        return video_path, sub_path, wm_path, msg_id
    except Exception as e:
        await app.edit_message_text(CHAT_ID, msg_id, f"❌ Error: {e}")
        sys.exit(1)

def encode_phase(video_path, sub_path, wm_path):
    output = RENAME if RENAME != "none" else "output.mp4"
    if TASK_TYPE == "hsub":
        abs_sub = os.path.abspath(sub_path).replace('\\', '/')
        if wm_path:
            overlay_pos = "20:20" if WM_POS == "TL" else "W-w-20:20"
            cmd = ["ffmpeg", "-y", "-i", video_path, "-i", wm_path, "-filter_complex", f"[0:v]subtitles='{abs_sub}':charenc=UTF-8[sub];[1:v]scale=200:-1[wm];[sub][wm]overlay={overlay_pos}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-c:a", "aac", output]
        else:
            cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"subtitles='{abs_sub}':charenc=UTF-8", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-c:a", "aac", output]
    elif TASK_TYPE == "resize":
        cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"scale=-2:{RESO}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-c:a", "aac", output]
    elif TASK_TYPE == "extract":
        output = "extracted_sub.srt"
        cmd = ["ffmpeg", "-y", "-i", video_path, "-map", "0:s:0", "-c:s", "srt", output] # Added -c:s srt for ultra-fast extract
    process = subprocess.run(cmd, capture_output=True, text=True)
    return output, process.returncode, process.stderr

async def upload_phase(output, returncode, stderr, msg_id):
    app = Client("worker_up", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    await app.start()
    try:
        if returncode == 0 and os.path.exists(output):
            await app.send_document(CHAT_ID, document=output, caption="✅ Completed", progress=progress_bar, progress_args=(app, msg_id, "📤 Uploading..."))
            await app.delete_messages(CHAT_ID, msg_id)
        else:
            await app.edit_message_text(CHAT_ID, msg_id, f"❌ **Error:**\n`{stderr[-500:]}`")
    finally: await app.stop()

if __name__ == "__main__":
    v_path, s_path, w_path, m_id = asyncio.run(download_phase())
    out, rc, err = encode_phase(v_path, s_path, w_path)
    asyncio.run(upload_phase(out, rc, err, m_id))
