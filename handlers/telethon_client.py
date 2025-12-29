"""Telethon client for downloading large files (up to 2GB)."""
import os
import logging
import time
from telethon import TelegramClient
from telethon.types import DocumentAttributeVideo
from telethon.errors import SessionPasswordNeededError

logger = logging.getLogger(__name__)

# Global Telethon client
telethon_client = None
client_lock = None

async def get_telethon_client():
    """
    Get or create a persistent Telethon client.
    Uses bot token for initialization.
    """
    global telethon_client, client_lock
    
    try:
        API_ID = int(os.getenv('API_ID', '24663402'))
        API_HASH = os.getenv('API_HASH', '3ca4ba0a56c360004a0048d51d385529')
        BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8568856909:AAHy9nqMBhcIGVuFdA2QtMWKWoqQf5roROE')
        
        if not BOT_TOKEN:
            logger.error("[v0] TELEGRAM_BOT_TOKEN not set in environment")
            return None
        
        if telethon_client is None:
            telethon_client = TelegramClient(
                session='bot_session',
                api_id=API_ID,
                api_hash=API_HASH
            )
            
            logger.info("[v0] Created Telethon client")
            
            # Start the client with bot token
            await telethon_client.start(bot_token=BOT_TOKEN)
            logger.info("[v0] Telethon client started successfully with MTProto API")
            logger.info("[v0] Supporting files up to 2GB!")
        
        return telethon_client
    
    except Exception as e:
        logger.error(f"[v0] Error creating Telethon client: {e}", exc_info=True)
        telethon_client = None
        return None

def create_progress_callback(total_size: int):
    """
    Create a progress callback that displays download speed and ETA.
    
    Args:
        total_size: Total file size in bytes
    
    Returns:
        Callback function for download progress
    """
    start_time = time.time()
    
    def progress_callback(current, total):
        elapsed = time.time() - start_time
        if elapsed > 0:
            speed_mbps = (current / (1024*1024)) / elapsed
            if current > 0:
                eta_seconds = (total - current) / (current / elapsed) if current > 0 else 0
                percentage = (current / total) * 100 if total > 0 else 0
                
                logger.info(
                    f"[v0] Download progress: {percentage:.1f}% | "
                    f"Speed: {speed_mbps:.2f} MB/s | "
                    f"ETA: {int(eta_seconds)}s | "
                    f"{current/(1024*1024):.2f}MB/{total/(1024*1024):.2f}MB"
                )
    
    return progress_callback

async def download_file_via_telethon(chat_id: int, message_id: int, file_path: str, progress_callback=None) -> bool:
    """
    Download file from Telegram using Telethon (supports up to 2GB).
    
    Args:
        chat_id: Chat/Channel ID where message is located
        message_id: Message ID containing the file
        file_path: Local path to save file
        progress_callback: Optional callback for download progress
    
    Returns:
        True if download successful, False otherwise
    """
    try:
        client = await get_telethon_client()
        if not client:
            logger.error("[v0] Failed to get Telethon client")
            return False
        
        logger.info(f"[v0] Downloading file via Telethon MTProto from chat {chat_id}, message {message_id}")
        
        # Fetch the message from Telegram
        message = await client.get_messages(chat_id, ids=message_id)
        
        if not message or not message.media:
            logger.error("[v0] Message not found or has no media")
            return False
        
        final_callback = progress_callback if progress_callback else create_progress_callback(message.media.size)
        
        await client.download_media(
            message,
            file=file_path,
            progress_callback=final_callback
        )
        
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            logger.info(f"[v0] File downloaded successfully via Telethon: {file_size / (1024*1024):.2f}MB")
            return True
        else:
            logger.error("[v0] File download completed but file not found")
            return False
    
    except Exception as e:
        logger.error(f"[v0] Telethon download failed: {e}", exc_info=True)
        return False

async def close_telethon_client():
    """Close the Telethon client gracefully."""
    global telethon_client
    
    try:
        if telethon_client and telethon_client.is_connected():
            await telethon_client.disconnect()
            logger.info("[v0] Telethon client disconnected")
    except Exception as e:
        logger.error(f"[v0] Error closing Telethon client: {e}")
    finally:
        telethon_client = None
