"""Initialize Pyrogram client for large file downloads via MTProto protocol."""
import logging
import os
from pyrogram import Client
from pyrogram.errors import BadRequest
import asyncio

logger = logging.getLogger(__name__)

pyro_client = None
pyro_lock = asyncio.Lock()
client_started = False

async def get_pyrogram_client() -> Client:
    """
    Get or create a GLOBAL persistent Pyrogram client for MTProto downloads.
    
    This is a singleton - only ONE client for the entire bot.
    The client is started ONCE and kept alive for all large file downloads.
    
    Pyrogram MTProto supports files up to 2GB (vs Bot API 50MB limit).
    
    Requires environment variables:
    - TELEGRAM_API_ID: Your Telegram API ID (from https://my.telegram.org)
    - TELEGRAM_API_HASH: Your Telegram API Hash (from https://my.telegram.org)
    """
    global pyro_client, client_started
    
    async with pyro_lock:
        if pyro_client is None:
            try:
                api_id = int(os.getenv("TELEGRAM_API_ID", "31315704"))
                api_hash = os.getenv("TELEGRAM_API_HASH", "e9a0fcbaf23eb7d872732e87cbb012cc")
                
                if not api_id or not api_hash:
                    logger.error("[v0] Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in environment")
                    return None
                
                # Create session directory
                os.makedirs("./sessions", exist_ok=True)
                
                pyro_client = Client(
                    "mtproto_bot_session",  # Single global session
                    api_id,
                    api_hash,
                    no_updates=True,  # Disable update handling
                    workdir="./sessions"
                )
                
                logger.info("[v0] Created global Pyrogram MTProto client (NOT YET STARTED)")
            
            except Exception as e:
                logger.error(f"[v0] Error creating Pyrogram client: {e}", exc_info=True)
                return None
        
        if not client_started:
            try:
                logger.info("[v0] Starting global Pyrogram client for the first time...")
                await pyro_client.start()
                
                logger.info("[v0] Syncing client time with Telegram servers...")
                await pyro_client.get_me()
                
                client_started = True
                logger.info("[v0] ✅ Global Pyrogram client started and time synced")
            
            except Exception as e:
                logger.error(f"[v0] Error starting Pyrogram client: {e}", exc_info=True)
                pyro_client = None
                client_started = False
                return None
        else:
            logger.debug("[v0] Pyrogram client already started, reusing...")
        
        return pyro_client


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
        if not client or not client.is_connected:
            logger.error("[v0] Pyrogram client not connected - cannot download")
            return False
        
        logger.info(f"[v0] Starting Pyrogram MTProto download to: {filepath}")
        
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
        logger.info(f"[v0] Downloading file from message {message_id}...")
        downloaded_path = await msg.download(file_name=filepath)
        
        if downloaded_path and os.path.exists(filepath):
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            logger.info(f"[v0] ✅ Pyrogram download successful: {filepath} ({file_size_mb:.2f}MB)")
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


async def cleanup_pyrogram_client() -> None:
    """Cleanup and disconnect global Pyrogram client. Call only on bot shutdown."""
    global pyro_client, client_started
    
    try:
        if pyro_client and pyro_client.is_connected:
            logger.info("[v0] Stopping global Pyrogram client...")
            await pyro_client.stop()
            client_started = False
            logger.info("[v0] Global Pyrogram client stopped")
    except Exception as e:
        logger.warning(f"[v0] Error stopping Pyrogram client: {e}")
