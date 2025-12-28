"""Initialize Pyrogram client for large file downloads via MTProto protocol."""
import logging
import os
from pyrogram import Client
from pyrogram.errors import BadRequest

logger = logging.getLogger(__name__)

# Cache for pyrogram clients per user
pyrogram_clients = {}

async def get_or_create_pyrogram_client(user_id: str) -> Client:
    """
    Get or create a Pyrogram client for MTProto downloads.
    Each user gets their own session file.
    
    Pyrogram MTProto supports files up to 2GB (vs Bot API 50MB limit).
    
    Requires environment variables:
    - TELEGRAM_API_ID: Your Telegram API ID (from https://my.telegram.org)
    - TELEGRAM_API_HASH: Your Telegram API Hash (from https://my.telegram.org)
    """
    if user_id in pyrogram_clients:
        client = pyrogram_clients[user_id]
        logger.info(f"[v0] Using cached Pyrogram client for user {user_id}")
        return client
    
    try:
        api_id = int(os.getenv("TELEGRAM_API_ID", "31315704"))
        api_hash = os.getenv("TELEGRAM_API_HASH", "e9a0fcbaf23eb7d872732e87cbb012cc")
        
        if not api_id or not api_hash:
            logger.error("[v0] Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in environment")
            return None
        
        # Create user session directory
        session_dir = f"./userdata/{user_id}"
        os.makedirs(session_dir, exist_ok=True)
        
        # Starting will happen once in file_handler.py and kept alive
        client = Client(
            f"user_{user_id}",
            api_id,
            api_hash,
            no_updates=True  # Disable update handling for download-only client
        )
        
        pyrogram_clients[user_id] = client
        logger.info(f"[v0] Created Pyrogram client for user {user_id} (NOT YET STARTED)")
        return client
    
    except Exception as e:
        logger.error(f"[v0] Error creating Pyrogram client: {e}", exc_info=True)
        return None


async def download_file_via_pyrogram(
    client: Client, 
    chat_id: int, 
    message_id: int, 
    filepath: str
) -> bool:
    """
    Download file from Telegram using Pyrogram MTProto protocol.
    Supports files up to 2GB (vs Bot API 50MB limit).
    
    Args:
        client: Pyrogram client instance (must be connected)
        chat_id: Telegram chat ID
        message_id: Message ID containing the file
        filepath: Local path to save file
    
    Returns:
        True if download successful, False otherwise
    """
    try:
        # No reconnection logic needed here - that causes msg_id rollback
        if not client.is_connected:
            logger.error("[v0] Client not connected - must be started before download")
            return False
        
        logger.info(f"[v0] Starting Pyrogram download to: {filepath}")
        
        # Get message with file
        msg = await client.get_messages(chat_id, message_id)
        
        if not msg:
            logger.error(f"[v0] Message not found: chat_id={chat_id}, message_id={message_id}")
            return False
        
        # Check if message has a media file
        if not (msg.document or msg.video or msg.audio or msg.animation):
            logger.error(f"[v0] Message has no downloadable media")
            return False
        
        # Download the file
        logger.info(f"[v0] Downloading file from message {message_id}")
        downloaded_path = await msg.download(file_name=filepath)
        
        if downloaded_path and os.path.exists(filepath):
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            logger.info(f"[v0] Pyrogram download successful: {filepath} ({file_size_mb:.2f}MB)")
            return True
        else:
            logger.error(f"[v0] Downloaded file not found at {filepath}")
            return False
    
    except BadRequest as e:
        logger.error(f"[v0] Pyrogram BadRequest error: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"[v0] Pyrogram download error: {e}", exc_info=True)
        return False


async def cleanup_pyrogram_client(user_id: str) -> None:
    """Cleanup and disconnect Pyrogram client for user. Call only on bot shutdown."""
    try:
        if user_id in pyrogram_clients:
            client = pyrogram_clients[user_id]
            if client.is_connected:
                await client.stop()
            del pyrogram_clients[user_id]
            logger.info(f"[v0] Cleaned up Pyrogram client for user {user_id}")
    except Exception as e:
        logger.warning(f"[v0] Error cleaning up Pyrogram client: {e}")
