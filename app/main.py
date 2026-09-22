import os
import asyncio
import logging
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
    
    check_interval = int(os.getenv("CHECK_INTERVAL_SEC", "120"))
    fallback_interval = int(os.getenv("FALLBACK_INTERVAL_SEC", "20"))
    max_retries = int(os.getenv("MAX_FALLBACK_RETRIES", "3"))
    
    chunk_file = "/data/temp_chunk.mp3"
    consecutive_failures = 0
    
    if not twitch.channel:
        logger.critical("TWITCH_CHANNEL is not set in .env. Exiting.")
        return
        
    logger.info(f"Target channel configured: {twitch.channel}")
    
    while True:
        sleep_time = check_interval
        
        try:
            if twitch.get_audio_stream_url():
                logger.info("Stream is live. Recording audio chunk.")
                success = await twitch.record_audio(chunk_file, duration_sec=15)
                
                if success and os.path.exists(chunk_file):
                    logger.info("Chunk recorded. Analyzing audio.")
                    result = await shazam.analyze_file(chunk_file)
                    
                    if result:
                        consecutive_failures = 0
                        title, artist = result["title"], result["artist"]
                        track_full_name = f"{artist} - {title}"
                        logger.info(f"Track identified: {track_full_name}")
                        
                        if await db.add_track(title, artist):
                            spotify_id, spotify_url = spotify.search_track(title, artist)
                            
                            if spotify_url:
                                message = f"<b>{track_full_name}</b>\n\n<a href='{spotify_url}'>Listen on Spotify</a>"
                                logger.info("Track found on Spotify. Sending to Telegram.")
                            else:
                                message = f"<b>{track_full_name}</b>\n\n<i>Not found on Spotify</i>"
                                logger.warning("Track not found on Spotify. Sending basic info to Telegram.")
                                
                            telegram.send_message(message)
                        else:
                            logger.info("Track already in local database. Skipped.")
                    else:
                        logger.info("No music detected.")
                        consecutive_failures += 1
                        
                        if consecutive_failures <= max_retries:
                            sleep_time = fallback_interval
                            logger.info(f"Fallback active ({consecutive_failures}/{max_retries}). Next check in {sleep_time}s.")
                        else:
                            logger.info("Max retries reached. Restoring standard check interval.")
                            consecutive_failures = 0
                        
                    # Cleanup chunk
                    if os.path.exists(chunk_file):
                        try:
                            os.remove(chunk_file)
                        except OSError:
                            pass
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
