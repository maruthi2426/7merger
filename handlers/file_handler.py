"""Handle file uploads including rclone config file detection."""
import logging
import os
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

started_clients = {}

async def download_file_with_fallback(context: ContextTypes.DEFAULT_TYPE, file, filepath: str, user_id: int, update: Update = None) -> bool:
    """
    Download file with intelligent fallback to Pyrogram for large files.
    
    Bot API getFile has 50MB hard limit enforced by Telegram servers.
    For files > 50MB, automatically switch to Pyrogram MTProto protocol (supports up to 2GB).
    
    Args:
        context: Telegram context
        file: File object from update.message
        filepath: Local path to save file
        user_id: User ID
        update: Update object (required for Pyrogram fallback)
    
    Returns:
        True if download successful, False otherwise
    """
    try:
        BOT_API_LIMIT = 50 * 1024 * 1024  # 50MB hard limit
        file_size = getattr(file, "file_size", 0)
        
        logger.info(f"[v0] Download request - file_size: {file_size / (1024*1024):.2f}MB (Bot API limit: 50MB)")
        
        if file_size > BOT_API_LIMIT and update:
            logger.warning(f"[v0] File size {file_size / (1024*1024):.2f}MB exceeds Bot API limit - Using Pyrogram MTProto")
            
            try:
                from handlers.pyrogram_setup import get_pyrogram_client, download_file_via_pyrogram
                
                pyrogram_client = await get_pyrogram_client()
                if not pyrogram_client:
                    raise Exception("Failed to initialize global Pyrogram client")
                
                logger.info(f"[v0] Using global Pyrogram client (already started and time synced)")
                
                # Get chat and message info
                chat_id = update.effective_chat.id
                message_id = update.message.message_id
                
                success = await download_file_via_pyrogram(
                    pyrogram_client,
                    chat_id,
                    message_id,
                    filepath
                )
                
                if success:
                    logger.info(f"[v0] Pyrogram download successful, keeping client alive for reuse")
                    return True
                else:
                    raise Exception("Pyrogram download failed")
            
            except Exception as pyrogram_error:
                logger.error(f"[v0] Pyrogram method failed: {pyrogram_error}")
                return False
        
        if file_size <= BOT_API_LIMIT:
            logger.info(f"[v0] File size {file_size / (1024*1024):.2f}MB - Using Bot API")
            try:
                file_obj = await context.bot.get_file(file.file_id)
                await file_obj.download_to_drive(filepath)
                logger.info(f"[v0] Bot API download successful: {filepath}")
                return True
            except Exception as bot_api_error:
                logger.error(f"[v0] Bot API download failed: {bot_api_error}")
                
                # If Bot API fails, try Pyrogram as last resort
                if update and file_size > 10 * 1024 * 1024:  # Only for moderately large files
                    logger.warning(f"[v0] Bot API failed, attempting Pyrogram fallback")
                    try:
                        from handlers.pyrogram_setup import get_pyrogram_client, download_file_via_pyrogram
                        
                        pyrogram_client = await get_pyrogram_client()
                        
                        if not pyrogram_client:
                            raise Exception("Failed to initialize Pyrogram client")
                        
                        chat_id = update.effective_chat.id
                        message_id = update.message.message_id
                        
                        success = await download_file_via_pyrogram(
                            pyrogram_client,
                            chat_id,
                            message_id,
                            filepath
                        )
                        
                        return success
                    except Exception as fallback_error:
                        logger.error(f"[v0] Pyrogram fallback also failed: {fallback_error}")
                        return False
                return False
        
        # If file size is unknown (0), try Bot API first
        if file_size == 0:
            logger.info(f"[v0] File size unknown - attempting Bot API")
            try:
                file_obj = await context.bot.get_file(file.file_id)
                await file_obj.download_to_drive(filepath)
                logger.info(f"[v0] Unknown size file downloaded via Bot API: {filepath}")
                return True
            except Exception as e:
                logger.error(f"[v0] Bot API failed for unknown size file: {e}")
                return False
        
        return False
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[v0] Unexpected download error: {error_msg}", exc_info=True)
        return False

