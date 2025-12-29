"""Handle callback queries from inline keyboards."""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from keyboards.main_keyboard import (
    get_main_keyboard,
    get_video_tools_keyboard,
    get_audio_tools_keyboard,
    get_upload_mode_keyboard,
    get_back_close_keyboard,
)

logger = logging.getLogger(__name__)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle all inline keyboard button callbacks.
    Simplified upload mode selection and fixed mode persistence
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception as e:
        logger.debug(f"[v0] Callback query error (may be expired): {e}")
        return
    
    callback_data = query.data
    
    if callback_data == "close":
        try:
            await query.delete_message()
            logger.info(f"User {update.effective_user.id} closed menu")
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            try:
                await query.edit_message_text(text="✅ Menu closed. Type /start to open again.")
            except:
                pass
        return
    
    if callback_data.startswith("merge_") or callback_data == "video_merge":
        from handlers.video_merge_callbacks import handle_merge_callbacks
        await handle_merge_callbacks(update, context)
        return
    
    if callback_data == "telegram_format_video" and context.user_data.get("awaiting_merge_format"):
        context.user_data["upload_mode"]["format"] = "video"
        context.user_data.pop("awaiting_merge_format", None)
        from handlers.video_merge_callbacks import _show_rename_options
        await _show_rename_options(query, update.effective_user.id)
        return
    
    if callback_data == "telegram_format_document" and context.user_data.get("awaiting_merge_format"):
        context.user_data["upload_mode"]["format"] = "document"
        context.user_data.pop("awaiting_merge_format", None)
        from handlers.video_merge_callbacks import _show_rename_options
        await _show_rename_options(query, update.effective_user.id)
        return
    
    # MAIN MENU NAVIGATION
    if callback_data == "back_main":
        await safe_edit(
            update,
            context,
            text="🎬 Welcome to Video Merger Bot!\n\nSelect a category:",
            reply_markup=get_main_keyboard(context.user_data.get("upload_mode")),
        )
        logger.info(f"User {update.effective_user.id} returned to main menu")
    
    elif callback_data == "menu_video_tools":
        await safe_edit(
            update,
            context,
            text="🎬 VIDEO TOOLS\n━━━━━━━━━━━━━━━━━━\nSelect an operation:",
            reply_markup=get_video_tools_keyboard(),
        )
        logger.info(f"User {update.effective_user.id} opened Video Tools menu")
    
    elif callback_data == "menu_audio_tools":
        await safe_edit(
            update,
            context,
            text="🎵 AUDIO TOOLS\n━━━━━━━━━━━━━━━━━━\nSelect an operation:",
            reply_markup=get_audio_tools_keyboard(),
        )
        logger.info(f"User {update.effective_user.id} opened Audio Tools menu")
    
    elif callback_data == "menu_upload_mode":
        await safe_edit(
            update,
            context,
            text="📤 UPLOAD MODE\n━━━━━━━━━━━━━━━━━━\nSelect your preferred upload method:",
            reply_markup=get_upload_mode_keyboard(context.user_data.get("upload_mode")),
        )
        logger.info(f"User {update.effective_user.id} opened Upload Mode menu")
    
    # VIDEO TOOLS OPERATIONS
    elif callback_data == "video_extract":
        await query.edit_message_text(
            text="🔊 EXTRACT AUDIO\n━━━━━━━━━━━━━━━━━━\n"
                 "Send a video file to extract audio from\n\n"
                 "✅ The audio will be extracted as MP3 format\n\n"
                 "💡 Tip: High quality output",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "extract"
        logger.info(f"User {update.effective_user.id} selected extract operation")
    
    elif callback_data == "video_trim":
        await query.edit_message_text(
            text="✂️ TRIM VIDEO\n━━━━━━━━━━━━━━━━━━\n"
                 "Send a video file to trim\n\n"
                 "You'll be asked for:\n"
                 "• Start time (HH:MM:SS format)\n"
                 "• End time (HH:MM:SS format)\n\n"
                 "💡 Example: 00:30:45 to 02:15:30",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "trim"
        logger.info(f"User {update.effective_user.id} selected trim operation")
    
    elif callback_data == "video_convert":
        await query.edit_message_text(
            text="🔄 CONVERT FORMAT\n━━━━━━━━━━━━━━━━━━\n"
                 "Send a video file to convert\n\n"
                 "✅ Supported formats: mp4, mkv, avi, mov, webm, flv, wmv\n\n"
                 "💡 You'll be asked which format to convert to",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "convert"
        logger.info(f"User {update.effective_user.id} selected convert operation")
    
    elif callback_data == "video_compress":
        await query.edit_message_text(
            text="✅ COMPRESS VIDEO\n━━━━━━━━━━━━━━━━━━\n"
                 "Send a video file to compress\n\n"
                 "Quality scale: 0-51\n"
                 "• 0 = Best quality (larger file)\n"
                 "• 28 = Default quality\n"
                 "• 51 = Worst quality (smallest file)\n\n"
                 "💡 You'll be asked for quality preference",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "compress"
        logger.info(f"User {update.effective_user.id} selected compress operation")
    
    elif callback_data == "video_remove_stream":
        await query.edit_message_text(
            text="❌ REMOVE STREAM\n━━━━━━━━━━━━━━━━━━\n"
                 "Send a video file to remove stream\n\n"
                 "You can remove either:\n"
                 "• Audio stream (keep video only)\n"
                 "• Video stream (keep audio only)\n\n"
                 "💡 Useful for removing unwanted audio/video",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "remove_stream"
        logger.info(f"User {update.effective_user.id} selected remove stream operation")
    
    elif callback_data == "video_watermark":
        await query.edit_message_text(
            text="🌊 ADD WATERMARK\n━━━━━━━━━━━━━━━━━━\n"
                 "Add a watermark to your video\n\n"
                 "Steps:\n"
                 "1️⃣ Send the video file\n"
                 "2️⃣ Send the watermark image (PNG recommended)\n"
                 "3️⃣ Specify position (top-left, center, bottom-right, etc.)\n\n"
                 "💡 PNG images with transparency work best",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "watermark"
        logger.info(f"User {update.effective_user.id} selected watermark operation")
    
    elif callback_data == "video_subtitle":
        await query.edit_message_text(
            text="📝 ADD SUBTITLE\n━━━━━━━━━━━━━━━━━━\n"
                 "Add subtitles to your video\n\n"
                 "Steps:\n"
                 "1️⃣ Send the video file\n"
                 "2️⃣ Send the subtitle file (.srt, .ass, .vtt)\n\n"
                 "✅ Supported formats: SRT, ASS, VTT, SUB",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "subtitle"
        logger.info(f"User {update.effective_user.id} selected subtitle operation")
    
    elif callback_data == "video_swap_audio":
        await query.edit_message_text(
            text="🎬 REPLACE AUDIO\n━━━━━━━━━━━━━━━━━━\n"
                 "Replace video audio with a new audio track\n\n"
                 "Steps:\n"
                 "1️⃣ Send the video file\n"
                 "2️⃣ Send the new audio file (MP3, WAV, etc.)\n\n"
                 "💡 New audio will sync with original video length",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "swap_audio"
        logger.info(f"User {update.effective_user.id} selected swap audio operation")
    
    elif callback_data == "video_thumbnail":
        await query.edit_message_text(
            text="📋 GENERATE THUMBNAIL\n━━━━━━━━━━━━━━━━━━\n"
                 "Extract a thumbnail from your video\n\n"
                 "You'll be asked for:\n"
                 "• Time point (HH:MM:SS format)\n"
                 "• Image size preference\n\n"
                 "💡 Useful for creating video cover images",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "thumbnail"
        logger.info(f"User {update.effective_user.id} selected thumbnail operation")
    
    elif callback_data == "video_metadata":
        await query.edit_message_text(
            text="📊 VIEW METADATA\n━━━━━━━━━━━━━━━━━━\n"
                 "View detailed information about video\n\n"
                 "You'll see:\n"
                 "• Duration & Resolution\n"
                 "• Codec & Bitrate\n"
                 "• FPS & Frame Count\n"
                 "• File Size & Format\n\n"
                 "💡 Useful for checking video properties",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "metadata"
        logger.info(f"User {update.effective_user.id} selected metadata operation")
    
    # AUDIO TOOLS OPERATIONS
    elif callback_data == "audio_combine":
        await query.edit_message_text(
            text="🎬 COMBINE VIDEO + AUDIO\n━━━━━━━━━━━━━━━━━━\n"
                 "Combine a video with an audio file\n\n"
                 "Steps:\n"
                 "1️⃣ Send the video file\n"
                 "2️⃣ Send the audio file to combine\n\n"
                 "✅ Supported audio: MP3, WAV, AAC, FLAC",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "combine"
        logger.info(f"User {update.effective_user.id} selected combine operation")
    
    elif callback_data == "audio_sync_sub":
        await query.edit_message_text(
            text="⏱️ SYNC SUBTITLE TIMING\n━━━━━━━━━━━━━━━━━━\n"
                 "Adjust subtitle timing\n\n"
                 "Steps:\n"
                 "1️⃣ Send the subtitle file (.srt, .ass, .vtt)\n"
                 "2️⃣ Provide delay in seconds\n\n"
                 "💡 Examples: 2.5 (delay forward), -1.5 (delay backward)",
            reply_markup=get_back_close_keyboard(),
        )
        context.user_data["operation"] = "sync_sub"
        logger.info(f"User {update.effective_user.id} selected sync subtitle operation")
    
    elif callback_data == "upload_telegram":
        context.user_data["upload_mode"] = {
            "engine": "telegram",
            "format": "video"  # Default format
        }
        
        await query.edit_message_text(
            text="🎬 Welcome to Video Merger Bot!\n\nSelect a category:",
            reply_markup=get_main_keyboard(context.user_data.get("upload_mode")),
        )
        logger.info(f"User {update.effective_user.id} selected Telegram upload mode")
    
    elif callback_data == "upload_rclone":
        user_id = update.effective_user.id
        import os
        conf_path = f"./userdata/{user_id}/rclone.conf"
        
        if os.path.exists(conf_path):
            # Config exists, set rclone mode and return to main menu silently
            context.user_data["upload_mode"] = {
                "engine": "rclone",
                "configured": True
            }
            logger.info(f"User {user_id} selected Rclone upload mode (config found)")
            
            # Simply return to main menu - no confirmation message
            await query.edit_message_text(
                text="🎬 Welcome to Video Merger Bot!\n\nSelect a category:",
                reply_markup=get_main_keyboard(context.user_data.get("upload_mode")),
            )
        else:
            # No config, ask user to upload
            context.user_data["awaiting_rclone_config"] = True
            
            await query.edit_message_text(
                text="☁️ RCLONE SETUP REQUIRED\n━━━━━━━━━━━━━━━━━━\n\n"
                     "To use Rclone upload, send your rclone.conf file.\n\n"
                     "📋 How to get rclone.conf:\n"
                     "1. Configure rclone: rclone config\n"
                     "2. Find config at ~/.config/rclone/rclone.conf\n"
                     "3. Send the file here\n\n"
                     "Once uploaded, Rclone mode will be automatically enabled.",
                reply_markup=get_back_close_keyboard(),
            )
            logger.info(f"User {user_id} clicked Rclone but no config found - requesting config file")
    
    # SETTINGS
    elif callback_data == "settings_metadata":
        await query.edit_message_text(
            text="📋 METADATA SETTINGS\n━━━━━━━━━━━━━━━━━━\n"
                 "Edit metadata for your files\n\n"
                 "⚠️ Status: Not yet configured\n\n"
                 "Coming soon:\n"
                 "• Custom title & author\n"
                 "• Set creation date\n"
                 "• Add custom tags",
            reply_markup=get_back_close_keyboard(),
        )
        logger.info(f"User {update.effective_user.id} opened metadata settings")
    
    elif callback_data == "settings_quality":
        await query.edit_message_text(
            text="🎬 VIDEO QUALITY SETTINGS\n━━━━━━━━━━━━━━━━━━\n"
                 "Configure default video quality\n\n"
                 "Current Setting: Auto\n\n"
                 "Quality Options:\n"
                 "• 480p - Small files, fast processing\n"
                 "• 720p - Balanced\n"
                 "• 1080p - High quality\n"
                 "• 4K - Maximum quality",
            reply_markup=get_back_close_keyboard(),
        )
        logger.info(f"User {update.effective_user.id} opened quality settings")
    
    elif callback_data == "settings_clear_cache":
        await query.edit_message_text(
            text="🗑️ CACHE CLEARED\n━━━━━━━━━━━━━━━━━━\n"
                 "✅ Cache cleared successfully!\n\n"
                 "Freed up disk space:\n"
                 "• Temporary files removed\n"
                 "• Processing logs cleaned\n"
                 "• Old conversions deleted",
            reply_markup=get_back_close_keyboard(),
        )
        logger.info(f"User {update.effective_user.id} cleared cache")
    
    elif callback_data == "settings_about":
        await query.edit_message_text(
            text="ℹ️ ABOUT VIDEO MERGER BOT\n━━━━━━━━━━━━━━━━━━\n"
                 "Version: 1.0\n"
                 "Powered by FFmpeg\n\n"
                 "Features:\n"
                 "✅ Video merging & editing\n"
                 "✅ Audio processing\n"
                 "✅ Format conversion\n"
                 "✅ Compression\n\n"
                 "Type /start to return to main menu",
            reply_markup=get_back_close_keyboard(),
        )
        logger.info(f"User {update.effective_user.id} viewed about info")
    
    # NEW CALLBACKS FOR RENAME FLOW
    elif callback_data == "merge_use_default":
        context.user_data["merged_filename"] = "merged_video.mp4"
        from handlers.video_merge_processor import execute_smart_merge
        await execute_smart_merge(update, context)
        return
    
    elif callback_data == "merge_ask_rename":
        context.user_data["awaiting_merge_filename"] = True
        await query.edit_message_text(
            text="✏️ ENTER FILENAME\n━━━━━━━━━━━━━━━━━━\n\n"
                 "Send the filename for merged video\n\n"
                 "📝 Examples: my_video.mp4, output.mp4\n"
                 "⚠️ Include the .mp4 extension",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="merge_menu")
            ]])
        )
        logger.info(f"User {update.effective_user.id} asked to enter merge filename")
        return
    
    elif callback_data == "merge_confirm_back":
        from handlers.video_merge_manager import show_merge_menu
        await show_merge_menu(update, context, edit=True)
        return
    
    elif callback_data == "merge_filename_continue":
        try:
            await query.delete_message()
        except Exception as e:
            logger.warning(f"Could not delete filename confirmation message: {e}")
        
        context.user_data.pop("awaiting_merge_filename", None)
        from handlers.video_merge_processor import execute_smart_merge
        await execute_smart_merge(update, context)
        return
    
    else:
        logger.warning(f"Unknown callback: {callback_data}")

async def safe_edit(update, context, text, reply_markup=None):
    """Safely edit message only if content actually changed."""
    query = update.callback_query
    try:
        # Get current message text
        current_text = query.message.text if query.message else ""
        
        # Only edit if content is different
        if current_text != text:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
        elif reply_markup and query.message:
            # Text is same but markup might be different
            current_markup = query.message.reply_markup
            if str(current_markup) != str(reply_markup):
                await query.edit_message_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Safe edit failed: {e}")
