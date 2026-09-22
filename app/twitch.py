import os
import asyncio
import subprocess
import logging

logger = logging.getLogger("twitch")

class TwitchMonitor:
    def __init__(self):
        self.channel = os.getenv("TWITCH_CHANNEL")
        self.oauth_token = os.getenv("TWITCH_OAUTH_TOKEN")
            
    def get_audio_stream_url(self):
        """Quick check to see if stream is live"""
        url = f"https://twitch.tv/{self.channel}"
        try:
            cmd = ["yt-dlp", "-g", "-f", "worst", url]
            if self.oauth_token and "your_" not in self.oauth_token:
                cmd.extend(["--extractor-args", f"twitch:api_header=Authorization=OAuth {self.oauth_token}"])
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return bool(result.stdout.strip())
        except subprocess.CalledProcessError:
            return False
        except Exception:
            return False

    async def record_audio(self, final_output_file: str, duration_sec: int = 25) -> bool:
        """Records the stream using yt-dlp and ffmpeg, ensuring all anti-bot headers are preserved."""
        url = f"https://twitch.tv/{self.channel}"
        
        # Make sure previous chunk is gone
        if os.path.exists(final_output_file):
            try:
                os.remove(final_output_file)
            except OSError:
                pass
                
        try:
            # By using yt-dlp as the orchestrator, we guarantee that Twitch sees a valid User-Agent
            # and doesn't serve a dummy silent stream to a bare ffmpeg client.
            cmd = [
                "yt-dlp",
                "-f", "best",
                "--downloader", "ffmpeg",
                # Pass the exact arguments to ffmpeg to cut it and strip video
                "--downloader-args", f"ffmpeg:-y -t {duration_sec} -vn -acodec libmp3lame",
                "-o", final_output_file,
                url
            ]
            
            # Pass OAuth token if available
            if self.oauth_token and "your_" not in self.oauth_token:
                cmd.extend(["--extractor-args", f"twitch:api_header=Authorization=OAuth {self.oauth_token}"])
            
            def _run_ytdlp():
                result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return result.returncode == 0
                
            loop = asyncio.get_event_loop()
            success = await asyncio.wait_for(
                loop.run_in_executor(None, _run_ytdlp),
                timeout=duration_sec + 20
            )
            
            if success and os.path.exists(final_output_file) and os.path.getsize(final_output_file) > 1000:
                return True
                
            # If yt-dlp/ffmpeg created an empty file
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
