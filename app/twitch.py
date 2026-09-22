import os
import asyncio
import subprocess
import logging

logger = logging.getLogger("twitch")

class TwitchMonitor:
    def __init__(self):
        self.channel = os.getenv("TWITCH_CHANNEL")
        # yt-dlp doesn't need OAuth for basic live streams, but we keep the config for future extensibility
        self.oauth_token = os.getenv("TWITCH_OAUTH_TOKEN")
        
    def get_audio_stream_url(self):
        """Uses yt-dlp to extract the raw m3u8 stream URL"""
        url = f"https://twitch.tv/{self.channel}"
        try:
            # -g gets the direct URL, -f gets audio_only or the worst quality video if audio is missing
            cmd = ["yt-dlp", "-g", "-f", "audio_only/worst", url]
            
            # If user has an oauth token, we pass it to bypass ad-blocks and sub-only restrictions
            if self.oauth_token and "your_" not in self.oauth_token:
                cmd.extend(["--extractor-args", f"twitch:api_header=Authorization=OAuth {self.oauth_token}"])
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            stream_url = result.stdout.strip()
            if stream_url:
                return stream_url
            return None
        except subprocess.CalledProcessError as e:
            # yt-dlp throws error if the stream is truly offline
            return None
        except Exception as e:
            logger.error(f"yt-dlp execution failed: {e}")
            return None
            
    async def record_audio(self, final_output_file: str, duration_sec: int = 15) -> bool:
        """Records the stream using ffmpeg directly from the m3u8 URL."""
        stream_url = self.get_audio_stream_url()
        if not stream_url:
            return False
            
        try:
            # We use ffmpeg to read directly from the m3u8 stream for X seconds and encode to mp3
            cmd = [
                "ffmpeg",
                "-y",                   # Overwrite
                "-t", str(duration_sec),# Duration to record
                "-i", stream_url,       # Input URL
                "-vn",                  # No video
                "-acodec", "libmp3lame",# Audio codec
                final_output_file       # Output file
            ]
            
            def _run_ffmpeg():
                result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return result.returncode == 0
                
            loop = asyncio.get_event_loop()
            success = await asyncio.wait_for(
                loop.run_in_executor(None, _run_ffmpeg),
                timeout=duration_sec + 15
            )
            
            if success and os.path.exists(final_output_file) and os.path.getsize(final_output_file) > 1000:
                return True
                
            # If ffmpeg created an empty file
            if os.path.exists(final_output_file):
                os.remove(final_output_file)
            return False
            
        except asyncio.TimeoutError:
            logger.warning("Stream recording timed out (likely ad blocked or network stall).")
            if os.path.exists(final_output_file):
                os.remove(final_output_file)
            return False
        except Exception as e:
            logger.error(f"Audio recording failed: {e}")
            if os.path.exists(final_output_file):
                os.remove(final_output_file)
            return False
