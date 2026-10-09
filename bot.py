import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

BOT_NAME = "YT Shorts Downloader"
MAX_FILE_SIZE = 49 * 1024 * 1024
DOWNLOAD_TIMEOUT = 300
YOUTUBE_RE = re.compile(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.I)
SHORTS_RE = re.compile(r"youtube\.com/shorts/", re.I)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(BOT_NAME)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            body = b"YT Shorts Downloader is running.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        logger.info("health-server: " + fmt, *args)

def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    Thread(target=server.serve_forever, daemon=True, name="health-server").start()
    logger.info("Health endpoint listening on port %s", port)

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Download Shorts", callback_data="download")],
        [InlineKeyboardButton("❓ Help", callback_data="help"),
         InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ])

def help_text():
    return (
        "❓ <b>How to use</b>\n\n"
        "1. Tap <b>🎬 Download Shorts</b>.\n"
        "2. Send a public YouTube Shorts link.\n"
        "3. Wait for processing, then receive the video here.\n\n"
        "<b>Example:</b> <code>https://youtube.com/shorts/VIDEO_ID</code>\n\n"
        "• Public Shorts only.\n"
        "• Videos over the bot upload limit are rejected.\n"
        "• Files are processed temporarily and deleted afterwards.\n"
        "• Use /cancel to cancel."
    )

def about_text():
    return (
        "ℹ️ <b>About</b>\n\n🎬 <b>YT Shorts Downloader</b>\n\n"
        "A simple Telegram bot for processing public YouTube Shorts links.\n"
        "🗑️ Temporary processing only; no database or permanent file storage.\n\n"
        "Use /help for instructions."
    )

def download_video(url: str, folder: Path) -> Path:
    opts = {
        "outtmpl": str(folder / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "merge_output_format": "mp4",
        "format": "best[ext=mp4][height<=1080]/best[height<=1080]/best",
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    candidates = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}
    ]
    if not candidates:
        raise RuntimeError("No video file was produced.")
    video = max(candidates, key=lambda p: p.stat().st_mtime)
    if video.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("FILE_TOO_LARGE")
    return video

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 <b>Welcome to {BOT_NAME}!</b>\n\nSend a public YouTube Shorts link to get started.",
        parse_mode="HTML",
        reply_markup=menu(),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(help_text(), parse_mode="HTML", reply_markup=menu())

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(about_text(), parse_mode="HTML", reply_markup=menu())

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = context.user_data.get("download_task")
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("🛑 Cancellation requested.", reply_markup=menu())
    else:
        await update.message.reply_text("Nothing is downloading right now.", reply_markup=menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "download":
        await query.edit_message_text(
            "🎬 <b>Send a public YouTube Shorts URL.</b>\nUse /cancel to cancel.",
            parse_mode="HTML",
        )
    elif query.data == "help":
        await query.edit_message_text(help_text(), parse_mode="HTML", reply_markup=menu())
    elif query.data == "about":
        await query.edit_message_text(about_text(), parse_mode="HTML", reply_markup=menu())

async def process_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    url = message.text.strip()

    if not YOUTUBE_RE.match(url):
        await message.reply_text("❌ Please send a valid YouTube URL.", reply_markup=menu())
        return
    if not SHORTS_RE.search(url):
        await message.reply_text(
            "⚠️ This version supports Shorts URLs only.\n"
            "Example: https://youtube.com/shorts/VIDEO_ID",
            reply_markup=menu(),
        )
        return

    current_task = context.user_data.get("download_task")
    if current_task and not current_task.done():
        await message.reply_text("⏳ You already have a download running. Use /cancel first.")
        return

    status = await message.reply_text("⏳ <b>Processing your Short...</b>", parse_mode="HTML")
    temp_dir = Path(tempfile.mkdtemp(prefix="ytshorts_"))

    async def runner():
        try:
            await message.chat.send_action(ChatAction.UPLOAD_VIDEO)
            video = await asyncio.wait_for(
                asyncio.to_thread(download_video, url, temp_dir),
                timeout=DOWNLOAD_TIMEOUT,
            )
            await status.edit_text("📤 <b>Uploading video to Telegram...</b>", parse_mode="HTML")
            with video.open("rb") as video_file:
                await message.reply_video(
                    video=video_file,
                    supports_streaming=True,
                    caption="🎬 Downloaded with YT Shorts Downloader",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=30,
                    pool_timeout=30,
                )
            await status.delete()
        except asyncio.CancelledError:
            try:
                await status.edit_text("🛑 Cancelled. Temporary files will be removed.")
            except Exception:
                pass
            raise
        except asyncio.TimeoutError:
            await status.edit_text("⏱️ Timed out. Please try another public Short.", reply_markup=menu())
        except yt_dlp.utils.DownloadError as exc:
            logger.warning("Download failed: %s", exc)
            await status.edit_text(
                "❌ Couldn't download this Short. It may be private, unavailable, restricted, or temporarily inaccessible.",
                reply_markup=menu(),
            )
        except ValueError as exc:
            text = (
                "📦 This video is too large to send through this bot."
                if str(exc) == "FILE_TOO_LARGE"
                else "❌ The video couldn't be processed."
            )
            await status.edit_text(text, reply_markup=menu())
        except Exception:
            logger.exception("Unexpected processing error")
            try:
                await status.edit_text("❌ Something went wrong. Please try again later.", reply_markup=menu())
            except Exception:
                pass
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            context.user_data.pop("download_task", None)

    task = asyncio.create_task(runner())
    context.user_data["download_task"] = task

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        await process_download(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled bot error", exc_info=context.error)

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Set it in Render Environment Variables.")
    start_health_server()
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_error_handler(error_handler)
    logger.info("Bot starting with polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
