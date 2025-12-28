"""Process and execute video merges with real-time progress."""
import logging
import os
import asyncio
import time
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.file_manager import FileManager
from utils.ffmpeg_processor import FFmpegProcessor
from handlers.video_merge_manager import get_or_create_queue

logger = logging.getLogger(__name__)
file_manager = FileManager()
processor = FFmpegProcessor()

try:
    from pyrogram import Client
    PYROGRAM_AVAILABLE = True
except ImportError:
    PYROGRAM_AVAILABLE = False
    logger.warning("Pyrogram not installed. Large file uploads will use Telegram Bot API (limited to ~50MB)")

async def process_merge_video(update: Update, context: ContextTypes.DEFAULT_TYPE, filepath: str) -> None:
    """Handle video addition to merge queue - ONLY updates queue message, no extra messages."""
    try:
        user_id = update.effective_user.id
        queue = get_or_create_queue(user_id)
        
        if not os.path.exists(filepath):
            await update.message.reply_text(
                "❌ File not found",
                reply_to_message_id=update.message.message_id
            )
            context.user_data["operation"] = None
            return
        
        # Extract metadata
        from handlers.video_merge_manager import VideoMetadata
        
        try:
            metadata = VideoMetadata(
                msg_id=update.message.message_id,
                file_name=os.path.basename(filepath),
                file_path=filepath
            )
        except Exception as e:
            logger.error(f"Error extracting metadata: {e}")
            await update.message.reply_text(
                f"❌ Cannot read video file: {str(e)}"
            )
            file_manager.delete_file(filepath)
            context.user_data["operation"] = None
            return
        
        # Add to queue
        if queue.add_video(metadata):
            keyboard = [
                [InlineKeyboardButton("➕ Add More", callback_data="merge_add_video")],
                [
                    InlineKeyboardButton("▶️ Merge", callback_data="merge_confirm"),
                    InlineKeyboardButton("❌ Cancel", callback_data="merge_clear"),
                    InlineKeyboardButton("🔙 Back", callback_data="merge_menu"),
                ],
            ]
            
            queue_text = f"✅ Video added!\n\n{queue.format_queue_message()}\n\nAdd more videos or start merge?"
            
            if len(queue.videos) == 1:
                msg = await update.message.reply_text(
                    text=queue_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                queue.queue_message_id = msg.message_id
            else:
                if queue.queue_message_id:
                    try:
                        await context.bot.delete_message(
                            chat_id=user_id,
                            message_id=queue.queue_message_id
                        )
                    except Exception as e:
                        logger.warning(f"Could not delete old message: {e}")
                
                # Send fresh message
                msg = await update.message.reply_text(
                    text=queue_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                queue.queue_message_id = msg.message_id
        else:
            await update.message.reply_text(
                "❌ Cannot add video to queue\n"
                "Max 20 videos per merge"
            )
        
        context.user_data["operation"] = None
    
    except Exception as e:
        logger.error(f"Error processing merge video: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        context.user_data["operation"] = None


async def _generate_video_thumbnail(video_path: str) -> str:
    """
    Generate thumbnail from merged video.
    Extract first frame at 1 second mark as thumbnail.
    """
    try:
        thumb_path = video_path.replace('.mp4', '_thumb.jpg')
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-ss", "1",  # 1 second into video
            "-vf", "scale=320:180",
            "-vframes", "1",
            "-y",
            thumb_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        
        if result.returncode == 0 and os.path.exists(thumb_path):
            logger.info(f"Generated thumbnail: {thumb_path}")
            return thumb_path
        else:
            logger.warning(f"Could not generate thumbnail")
            return None
    except Exception as e:
        logger.warning(f"Thumbnail generation error: {e}")
        return None


async def execute_smart_merge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute actual merge using FFmpeg concat (FAST - no re-encoding by default)."""
    user_id = update.effective_user.id
    query = update.callback_query
    queue = get_or_create_queue(user_id)
    
    if queue.is_merging:
        await query.answer("⏳ Merge already in progress. Please wait!", show_alert=True)
        logger.warning(f"User {user_id} tried to start merge while already merging")
        return
    
    queue.is_merging = True
    
    upload_mode = context.user_data.get("upload_mode")
    if not upload_mode:
        queue.is_merging = False  # Reset flag before returning
        await query.answer("❌ Please select Upload Mode first!", show_alert=True)
        logger.warning(f"User {user_id} attempted merge without selecting upload mode")
        return
    
    if upload_mode.get("engine") == "telegram" and "format" not in upload_mode:
        queue.is_merging = False  # Reset flag before returning
        await query.answer("❌ Please select format (Video/Document)!", show_alert=True)
        logger.warning(f"User {user_id} attempted merge without selecting Telegram format")
        return
    
    if len(queue.videos) < 2:
        queue.is_merging = False  # Reset flag before returning
        await query.answer("Need at least 2 videos!", show_alert=True)
        return
    
    status_msg = None
    concat_file = None
    output_file = None
    thumbnail_file = None
    
    try:
        start_time = time.time()
        
        merged_filename = context.user_data.get("merged_filename", "merged_video.mp4")
        
        actual_videos = [v.file_name for v in queue.videos]
        logger.info(f"[v0] Starting merge for user {user_id} with {len(queue.videos)} videos: {actual_videos}")
        
        # This prevents "Message to edit not found" errors
        try:
            status_msg = await query.edit_message_text(
                text="🔀 MERGING VIDEOS\n━━━━━━━━━━━━━━━━━━\n\n"
                     "⏳ Stage 1: Preparing Files\n"
                     "📊 Progress: 0%"
            )
        except Exception as e:
            logger.error(f"Could not edit message: {e}")
            # Fallback: create new message if edit fails
            status_msg = await context.bot.send_message(
                chat_id=user_id,
                text="🔀 MERGING VIDEOS\n━━━━━━━━━━━━━━━━━━\n\n"
                     "⏳ Stage 1: Preparing Files\n"
                     "📊 Progress: 0%"
            )
        
        await asyncio.sleep(0.5)
        
        # Stage 1: Create concat file with ALL videos in queue
        concat_file = os.path.join(file_manager.TEMP_FOLDER, "concat_list.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for video in queue.videos:
                if not os.path.exists(video.file_path):
                    logger.warning(f"[v0] Video file not found, skipping: {video.file_path}")
                    continue
                
                abs_path = os.path.abspath(video.file_path).replace("\\", "/")
                logger.info(f"[v0] Adding to concat: {video.file_name} -> {abs_path}")
                f.write(f"file '{abs_path}'\n")
        
        with open(concat_file, "r", encoding="utf-8") as f:
            concat_lines = f.readlines()
            logger.info(f"[v0] Concat file has {len(concat_lines)} valid video entries")
        
        if len(concat_lines) == 0:
            logger.error(f"[v0] Concat file is empty! No valid videos to merge")
            await status_msg.edit_text(
                text="❌ MERGE FAILED\n━━━━━━━━━━━━━━━━━━\n\n"
                     "Error: No valid videos found in queue.\n"
                     "This should not happen. Please try again."
            )
            queue.is_merging = False  # Reset flag on error
            return
        
        total_size_mb = sum(os.path.getsize(v.file_path) / (1024 * 1024) for v in queue.videos if os.path.exists(v.file_path))
        total_duration = queue.get_total_duration()
        output_file = os.path.join(file_manager.TEMP_FOLDER, merged_filename)
        
        try:
            await status_msg.edit_text(
                text="🔀 MERGING VIDEOS\n━━━━━━━━━━━━━━━━━━\n\n"
                     "✅ Stage 1: Files Ready\n"
                     "⏳ Stage 2: Merging (FAST - Stream Copy)\n\n"
                     "📊 Progress: 5%\n"
                     f"📁 Total Size: {total_size_mb:.2f}MB\n"
                     "⏱️ ETA: Calculating..."
            )
        except Exception as e:
            logger.warning(f"Could not update status: {e}")
        
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "concat",
            "-safe", "0",
            "-fflags", "+genpts",
            "-i", concat_file,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c", "copy",
            "-movflags", "+faststart",
            output_file
        ]
        
        logger.info(f"[v0] Running FFmpeg command with {len(concat_lines)} valid videos")
        
        # Run FFmpeg in thread to avoid blocking async event loop
        def run_ffmpeg():
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600
            )
        
        process_result = await asyncio.to_thread(run_ffmpeg)
        
        # Check if merge succeeded
        if process_result.returncode != 0:
            logger.error(f"FFmpeg merge failed with return code: {process_result.returncode}")
            logger.error(f"FFmpeg stderr: {process_result.stderr}")
            
            try:
                await status_msg.edit_text(
                    text="❌ MERGE FAILED\n━━━━━━━━━━━━━━━━━━\n\n"
                         "Error: Check if videos have compatible formats.\n"
                         "Try converting to same format first."
                )
            except:
                pass
            
            # Cleanup
            try:
                if concat_file and os.path.exists(concat_file):
                    os.remove(concat_file)
                if output_file and os.path.exists(output_file):
                    os.remove(output_file)
            except:
                pass
            
            queue.is_merging = False  # Reset flag on error
            return
        
        if not os.path.exists(output_file) or os.path.getsize(output_file) < 1024:
            logger.error(f"Output file missing or too small: {output_file}")
            try:
                await status_msg.edit_text(
                    text="❌ MERGE FAILED\n━━━━━━━━━━━━━━━━━━\n\n"
                         "Error: Output file corrupted or empty.\n"
                         "Ensure videos are valid MP4 files."
                )
            except:
                pass
            
            try:
                if output_file and os.path.exists(output_file):
                    os.remove(output_file)
                if concat_file and os.path.exists(concat_file):
                    os.remove(concat_file)
            except:
                pass
            
            queue.is_merging = False  # Reset flag on error
            return
        
        file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
        
        thumbnail_file = await _generate_video_thumbnail(output_file)
        
        try:
            await status_msg.edit_text(
                text="🔀 MERGING VIDEOS\n━━━━━━━━━━━━━━━━━━\n\n"
                     "✅ Stage 1: Files Ready\n"
                     "✅ Stage 2: Merge Complete\n"
                     "⏳ Stage 3: Uploading\n\n"
                     "📊 Progress: 95%"
            )
        except:
            pass
        
        upload_engine = upload_mode.get("engine", "telegram")
        
        if upload_engine == "telegram":
            upload_as_document = upload_mode.get("format") == "document"
            await _upload_to_telegram(
                context, user_id, output_file, file_size_mb, 
                queue, start_time, status_msg, upload_as_document, merged_filename, thumbnail_file
            )
        elif upload_engine == "rclone":
            await _upload_to_rclone(
                context, user_id, output_file, queue, start_time, status_msg, merged_filename
            )
        elif upload_engine == "pyrogram" and PYROGRAM_AVAILABLE:
            await _upload_to_pyrogram(
                context, user_id, output_file, file_size_mb, 
                queue, start_time, status_msg, merged_filename, thumbnail_file
            )
        else:
            logger.error(f"Unknown upload engine: {upload_engine}")
            await status_msg.edit_text("❌ Invalid upload mode configured")
        
        logger.info(f"[v0] Clearing merge queue for user {user_id} after successful merge")
        queue.clear_all()
        
        # Cleanup
        context.user_data.pop("merged_filename", None)
        
        # Cleanup temp files
        try:
            if output_file and os.path.exists(output_file):
                os.remove(output_file)
            if concat_file and os.path.exists(concat_file):
                os.remove(concat_file)
            if thumbnail_file and os.path.exists(thumbnail_file):
                os.remove(thumbnail_file)
        except:
            pass
    
    except Exception as e:
        logger.error(f"Error executing merge: {e}", exc_info=True)
        try:
            if status_msg:
                await status_msg.edit_text(f"❌ Merge error: {str(e)}")
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Merge error: {str(e)}"
                )
        except Exception as edit_error:
            logger.error(f"Could not send error message: {edit_error}")
        
        queue.clear_all()
        
        # Cleanup on error
        try:
            if concat_file and os.path.exists(concat_file):
                os.remove(concat_file)
            if output_file and os.path.exists(output_file):
                os.remove(output_file)
            if thumbnail_file and os.path.exists(thumbnail_file):
                os.remove(thumbnail_file)
        except:
            pass
    
    finally:
        queue.is_merging = False


async def _upload_to_telegram(context, user_id, filepath, file_size_mb, queue, start_time, status_msg, upload_as_document, filename, thumbnail_file=None):
    """
    Upload file to Telegram with MTProto fallback for large files.
    Uses Pyrogram (MTProto) for files >50MB, Bot API for smaller files.
    """
    try:
        if file_size_mb > 50 and PYROGRAM_AVAILABLE:
            logger.info(f"Using Pyrogram MTProto for large file upload ({file_size_mb:.2f}MB)")
            await _upload_via_pyrogram(user_id, filepath, filename, file_size_mb, queue, start_time, status_msg, upload_as_document)
            return
        
        # Fallback to Bot API for smaller files
        with open(filepath, 'rb') as f:
            if upload_as_document:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    caption=f"✅ MERGE COMPLETE!\n━━━━━━━━━━━━━━━━━━\n\n"
                            f"📁 {filename}\n"
                            f"📊 Size: {file_size_mb:.2f}MB\n"
                            f"⏱️ Duration: {queue._format_duration(queue.get_total_duration())}\n\n"
                            f"⏲️ Processing time: {int(time.time() - start_time)}s"
                )
            else:
                thumb = None
                if thumbnail_file and os.path.exists(thumbnail_file):
                    try:
                        thumb = open(thumbnail_file, 'rb')
                        await context.bot.send_video(
                            chat_id=user_id,
                            video=f,
                            thumbnail=thumb,
                            caption=f"✅ MERGE COMPLETE!\n━━━━━━━━━━━━━━━━━━\n\n"
                                    f"📹 {filename}\n"
                                    f"📊 Size: {file_size_mb:.2f}MB\n"
                                    f"⏱️ Duration: {queue._format_duration(queue.get_total_duration())}\n\n"
                                    f"⏲️ Processing time: {int(time.time() - start_time)}s"
                        )
                    finally:
                        if thumb:
                            thumb.close()
                else:
                    await context.bot.send_video(
                        chat_id=user_id,
                        video=f,
                        caption=f"✅ MERGE COMPLETE!\n━━━━━━━━━━━━━━━━━━\n\n"
                                f"📹 {filename}\n"
                                f"📊 Size: {file_size_mb:.2f}MB\n"
                                f"⏱️ Duration: {queue._format_duration(queue.get_total_duration())}\n\n"
                                f"⏲️ Processing time: {int(time.time() - start_time)}s"
                    )
        
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Telegram upload error: {e}")
        raise


async def _upload_to_rclone(context, user_id, filepath, queue, start_time, status_msg, filename):
    """Upload file to Rclone configured drive."""
    try:
        from handlers.rclone_upload import rclone_driver
        
        result = await rclone_driver(status_msg, user_id, filepath, filename)
        
        if result.get("success"):
            # Update final message with completion info
            try:
                await status_msg.edit_text(
                    text=f"✅ MERGE & UPLOAD COMPLETE!\n━━━━━━━━━━━━━━━━━━\n\n"
                         f"📁 File: {filename}\n"
                         f"☁️ Remote: {result.get('remote', 'Unknown')}\n"
                         f"📊 Size: {os.path.getsize(filepath)/(1024*1024):.2f}MB\n"
                         f"⏱️ Total time: {int(time.time() - start_time)}s"
                )
            except:
                pass
            
            logger.info(f"Rclone upload successful for user {user_id}")
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Rclone upload failed: {error_msg}")
            try:
                await status_msg.edit_text(
                    f"❌ Rclone upload failed:\n{error_msg}"
                )
            except:
                pass
        
    except ImportError as e:
        logger.error(f"Rclone module import error: {e}")
        try:
            await status_msg.edit_text(
                "❌ Rclone handler not found.\n"
                "Please ensure rclone module is installed."
            )
        except:
            pass
    except Exception as e:
        logger.error(f"Rclone upload error: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Rclone upload failed: {str(e)}")
        except:
            pass


async def _upload_to_pyrogram(context, user_id, filepath, file_size_mb, queue, start_time, status_msg, filename, thumbnail_file=None):
    """Upload file to Pyrogram configured drive."""
    try:
        if not context.user_data.get("pyrogram_client"):
            logger.error("Pyrogram client not initialized")
            await status_msg.edit_text("❌ Pyrogram client not initialized")
            return
        
        pyrogram_client = context.user_data["pyrogram_client"]
        
        with open(filepath, 'rb') as f:
            if thumbnail_file and os.path.exists(thumbnail_file):
                await pyrogram_client.send_video(
                    chat_id=user_id,
                    video=f,
                    thumb=thumbnail_file,
                    caption=f"✅ MERGE COMPLETE!\n━━━━━━━━━━━━━━━━━━\n\n"
                            f"📹 {filename}\n"
                            f"📊 Size: {file_size_mb:.2f}MB\n"
                            f"⏱️ Duration: {queue._format_duration(queue.get_total_duration())}\n\n"
                            f"⏲️ Processing time: {int(time.time() - start_time)}s"
                )
            else:
                await pyrogram_client.send_video(
                    chat_id=user_id,
                    video=f,
                    caption=f"✅ MERGE COMPLETE!\n━━━━━━━━━━━━━━━━━━\n\n"
                            f"📹 {filename}\n"
                            f"📊 Size: {file_size_mb:.2f}MB\n"
                            f"⏱️ Duration: {queue._format_duration(queue.get_total_duration())}\n\n"
                            f"⏲️ Processing time: {int(time.time() - start_time)}s"
                )
        
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Pyrogram upload error: {e}")
        raise


async def _upload_via_pyrogram(user_id, filepath, filename, file_size_mb, queue, start_time, status_msg, upload_as_document):
    """
    Upload file using Pyrogram (MTProto) for files >50MB.
    Bypasses Telegram Bot API 50MB limit.
    
    Requires:
    - pyrogram library installed
    - Telegram API_ID and API_HASH configured in environment
    - User session file created
    """
    try:
        import os as os_module
        
        api_id = int(os_module.getenv("TELEGRAM_API_ID", "31315704"))
        api_hash = os_module.getenv("TELEGRAM_API_HASH", "e9a0fcbaf23eb7d872732e87cbb012cc")
        
        if not api_id or not api_hash:
            logger.error("Pyrogram: Missing TELEGRAM_API_ID or TELEGRAM_API_HASH")
            raise ValueError("Telegram API credentials not configured")
        
        # Create MTProto client (user session)
        client = Client(
            name="video_merger_session",
            api_id=api_id,
            api_hash=api_hash,
            in_memory=True  # Don't save session to disk
        )
        
        async with client:
            logger.info(f"Uploading {file_size_mb:.2f}MB file via Pyrogram to user {user_id}")
            
            # Send file via Pyrogram (no size limit)
            if upload_as_document:
                await client.send_document(
                    chat_id=user_id,
                    document=filepath,
                    caption=f"✅ MERGE COMPLETE!\n━━━━━━━━━━━━━━━━━━\n\n"
                            f"📁 {filename}\n"
                            f"📊 Size: {file_size_mb:.2f}MB\n"
                            f"⏱️ Duration: {queue._format_duration(queue.get_total_duration())}\n\n"
                            f"⏲️ Processing time: {int(time.time() - start_time)}s"
                )
            else:
                await client.send_video(
                    chat_id=user_id,
                    video=filepath,
                    caption=f"✅ MERGE COMPLETE!\n━━━━━━━━━━━━━━━━━━\n\n"
                            f"📹 {filename}\n"
                            f"📊 Size: {file_size_mb:.2f}MB\n"
                            f"⏱️ Duration: {queue._format_duration(queue.get_total_duration())}\n\n"
                            f"⏲️ Processing time: {int(time.time() - start_time)}s"
                )
            
            logger.info(f"Pyrogram upload successful for user {user_id}")
        
        await status_msg.delete()
    
    except ImportError:
        logger.error("Pyrogram not installed. Install with: pip install pyrogram tgcrypto")
        try:
            await status_msg.edit_text(
                "❌ UPLOAD FAILED\n━━━━━━━━━━━━━━━━━━\n\n"
                f"File size ({file_size_mb:.2f}MB) exceeds Bot API limit (50MB).\n\n"
                "⚠️ Install Pyrogram for large file support:\n"
                "`pip install pyrogram tgcrypto`"
            )
        except:
            pass
    
    except Exception as e:
        logger.error(f"Pyrogram upload error: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Upload error: {str(e)}")
        except:
            pass
