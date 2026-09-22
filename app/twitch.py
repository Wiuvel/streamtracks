import os
import asyncio
import streamlink
import subprocess
import logging
from streamlink.exceptions import NoPluginError, PluginError

logger = logging.getLogger("twitch")

class TwitchMonitor:
    def __init__(self):
        self.channel = os.getenv("TWITCH_CHANNEL")
        self.oauth_token = os.getenv("TWITCH_OAUTH_TOKEN")
        
    def get_audio_stream(self):
        url = f"https://twitch.tv/{self.channel}"
        session = streamlink.Streamlink()
        
        if self.oauth_token:
            session.set_option("twitch-api-header", [f"Authorization=OAuth {self.oauth_token}"])
            session.set_option("twitch-disable-ads", True)
            
        try:
            streams = session.streams(url)
            if not streams:
                return None
                
            if "audio_only" in streams:
                return streams["audio_only"]
            elif "worst" in streams:
                return streams["worst"]
            return None
        except (NoPluginError, PluginError) as e:
            logger.error(f"Streamlink initialization failed: {e}")
            return None
            
    async def record_audio(self, final_output_file: str, duration_sec: int = 15) -> bool:
        """Records the stream to a temporary TS file, converts to MP3, and saves it."""
        stream = self.get_audio_stream()
        if not stream:
            return False
            
        ts_temp = f"{final_output_file}.ts"
            
        try:
            def _read_ts():
                fd = stream.open()
                target_bytes = 1024 * 500  # ~15-20 secs of 160kbps audio
                bytes_read = 0
                
                with open(ts_temp, "wb") as f:
                    while bytes_read < target_bytes:
                        data = fd.read(1024 * 64)
                        if not data:
                            break
                        f.write(data)
                        bytes_read += len(data)
                fd.close()
                return bytes_read > 0
                
            loop = asyncio.get_event_loop()
            success = await asyncio.wait_for(
                loop.run_in_executor(None, _read_ts),
                timeout=duration_sec + 60
            )
            
            if success and os.path.exists(ts_temp):
                # Convert the raw TS chunk to clean MP3 to avoid ffmpeg/shazamio metadata errors
                subprocess.run(
                    ["ffmpeg", "-y", "-i", ts_temp, "-vn", "-acodec", "libmp3lame", final_output_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                os.remove(ts_temp)
                return os.path.exists(final_output_file)
                
            return False
            
        except asyncio.TimeoutError:
            logger.warning("Stream recording timed out (likely ad blocked).")
            if os.path.exists(ts_temp):
                os.remove(ts_temp)
            return False
        except Exception as e:
            logger.error(f"Audio recording failed: {e}")
            if os.path.exists(ts_temp):
                os.remove(ts_temp)
            return False
