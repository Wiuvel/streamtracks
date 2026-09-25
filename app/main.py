import os
import asyncio
import logging
import uuid
import shutil
from dotenv import load_dotenv

from db import Database
from shazam import ShazamAnalyzer
from spotify import SpotifyClient
from twitch import TwitchMonitor
from telegram_bot import TelegramBot

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("spotipy").setLevel(logging.WARNING)
logging.getLogger("shazamio").setLevel(logging.WARNING)

logger = logging.getLogger("core")

async def producer_capture(twitch: TwitchMonitor, analyze_queue: asyncio.Queue, db: Database, telegram: TelegramBot, check_interval: int, recording_duration: int, max_retries: int, fallback_interval: int):
    """Task 1: Continuously captures audio chunks and pushes them to the queue."""
    consecutive_failures = 0
    offline_strikes = 0
    
    while True:
        sleep_time = check_interval
        try:
            is_live_now = bool(await twitch.get_audio_stream_url())
            was_live_db = await db.get_state("is_live") == "1"
            current_stream_id = await db.get_state("current_stream_id")
            
            if is_live_now:
                offline_strikes = 0  # Reset offline strikes
                if not was_live_db:
                    current_stream_id = str(uuid.uuid4())
                    await db.set_state("current_stream_id", current_stream_id)
                    await db.set_state("is_live", "1")
                    
                    logger.info("Stream just went live! Sending alert to Telegram.")
                    title = twitch.get_stream_title()
                    # Fire and forget telegram alert
                    asyncio.create_task(telegram.send_live_alert(twitch.channel, title))
                    
                chunk_id = str(uuid.uuid4())[:8]
                chunk_file = f"/data/chunk_{chunk_id}.mp3"
                
                logger.info(f"Stream is live. Recording audio chunk ({recording_duration}s)...")
                success, timecode_sec = await twitch.record_audio(chunk_file, duration_sec=recording_duration)
                
                if success and os.path.exists(chunk_file):
                    logger.info(f"Chunk {chunk_id} recorded. Pushing to analyze queue.")
                    # Pass the chunk data downstream
                    await analyze_queue.put({
                        "file": chunk_file, 
                        "timecode_sec": timecode_sec,
                        "stream_id": current_stream_id
                    })
                    consecutive_failures = 0
                else:
                    logger.warning("Failed to record valid chunk.")
                    consecutive_failures += 1
            else:
                if was_live_db:
                    offline_strikes += 1
                    if offline_strikes >= 3:
                        logger.info(f"Stream went offline (confirmed after {offline_strikes} checks).")
                        await db.set_state("is_live", "0")
                        offline_strikes = 0
                    else:
                        logger.info(f"Stream appears offline (strike {offline_strikes}/3). Waiting to confirm...")
                else:
                    logger.debug("Stream is offline.")
                consecutive_failures = 0
                
            if consecutive_failures > max_retries:
                sleep_time = fallback_interval
                logger.info(f"Fallback active ({consecutive_failures}/{max_retries}). Next check in {sleep_time}s.")
                
        except Exception as e:
            logger.error(f"Producer error: {e}", exc_info=True)
            
        logger.debug(f"Producer sleeping for {sleep_time}s.")
        await asyncio.sleep(sleep_time)

async def consumer_analyze(shazam: ShazamAnalyzer, analyze_queue: asyncio.Queue, notify_queue: asyncio.Queue, db: Database):
    """Task 2: Pulls chunks, runs Shazam, pushes matches to notifier."""
    while True:
        data = await analyze_queue.get()
        chunk_file = data["file"]
        timecode_sec = data["timecode_sec"]
        stream_id = data["stream_id"]
        
        try:
            logger.info(f"Analyzing {chunk_file}...")
            result = await shazam.analyze_file(chunk_file)
            
            if result:
                title, artist = result["title"], result["artist"]
                track_full_name = f"{artist} - {title}"
                logger.info(f"Track identified: {track_full_name}")
                
                # Check DB for duplicate before doing expensive Spotify/Telegram ops
                is_new = await db.add_track(title, artist, stream_id, None)
                if is_new:
                    await notify_queue.put({
                        "title": title,
                        "artist": artist,
                        "track_full_name": track_full_name,
                        "timecode_sec": timecode_sec,
                        "stream_id": stream_id
                    })
                else:
                    logger.info(f"Track '{track_full_name}' already played this stream. Skipped.")
            else:
                logger.info(f"No music detected in {chunk_file}.")
                # Optional: save failed chunks
                debug_file = "/data/debug_last_failed_chunk.mp3"
                shutil.copy(chunk_file, debug_file)
                
        except Exception as e:
            logger.error(f"Analyzer error: {e}")
        finally:
            # Always clean up chunk
            if os.path.exists(chunk_file):
                try:
                    os.remove(chunk_file)
                except OSError:
                    pass
            analyze_queue.task_done()

async def consumer_notify(spotify: SpotifyClient, db: Database, telegram: TelegramBot, notify_queue: asyncio.Queue):
    """Task 3: Takes matches, queries Spotify, sends Telegram message."""
    while True:
        data = await notify_queue.get()
        title = data["title"]
        artist = data["artist"]
        track_full_name = data["track_full_name"]
        timecode_sec = data["timecode_sec"]
        
        try:
            spotify_id, spotify_url = await spotify.search_track(title, artist)
            
            # Optionally update DB with spotify_id if found
            # (We already added it without spotify_id in Task 2 to lock the duplicate check quickly)
            
            if spotify_url:
                logger.info(f"Track found on Spotify. Sending to Telegram: {track_full_name}")
            else:
                logger.warning(f"Track not found on Spotify. Sending basic info to Telegram: {track_full_name}")
                
            await telegram.send_track(track_full_name, spotify_url, timecode_sec)
            
        except Exception as e:
            logger.error(f"Notifier error: {e}")
        finally:
            notify_queue.task_done()

async def main():
    logger.info("Initializing StreamTracks Concurrent Pipeline.")
    
    os.makedirs("/data", exist_ok=True)
    db = Database()
    await db.init_db()
    
    twitch = TwitchMonitor()
    shazam = ShazamAnalyzer()
    spotify = SpotifyClient()
    telegram = TelegramBot()
    
    if not twitch.channel:
        logger.critical("TWITCH_CHANNEL is not set in .env. Exiting.")
        return
    
    # Updated default intervals for the concurrent pipeline
    check_interval = int(os.getenv("CHECK_INTERVAL_SEC", "45"))
    fallback_interval = int(os.getenv("FALLBACK_INTERVAL_SEC", "20"))
    max_retries = int(os.getenv("MAX_FALLBACK_RETRIES", "3"))
    recording_duration = int(os.getenv("RECORDING_DURATION_SEC", "20"))
    
    analyze_queue = asyncio.Queue()
    notify_queue = asyncio.Queue()
    
    # Spin up the concurrent tasks
    producer_task = asyncio.create_task(producer_capture(twitch, analyze_queue, db, telegram, check_interval, recording_duration, max_retries, fallback_interval))
    analyze_task = asyncio.create_task(consumer_analyze(shazam, analyze_queue, notify_queue, db))
    notify_task = asyncio.create_task(consumer_notify(spotify, db, telegram, notify_queue))
    
    # Keep main running forever
    await asyncio.gather(producer_task, analyze_task, notify_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
