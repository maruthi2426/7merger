"""Handle file uploads including rclone config file detection."""
import logging
import os
import asyncio  # ✅ ADDED (required for sleep)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.file_manager import FileManager
from utils.ffmpeg_processor import FFmpegProcessor
from handlers.media_processor import (
    process_extract, process_trim, 
    process_convert, process_compress, process_remove_stream,
    process_swap_audio, process_combine, process_watermark, 
    process_subtitle
)
from handlers.video_merge_processor import process_merge_video

logger = logging.getLogger(__name__)
file_manager = FileManager()
processor = FFmpegProcessor()

async def download_file_with_fallback(context: ContextTypes.DEFAULT_TYPE, file, filepath: str, user_id: int, update: Update = None) -> bool:
    """
    Download file with intelligent fallback to Pyrogram for large files.
    
    Bot API getFile has 50MB hard limit enforced by Telegram servers.
    For files > 50MB, automatically switch to Pyrogram MTProto protocol (supports up to 2GB).
    """
    try:
        BOT_API_LIMIT = 50 * 1024 * 1024
        file_size = getattr(file, "file_size", 0)

        logger.info(f"[v0] Download request - file_size: {file_size / (1024*1024):.2f}MB (Bot API limit: 50MB)")

        # =========================
        # PYROGRAM FALLBACK
        # =========================
        if file_size > BOT_API_LIMIT and update:
            logger.warning(f"[v0] File size exceeds Bot API limit - Using Pyrogram MTProto")

            try:
                from handlers.pyrogram_setup import (
                    get_or_create_pyrogram_client,
                    download_file_via_pyrogram
                )

                # ✅ Get cached & already-started client
                pyrogram_client = await get_or_create_pyrogram_client(str(user_id))
                if not pyrogram_client:
                    raise Exception("Failed to initialize Pyrogram client")

                # ❌ DO NOT RESTART CLIENT HERE
                # ✅ Force session ready & time sync
                await pyrogram_client.get_me()
                await asyncio.sleep(1.5)

                chat_id = update.effective_chat.id
                message_id = update.message.message_id

                success = await download_file_via_pyrogram(
                    pyrogram_client,
                    chat_id,
                    message_id,
                    filepath
                )

                logger.info(f"[v0] Pyrogram download completed (client kept alive)")

                if success:
                    return True
                else:
                    raise Exception("Pyrogram download failed")

            except Exception as pyrogram_error:
                logger.error(f"[v0] Pyrogram method failed: {pyrogram_error}", exc_info=True)
                return False

        # =========================
        # BOT API DOWNLOAD
        # =========================
        if file_size <= BOT_API_LIMIT:
            logger.info(f"[v0] Using Bot API download")
            try:
                file_obj = await context.bot.get_file(file.file_id)
                await file_obj.download_to_drive(filepath)
                return True
            except Exception as bot_api_error:
                logger.error(f"[v0] Bot API download failed: {bot_api_error}")

        return False

    except Exception as e:
        logger.error(f"[v0] Unexpected download error: {e}", exc_info=True)
        return False


async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all file uploads and process based on operation."""
    try:
        user_id = update.effective_user.id

        # =========================
        # RCLONE CONFIG
        # =========================
        if context.user_data.get("awaiting_rclone_config"):
            file = update.message.document
            if not file:
                await update.message.reply_text("❌ Please send a document file")
                return

            filename = file.file_name or "rclone.conf"
            if not filename.endswith(".conf"):
                await update.message.reply_text("❌ Only rclone.conf allowed")
                return

            user_dir = f"./userdata/{user_id}"
            os.makedirs(user_dir, exist_ok=True)
            conf_path = os.path.join(user_dir, "rclone.conf")

            success = await download_file_with_fallback(context, file, conf_path, user_id, update)
            if not success:
                await update.message.reply_text("❌ Failed to download rclone.conf")
                return

            with open(conf_path, "r") as f:
                content = f.read()
                if "[" not in content or "]" not in content:
                    os.remove(conf_path)
                    await update.message.reply_text("❌ Invalid rclone config")
                    return

            context.user_data["upload_mode"] = {"engine": "rclone", "configured": True}
            context.user_data.pop("awaiting_rclone_config", None)

            from keyboards.main_keyboard import get_main_keyboard
            await update.message.reply_text(
                "✅ RCLONE CONFIGURED\n\nSelect a category:",
                reply_markup=get_main_keyboard(context.user_data.get("upload_mode"))
            )
            return

        # =========================
        # OPERATION REQUIRED
        # =========================
        operation = context.user_data.get("operation")
        if not operation:
            await update.message.reply_text("❌ No operation selected")
            return

        file = update.message.document or update.message.video or update.message.audio
        if not file:
            return

        filename = file.file_name or f"file_{file.file_id[:8]}"
        filepath = os.path.join(file_manager.TEMP_FOLDER, filename)
        file_manager.create_temp_folder()

        # =========================
        # MERGE
        # =========================
        if operation in ["merge", "merge_add"]:
            success = await download_file_with_fallback(context, file, filepath, user_id, update)
            if not success:
                await update.message.reply_text("❌ Download failed")
                return
            await process_merge_video(update, context, filepath)
            return

        # =========================
        # OTHER OPERATIONS
        # =========================
        success = await download_file_with_fallback(context, file, filepath, user_id, update)
        if not success:
            await update.message.reply_text("❌ Download failed")
            return

        if operation == "extract":
            await process_extract(update, context, filepath)
        elif operation == "trim":
            await process_trim(update, context, filepath)
        elif operation == "convert":
            await process_convert(update, context, filepath)
        elif operation == "compress":
            await process_compress(update, context, filepath)
        elif operation == "remove_stream":
            await process_remove_stream(update, context, filepath)
        elif operation == "swap_audio":
            await process_swap_audio(update, context, filepath)
        elif operation == "combine":
            await process_combine(update, context, filepath)
        elif operation == "watermark":
            await process_watermark(update, context, filepath)
        elif operation == "subtitle":
            await process_subtitle(update, context, filepath)

    except Exception as e:
        logger.error(f"Error handling file: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {e}")
