import logging
import os
import asyncio
import yt_dlp
import hashlib
from dotenv import load_dotenv  # New import

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Load .env file variables
load_dotenv()  # New line
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # New token retrieval
PROXY_URL = os.getenv("PROXY_URL")
GET_IP_URL = os.getenv("GET_IP_URL")
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER")

CACHE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'cache')

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

if not GET_IP_URL:
    GET_IP_URL = "https://wtfismyip.com/text"

if not COOKIES_FROM_BROWSER:
    COOKIES_FROM_BROWSER = ""

# Attempt to import Request for custom timeout configuration.
try:
    from telegram.request import Request
    custom_request_available = True
except ImportError:
    custom_request_available = False

# Configure logging for debugging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Function to get IP using yt-dlp (to test proxy)
def get_ip_with_yt_dlp() -> str:
    ip_tmp = os.path.join(CACHE_DIR, "ip.txt")
    ydl_opts = {
        'format': 'best',
        'proxy': PROXY_URL,
        'noplaylist': True,
        'outtmpl': ip_tmp,
        'quiet': True,
        'force_generic_extractor': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([GET_IP_URL])
    with open(ip_tmp, 'r') as f:
        ip = f.read().strip()
    os.remove(ip_tmp)
    return ip

# Function to download video using yt-dlp with progress hook support.
def download_video(url: str, download_path: str, progress_hook=None) -> str:
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    outtmpl = os.path.join(download_path, f'{url_hash}.%(ext)s')
    ydl_opts = {
        'format': 'best',
        'outtmpl': outtmpl,
        'noplaylist': True,
        'progress_hooks': [progress_hook] if progress_hook else [],
    }

    if PROXY_URL:
        ydl_opts['proxy'] = PROXY_URL

    if COOKIES_FROM_BROWSER:
        browser_opts = yt_dlp.parse_options(
            ['--cookies-from-browser', COOKIES_FROM_BROWSER]
        ).ydl_opts
        ydl_opts.update(browser_opts)
        ydl_opts['outtmpl'] = outtmpl
    else:
        ydl_opts['cookies'] = ""

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    
    # If the expected file doesn't exist (e.g. ends with .NA), try to determine the correct file.
    if not os.path.exists(filename):
        # Try using the extension provided in the info dictionary.
        ext = info.get('ext')
        if ext and ext != 'NA':
            candidate = os.path.splitext(filename)[0] + f'.{ext}'
            if os.path.exists(candidate):
                filename = candidate
        else:
            # As a fallback, search the download_path for a file starting with the hash.
            for f in os.listdir(download_path):
                if f.startswith(url_hash):
                    candidate = os.path.join(download_path, f)
                    if os.path.exists(candidate):
                        filename = candidate
                        break

    return filename

def split_file(file_path, chunk_size_bytes=45 * 1024 * 1024) -> list:
    """
    Splits the file at file_path into chunks of chunk_size_bytes.
    Returns a list of paths for the split parts.
    """
    part_paths = []
    with open(file_path, 'rb') as f:
        part = 1
        while True:
            chunk = f.read(chunk_size_bytes)
            if not chunk:
                break
            part_file = f"{file_path}.part{part}"
            with open(part_file, 'wb') as pf:
                pf.write(chunk)
            part_paths.append(part_file)
            part += 1
    return part_paths

# /start command handler.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Welcome! Send me a message or a video link.')

# Message handler: responds to video links by downloading and uploading the video.
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if text == 'ip':
        try:
            # Run the blocking yt-dlp IP retrieval function in a separate thread.
            ip_address = await asyncio.to_thread(get_ip_with_yt_dlp)
            await update.message.reply_text(f"Your IP address is: {ip_address}")
        except Exception as e:
            await update.message.reply_text("Failed to retrieve IP: " + str(e))
    elif "http" in text:
        # Create a message for download progress updates.
        progress_msg = await update.message.reply_text("Downloading video: 0%")
        loop = asyncio.get_running_loop()

        # Define the progress hook for yt-dlp.
        def progress_hook(d):
            status = d.get('status')
            if status == 'downloading':
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                if total_bytes:
                    downloaded = d.get('downloaded_bytes', 0)
                    percent = downloaded / total_bytes * 100
                    # Update the progress message from the thread.
                    asyncio.run_coroutine_threadsafe(
                        progress_msg.edit_text(f"Downloading video: {percent:.1f}%"),
                        loop
                    )
            elif status == 'finished':
                asyncio.run_coroutine_threadsafe(
                    progress_msg.edit_text("Download complete. Uploading video..."),
                    loop
                )

        try:
            # Run the blocking download function in a separate thread.
            file_path = await asyncio.to_thread(download_video, text, CACHE_DIR, progress_hook)
        except Exception as e:
            await update.message.reply_text("Failed to download video: " + str(e))
            return

        # Notify the user that uploading is starting.
        uploading_msg = await update.message.reply_text("Uploading video, please wait...")
        try:
            file_size = os.path.getsize(file_path)
            max_size = 45 * 1024 * 1024  # 45MB
            if file_size > max_size:
                parts = split_file(file_path, max_size)
                total_parts = len(parts)
                for idx, part in enumerate(parts, start=1):
                    with open(part, 'rb') as video_file:
                        await update.message.reply_video(video=video_file, caption=f'Part {idx} of {total_parts}')
                    os.remove(part)
                os.remove(file_path)  # Remove original file if needed.
                await uploading_msg.edit_text("Upload complete in parts.")
            else:
                with open(file_path, 'rb') as video_file:
                    await update.message.reply_video(video=video_file)
                os.remove(file_path)
                await uploading_msg.edit_text("Upload complete.")
        except Exception as e:
            await update.message.reply_text("Failed to send video: " + str(e))

# New handler for photo messages.
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]  # highest resolution
    file = await context.bot.get_file(photo.file_id)
    photo_path = os.path.join(CACHE_DIR, f"{photo.file_unique_id}.jpg")
    await file.download(custom_path=photo_path)
    # Respond by sending the photo back to the user.
    with open(photo_path, 'rb') as photo_file:
        await update.message.reply_photo(photo=photo_file)
    os.remove(photo_path)

# Main function to set up and run the bot.
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set. Please check your environment or .env file.")
        return

    if custom_request_available:
        req = Request(con_pool_size=8, read_timeout=1800)
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).request(req).build()
    else:
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register command and message handlers.
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))  # New handler for photos

    # Start the bot.
    application.run_polling()

if __name__ == '__main__':
    main()