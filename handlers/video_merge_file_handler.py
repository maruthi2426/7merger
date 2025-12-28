"""Handle file uploads for video merge operations."""
import logging
import os
from telegram import Update
from telegram.ext import ContextTypes
from utils.file_manager import FileManager
from handlers.video_merge_manager import (
    get_or_create_queue,
    VideoMetadata,
    show_merge_menu,
)

logger = logging.getLogger(__name__)
file_manager = FileManager()


async def handle_merge_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, file_path: str) -> None:
    """Handle video file upload for merge queue."""
    user_id = update.effective_user.id
    queue = get_or_create_queue(user_id)
    
    try:
        # Get file info
        file_info = update.message.video or update.message.document
        file_name = file_info.file_name or f"video_{len(queue.videos) + 1}.mp4"
        
        for existing_video in queue.videos:
            if existing_video.file_name.lower() == file_name.lower():
                await update.message.reply_text(
                    "⚠️ DUPLICATE FILENAME DETECTED!\n\n"
                    f"❌ A file named '{file_name}' is already queued.\n\n"
                    "📝 Solution:\n"
                    "• Rename the file before uploading\n"
                    "• Send a different video file\n\n"
                    f"📂 Current queue: {len(queue.videos)} videos"
                )
                file_manager.delete_file(file_path)
                logger.warning(f"User {user_id} tried to add duplicate filename: {file_name}")
                return
        
        # Create metadata
        metadata = VideoMetadata(
            msg_id=update.message.message_id,
            file_name=file_name,
            file_path=file_path
        )
        
        # Validate video
        if metadata.duration == 0:
            await update.message.reply_text(
                "❌ Invalid video file or unable to detect duration.\n\n"
                "Please send a valid video file."
            )
            file_manager.delete_file(file_path)
            return
        
        if len(queue.videos) >= 20:
            await update.message.reply_text(
                "❌ Queue is full!\n\n"
                "Maximum 20 videos per merge.\n"
                "Click 🧹 Clear Queue to start over."
            )
            file_manager.delete_file(file_path)
            logger.warning(f"User {user_id} tried to add video but queue full (has {len(queue.videos)})")
            return
        
        for existing_video in queue.videos:
            if existing_video.file_id == metadata.file_id:
                await update.message.reply_text(
                    "⚠️ DUPLICATE VIDEO DETECTED!\n\n"
                    f"❌ This exact video is already in the queue.\n\n"
                    "📝 Solution:\n"
                    "• Please send a different video file\n\n"
                    f"📂 Current queue: {len(queue.videos)} videos"
                )
                file_manager.delete_file(file_path)
                logger.warning(f"User {user_id} tried to add duplicate file_id: {file_name}")
                return
        
        # Add to queue
        if queue.add_video(metadata):
            await update.message.reply_text(
                f"✅ Video {len(queue.videos)} added!\n\n"
                f"📁 File: {file_name}\n"
                f"⏱️ Duration: {VideoMetadata._format_duration(metadata.duration)}\n"
                f"📊 Size: {metadata.size / (1024*1024):.1f} MB\n"
                f"🎬 Resolution: {metadata.resolution[0]}x{metadata.resolution[1]}\n\n"
                f"📂 Queue: {len(queue.videos)} videos\n"
                f"💾 Total: {queue.get_total_size():.2f} GB"
            )
            
            # Show updated merge menu
            await show_merge_menu(update, context, edit=False)
        else:
            await update.message.reply_text(
                "❌ Could not add video to queue.\n"
                "Please try again."
            )
            file_manager.delete_file(file_path)
            logger.error(f"Unexpected: add_video failed for {file_name} even after pre-checks")
    
    except Exception as e:
        logger.error(f"Error handling merge video upload: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        file_manager.delete_file(file_path)
