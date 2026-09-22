import os
import asyncio
import logging
import collections
from dotenv import load_dotenv

from db import Database
from shazam import ShazamAnalyzer
from spotify import SpotifyClient
from twitch import TwitchMonitor
from telegram_bot import TelegramBot

# Load environment variables
load_dotenv()

# Setup standard logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
# Suppress noisy debug logs from third-party libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("spotipy").setLevel(logging.WARNING)

logger = logging.getLogger("core")

async def main():
    logger.info("Initializing StreamTracks.")
    
    os.makedirs("/data", exist_ok=True)
    db = Database()
    await db.init_db()
    
    twitch = TwitchMonitor()
    shazam = ShazamAnalyzer()
    spotify = SpotifyClient()
    telegram = TelegramBot()
    
    check_interval = int(os.getenv("CHECK_INTERVAL_SEC", "60"))
    fallback_interval = int(os.getenv("FALLBACK_INTERVAL_SEC", "20"))
    max_retries = int(os.getenv("MAX_FALLBACK_RETRIES", "3"))
    recording_duration = int(os.getenv("RECORDING_DURATION_SEC", "25"))
    
    chunk_file = "/data/temp_chunk.mp3"
    consecutive_failures = 0
    
    if not twitch.channel:
        logger.critical("TWITCH_CHANNEL is not set in .env. Exiting.")
        return
        
    import uuid
    
    while True:
        sleep_time = check_interval
        
        try:
            is_live_now = bool(twitch.get_audio_stream_url())
            was_live_db = await db.get_state("is_live") == "1"
            current_stream_id = await db.get_state("current_stream_id")
            
            if is_live_now:
                if not was_live_db:
                    # Stream JUST went live, or started while bot was offline
                    current_stream_id = str(uuid.uuid4())
                    await db.set_state("current_stream_id", current_stream_id)
                    await db.set_state("is_live", "1")
                    
                    # If this is not the very first check (meaning the bot has been running), OR
                    # if we want to be safe, we just always send it unless we have some other logic.
                    # Actually, if was_live_db was 0, it means we cleanly saw it go offline before, 
                    # OR this is a fresh database. So sending an alert is always correct here!
                    logger.info("Stream just went live! Sending alert to Telegram.")
                    title = twitch.get_stream_title()
                    telegram.send_live_alert(twitch.channel, title)
                    
                logger.info(f"Stream is live. Recording audio chunk ({recording_duration}s)...")
                success, timecode_sec = await twitch.record_audio(chunk_file, duration_sec=recording_duration)
                
                if success and os.path.exists(chunk_file):
                    logger.info("Chunk recorded. Analyzing audio.")
                    result = await shazam.analyze_file(chunk_file)
                    
                    if result:
                        consecutive_failures = 0
                        title, artist = result["title"], result["artist"]
                        track_full_name = f"{artist} - {title}"
                        logger.info(f"Track identified: {track_full_name}")
                        
                        spotify_id, spotify_url = spotify.search_track(title, artist)
                        
                        # Database handles deduplication for THIS stream session using current_stream_id
                        if await db.add_track(title, artist, current_stream_id, spotify_id):
                            if spotify_url:
                                logger.info("Track found on Spotify. Sending to Telegram.")
                            else:
                                logger.warning("Track not found on Spotify. Sending basic info to Telegram.")
                                
                            telegram.send_track(track_full_name, spotify_url, timecode_sec)
                        else:
                            logger.info(f"Track '{track_full_name}' already played this stream. Skipped.")
                    else:
                        logger.info("No music detected.")
                        consecutive_failures += 1
                        
                        if consecutive_failures <= max_retries:
                            sleep_time = fallback_interval
                            logger.info(f"Fallback active ({consecutive_failures}/{max_retries}). Next check in {sleep_time}s.")
                        else:
                            logger.info("Max retries reached. Restoring standard check interval.")
                            consecutive_failures = 0
                        
                    # Cleanup or save chunk for debugging
                    if os.path.exists(chunk_file):
                        if not result:
                            # Save the failed chunk so the user can listen to it
                            import shutil
                            debug_file = "/data/debug_last_failed_chunk.mp3"
                            shutil.copy(chunk_file, debug_file)
                            logger.info(f"Saved debug audio chunk to {debug_file}")
                            
                        try:
                            os.remove(chunk_file)
                        except OSError:
                            pass
            else:
                if was_live_db:
                    logger.info("Stream went offline.")
                    await db.set_state("is_live", "0")
                else:
                    logger.info("Stream is offline.")
                consecutive_failures = 0
                
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            consecutive_failures = 0
            
        logger.debug(f"Sleeping for {sleep_time}s.")
        await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
