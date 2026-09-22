import os
import asyncio
import subprocess
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("twitch")

class TwitchMonitor:
    def __init__(self):
        self.channel = os.getenv("TWITCH_CHANNEL")
        self.oauth_token = os.getenv("TWITCH_OAUTH_TOKEN")
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
    def get_audio_stream_url(self):
        """Quick check to see if stream is live and returns M3U8 URL"""
        url = f"https://twitch.tv/{self.channel}"
        try:
            cmd = ["yt-dlp", "-g", "-f", "best", url]
            if self.oauth_token and "your_" not in self.oauth_token:
                cmd.extend(["--extractor-args", f"twitch:api_header=Authorization=OAuth {self.oauth_token}"])
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None
        except Exception:
            return None

    async def record_audio(self, final_output_file: str, duration_sec: int = 25) -> bool:
        """Downloads HLS segments manually in Python to bypass ffmpeg's HTTP client fingerprinting, then converts to MP3."""
        
        if os.path.exists(final_output_file):
            try:
                os.remove(final_output_file)
            except OSError:
                pass

        m3u8_url = self.get_audio_stream_url()
        if not m3u8_url:
            return False

        ts_file = final_output_file.replace(".mp3", ".ts")
        
        try:
            # 1. Fetch the M3U8 playlist
            req = urllib.request.Request(m3u8_url, headers={'User-Agent': self.user_agent})
            with urllib.request.urlopen(req, timeout=10) as response:
                m3u8_content = response.read().decode('utf-8')
            
            # 2. Extract TS segment URLs
            ts_urls = []
            for line in m3u8_content.splitlines():
                if line and not line.startswith('#'):
                    # Handle relative vs absolute URLs just in case
                    if line.startswith('http'):
                        ts_urls.append(line)
                    else:
                        base_url = m3u8_url.rsplit('/', 1)[0]
                        ts_urls.append(f"{base_url}/{line}")

            if not ts_urls:
                logger.error("No TS segments found in M3U8 playlist.")
                return False

            # Filter out known Twitch ad server segments
            real_ts_urls = [url for url in ts_urls if "weaver" not in url.lower() and "stitched" not in url.lower()]
            if not real_ts_urls:
                real_ts_urls = ts_urls # Fallback if all are flagged

            # Take segments from the END of the playlist (the actual live edge) to avoid pre-roll ads
            chunks_needed = (duration_sec // 2) + 2
            target_urls = real_ts_urls[-chunks_needed:]

            # 3. Download the TS chunks natively using Python
            with open(ts_file, 'wb') as f_out:
                for ts_url in target_urls:
                    try:
                        ts_req = urllib.request.Request(ts_url, headers={'User-Agent': self.user_agent})
                        with urllib.request.urlopen(ts_req, timeout=10) as ts_res:
                            f_out.write(ts_res.read())
                    except Exception as e:
                        logger.warning(f"Failed to download a TS chunk: {e}")
                        continue
            
            # Check if we downloaded anything
            if not os.path.exists(ts_file) or os.path.getsize(ts_file) < 10000:
                logger.error("Failed to download sufficient TS data natively.")
                return False

            # 4. Use ffprobe to detect how many audio streams are in the TS file.
            # If the streamer uses OBS "Twitch VOD Track", the TS file might contain TWO audio tracks.
            # Often, Track 1 is muted/VOD-only, and Track 2 has the music. ffmpeg defaults to Track 1.
            # We will dynamically mix all audio tracks together if there are multiple!
            
            probe_cmd = [
                "ffprobe", "-v", "error", 
                "-select_streams", "a", 
                "-show_entries", "stream=index", 
                "-of", "csv=p=0", 
                ts_file
            ]
            
            try:
                probe_out = subprocess.check_output(probe_cmd).decode('utf-8').strip()
                num_audio = len([x for x in probe_out.splitlines() if x])
            except Exception:
                num_audio = 1

            if num_audio > 1:
                logger.info(f"Detected {num_audio} audio tracks in TS chunk! Mixing them to ensure music is captured.")
                cmd = [
                    "ffmpeg", "-y", "-i", ts_file,
                    "-filter_complex", f"amix=inputs={num_audio}:duration=longest",
                    "-vn", "-acodec", "libmp3lame", final_output_file
                ]
            else:
                cmd = [
                    "ffmpeg", "-y", "-i", ts_file,
                    "-vn", "-acodec", "libmp3lame", final_output_file
                ]
            
            def _run_convert():
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return res.returncode == 0
                
            loop = asyncio.get_event_loop()
            success = await asyncio.wait_for(
                loop.run_in_executor(None, _run_convert),
                timeout=15
            )
            
            # Cleanup temp TS
            if os.path.exists(ts_file):
                os.remove(ts_file)
                
            if success and os.path.exists(final_output_file) and os.path.getsize(final_output_file) > 1000:
                return True
                
            return False

        except Exception as e:
            logger.error(f"Native audio recording failed: {e}")
            if os.path.exists(ts_file):
                os.remove(ts_file)
            return False
