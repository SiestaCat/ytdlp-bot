import logging
import os
import sys
import runpy
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

# Función auxiliar para ejecutar gallery-dl usando runpy.
def run_gallery_dl(args):
    old_argv = sys.argv[:]
    sys.argv = ["gallery-dl"] + args
    try:
        runpy.run_module("gallery_dl.__main__", run_name="__main__")
    finally:
        sys.argv = old_argv

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
        # Parse the browser cookies specification.
        browser_opts = yt_dlp.parse_options(
            ['--cookies-from-browser', COOKIES_FROM_BROWSER]
        ).ydl_opts
        ydl_opts.update(browser_opts)
        # Reassign the custom outtmpl to override the browser options.
        ydl_opts['outtmpl'] = outtmpl
    else:
        ydl_opts['cookies'] = ""

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
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
    welcome_msg = (
        "Welcome! By default the bot downloads video links using yt-dlp.\n"
        "To download a photo gallery, prefix your URL with 'photo '. For example:\n"
        "photo https://www.example.com"
    )
    await update.message.reply_text(welcome_msg)

# Message handler: responde tanto a enlaces de video como a galerías de fotos.
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    # Rama para descarga de galería de fotos si el mensaje inicia con "photo "
    if text.lower().startswith("photo "):
        url = text[6:].strip()  # Se remueve el prefijo "photo "
        # Calcular hash de la URL para usarlo como subcarpeta en cache.
        photo_hash = hashlib.sha256(url.encode()).hexdigest()
        photo_dir = os.path.join(CACHE_DIR, photo_hash)
        os.makedirs(photo_dir, exist_ok=True)
        progress_msg = await update.message.reply_text("Downloading photo gallery, please wait...")
        try:
            # Construir argumentos para gallery-dl, incluyendo COOKIES_FROM_BROWSER si está definido.
            gallery_args = []
            if COOKIES_FROM_BROWSER:
                gallery_args.extend(["--cookies-from-browser", COOKIES_FROM_BROWSER])
            # Usar '-d' para definir el directorio de descarga.
            gallery_args.extend(["-d", photo_dir, url])
            # Ejecutar gallery-dl en un hilo aparte usando la función run_gallery_dl.
            await asyncio.to_thread(run_gallery_dl, gallery_args)
        except SystemExit:
            # gallery-dl puede llamar a sys.exit; se captura para continuar.
            pass
        except Exception as e:
            await update.message.reply_text("Failed to download photo gallery: " + str(e))
            return

        # Recorrer recursivamente photo_dir para obtener todos los archivos (fotos)
        photo_files = []
        for root, dirs, files in os.walk(photo_dir):
            for file in files:
                full_path = os.path.join(root, file)
                photo_files.append(full_path)
        
        if not photo_files:
            await update.message.reply_text("No photos were found in the gallery.")
            return

        uploading_msg = await update.message.reply_text("Uploading photos, please wait...")
        from telegram import InputMediaPhoto

        max_photos_per_group = 10
        for i in range(0, len(photo_files), max_photos_per_group):
            group = photo_files[i:i+max_photos_per_group]
            media_group = []
            file_handlers = []
            try:
                for file_path in group:
                    f = open(file_path, 'rb')
                    file_handlers.append(f)
                    media_group.append(InputMediaPhoto(media=f))
                try:
                    await update.message.reply_media_group(media=media_group)
                except Exception as e:
                    error_str = str(e)
                    # If the error indicates an image processing failure, try sending photos individually.
                    if "image_process_failed" in error_str:
                        for file_path in group:
                            with open(file_path, 'rb') as photo_file:
                                await update.message.reply_photo(photo=photo_file)
                    else:
                        await update.message.reply_text(f"Failed to send photos: {error_str}")
            finally:
                for f in file_handlers:
                    f.close()
        await uploading_msg.edit_text("Upload complete.")
    elif text == 'ip':
        try:
            # Ejecuta la función de obtención de IP en un hilo aparte.
            ip_address = await asyncio.to_thread(get_ip_with_yt_dlp)
            await update.message.reply_text(f"Your IP address is: {ip_address}")
        except Exception as e:
            await update.message.reply_text("Failed to retrieve IP: " + str(e))
    elif "http" in text:
        # Rama para descarga de videos con yt-dlp.
        progress_msg = await update.message.reply_text("Downloading video: 0%")
        loop = asyncio.get_running_loop()

        # Define el progress hook para yt-dlp.
        def progress_hook(d):
            status = d.get('status')
            if status == 'downloading':
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                if total_bytes:
                    downloaded = d.get('downloaded_bytes', 0)
                    percent = downloaded / total_bytes * 100
                    # Actualiza el mensaje de progreso desde el hilo.
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
            # Ejecuta la función de descarga en un hilo aparte.
            file_path = await asyncio.to_thread(download_video, text, CACHE_DIR, progress_hook)
        except Exception as e:
            await update.message.reply_text("Failed to download video: " + str(e))
            return

        # Notificar al usuario que se inicia la carga.
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
                os.remove(file_path)  # Remover archivo original si es necesario.
                await uploading_msg.edit_text("Upload complete in parts.")
            else:
                with open(file_path, 'rb') as video_file:
                    await update.message.reply_video(video=video_file)
                os.remove(file_path)
                await uploading_msg.edit_text("Upload complete.")
        except Exception as e:
            await update.message.reply_text("Failed to send video: " + str(e))

# Main function to set up and run the bot.
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set. Please check your environment or .env file.")
        return

    if custom_request_available:
        from telegram.request import Request
        req = Request(con_pool_size=8, read_timeout=1800)
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
