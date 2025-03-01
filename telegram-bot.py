import logging
import os
import asyncio
import yt_dlp
import hashlib
import aiohttp
from dotenv import load_dotenv  # New import

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Load .env file variables
load_dotenv()  # New line
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # New token retrieval
PROXY_URL = os.getenv("PROXY_URL")
GET_IP_URL = os.getenv("GET_IP_URL")

CACHE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'cache')

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

if not GET_IP_URL:
    GET_IP_URL = "https://wtfismyip.com/text"

COOKIES_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'cookies.txt')

if not os.path.exists(COOKIES_FILE):
    with open(COOKIES_FILE, 'w') as f:
        f.write("")

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
    ydl_opts = {
        'format': 'best',
        'cookies': COOKIES_FILE,
        'outtmpl': os.path.join(download_path, f'{url_hash}.%(ext)s'),
        'noplaylist': True,
        'progress_hooks': [progress_hook] if progress_hook else [],
    }
    logger.error(f"cookies file: {COOKIES_FILE} ({os.path.getsize(COOKIES_FILE)} bytes)")
    if PROXY_URL:
        ydl_opts['proxy'] = PROXY_URL
        
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    return filename

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
            # Open the downloaded file and send it as a video.
            with open(file_path, 'rb') as video_file:
                await update.message.reply_video(video=video_file)
            await uploading_msg.edit_text("Upload complete.")
        except Exception as e:
            await update.message.reply_text("Failed to send video: " + str(e))

# Main function to set up and run the bot.
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set. Please check your environment or .env file.")
        return

    if custom_request_available:
        # Create a custom Request with a longer read timeout (in seconds).
        req = Request(con_pool_size=8, read_timeout=300)
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).request(req).build()
    else:
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register command and message handlers.
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))

    # Start the bot.
    application.run_polling()

if __name__ == '__main__':
    main()