async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all file uploads and process based on operation."""
    try:
        user_id = update.effective_user.id
        
        if context.user_data.get("awaiting_rclone_config"):
            file = update.message.document
            if not file:
                await update.message.reply_text(
                    "❌ Please send a file (document format only)",
                    reply_to_message_id=update.message.message_id
                )
                return
            
            filename = file.file_name or "rclone.conf"
            
            # Only accept .conf files
            if not filename.endswith(".conf"):
                await update.message.reply_text(
                    "❌ Invalid file! Please send the rclone.conf file only",
                    reply_to_message_id=update.message.message_id
                )
                return
            
            # Create userdata directory
            user_dir = f"./userdata/{user_id}"
            os.makedirs(user_dir, exist_ok=True)
            
            # Save the config file
            conf_path = os.path.join(user_dir, "rclone.conf")
            
            success = await download_file_with_fallback(context, file, conf_path, user_id, update)
            if not success:
                await update.message.reply_text(
                    "❌ Failed to download rclone.conf file",
                    reply_to_message_id=update.message.message_id
                )
                return
            
            # Validate rclone config
            try:
                with open(conf_path, 'r') as f:
                    content = f.read()
                    if '[' not in content or ']' not in content:
                        raise ValueError("Invalid rclone config format")
                
                context.user_data["upload_mode"] = {
                    "engine": "rclone",
                    "configured": True
                }
                context.user_data.pop("awaiting_rclone_config", None)
                
                logger.info(f"User {user_id} successfully uploaded rclone.conf")
                
                try:
                    await update.message.reply_to_message.delete()
                except Exception as e:
                    logger.warning(f"Could not delete rclone setup message: {e}")
                
                try:
                    await update.message.delete()
                except Exception as e:
                    logger.warning(f"Could not delete rclone file message: {e}")
                
                from keyboards.main_keyboard import get_main_keyboard
                
                await update.message.reply_text(
                    text="✅ RCLONE CONFIGURED\n━━━━━━━━━━━━━━━━━━\n\n"
                         "📋 rclone.conf: Successfully added\n\n"
                         "🎬 Welcome to Video Merger Bot!\n\nSelect a category:",
                    reply_markup=get_main_keyboard(context.user_data.get("upload_mode"))
                )
                return
            except Exception as e:
                logger.error(f"Invalid rclone config from user {user_id}: {e}")
                await update.message.reply_text(
                    f"❌ Invalid rclone config file!\n\n"
                    f"Error: {str(e)}\n\n"
                    f"Please send a valid rclone.conf file",
                    reply_to_message_id=update.message.message_id
                )
                os.remove(conf_path)
                return
        
        if context.user_data.get("awaiting_merge_filename"):
            filename_text = update.message.text
            
            if not filename_text:
                await update.message.reply_text(
                    "❌ Please send a valid filename",
                    reply_to_message_id=update.message.message_id
                )
                return
            
            # Validate and normalize filename
            filename_text = filename_text.strip()
            
            # Ensure .mp4 extension
            if not filename_text.lower().endswith('.mp4'):
                filename_text = filename_text + '.mp4'
            
            # Remove invalid characters
            invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
            for char in invalid_chars:
                filename_text = filename_text.replace(char, '')
            
            context.user_data["merged_filename"] = filename_text
            context.user_data.pop("awaiting_merge_filename", None)
            
            try:
                await update.message.reply_to_message.delete()
            except Exception as e:
                logger.warning(f"Could not delete asking message: {e}")
            
            try:
                await update.message.delete()
            except Exception as e:
                logger.warning(f"Could not delete filename message: {e}")
            
            # Show continue button as fresh message
            await update.message.reply_text(
                text=f"✅ FILENAME SET\n━━━━━━━━━━━━━━━━━━\n\n"
                     f"📁 Filename: {filename_text}\n\n"
                     f"Ready to merge!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("▶️ Continue", callback_data="merge_filename_continue"),
                    InlineKeyboardButton("❌ Cancel", callback_data="merge_menu")
                ]])
            )
            return
        
        operation = context.user_data.get("operation")
        
        if not operation:
            await update.message.reply_text(
                "❌ No operation selected. Use /start to choose an operation",
                reply_to_message_id=update.message.message_id
            )
            return
        
        file = update.message.document or update.message.video or update.message.audio
        if not file:
            return
        
        filename = file.file_name or f"file_{file.file_id[:8]}"
        filepath = os.path.join(file_manager.TEMP_FOLDER, filename)
        
        # Create temp folder
        file_manager.create_temp_folder()
        
        if operation in ["merge", "merge_add"]:
            download_msg = await update.message.reply_text(
                "📥 Downloading video...\n"
                "Progress: 0%",
                reply_to_message_id=update.message.message_id
            )
            
            success = await download_file_with_fallback(context, file, filepath, user_id, update)
            try:
                await download_msg.delete()
            except:
                pass
            
            if not success:
                await update.message.reply_text(
                    "❌ Failed to download video file. Please try again.",
                    reply_to_message_id=update.message.message_id
                )
                return
            
            await process_merge_video(update, context, filepath)
        else:
            success = await download_file_with_fallback(context, file, filepath, user_id, update)
            if not success:
                await update.message.reply_text(
                    "❌ Failed to download file. Please try again.",
                    reply_to_message_id=update.message.message_id
                )
                return
            
            file_size = file_manager.get_file_size(filepath) / (1024*1024)
            await update.message.reply_text(
                f"📥 Downloaded: {filename} ({file_size:.2f} MB)",
                reply_to_message_id=update.message.message_id
            )
            
            if "files" not in context.user_data:
                context.user_data["files"] = []
            context.user_data["files"].append(filepath)
            
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
        await update.message.reply_text(
            f"❌ Error: {str(e)}",
            reply_to_message_id=update.message.message_id
        )
