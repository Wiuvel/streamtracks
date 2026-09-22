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
            logger.error("Failed to get M3U8 URL from yt-dlp.")
            return False

        ts_file = final_output_file.replace(".mp3", ".ts")
        logger.info(f"Got M3U8 URL: {m3u8_url.split('?')[0]}...")
        
        try:
            # 1. Fetch the M3U8 playlist
            req = urllib.request.Request(m3u8_url, headers={'User-Agent': self.user_agent})
            with urllib.request.urlopen(req, timeout=10) as response:
                m3u8_content = response.read().decode('utf-8')
            
            logger.info(f"Fetched M3U8. Length: {len(m3u8_content)} bytes. First 100 chars: {m3u8_content[:100].replace(chr(10), ' ')}")
            
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

            logger.info(f"Found {len(ts_urls)} raw segment URLs in playlist. First URL: {ts_urls[0].split('?')[0]}")

            # Filter out known Twitch ad server segments
            real_ts_urls = [url for url in ts_urls if "weaver" not in url.lower() and "stitched" not in url.lower()]
            if not real_ts_urls:
                logger.warning("All segments appear to be ad servers! Falling back to raw list.")
                real_ts_urls = ts_urls

            # Take segments from the END of the playlist (the actual live edge) to avoid pre-roll ads
            chunks_needed = (duration_sec // 2) + 2
            target_urls = real_ts_urls[-chunks_needed:]
            
            logger.info(f"Selected {len(target_urls)} segments from the live edge to download.")

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
            if not os.path.exists(ts_file):
                logger.error("TS file does not exist after download attempt.")
                return False
                
            ts_size = os.path.getsize(ts_file)
            logger.info(f"Downloaded TS file natively. Total size: {ts_size / 1024:.2f} KB.")
            
            if ts_size < 10000:
                logger.error("Failed to download sufficient TS data natively (file too small).")
                return False

            # 4. Use ffprobe to detect how many audio streams are in the TS file.
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
                logger.info(f"ffprobe output: '{probe_out.replace(chr(10), ',')}', Tracks detected: {num_audio}")
            except Exception as e:
                logger.warning(f"ffprobe failed: {e}")
                num_audio = 1

            if num_audio > 1:
                logger.info(f"Detected {num_audio} audio tracks in TS chunk! Mixing them to ensure music is captured.")
                cmd = [
                    "ffmpeg", "-y", "-i", ts_file,
                    "-filter_complex", f"amix=inputs={num_audio}:duration=longest",
                    "-vn", "-acodec", "libmp3lame", final_output_file
                ]
            else:
                logger.info("Only 1 audio track detected. Proceeding with standard extraction.")
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
                
            if success and os.path.exists(final_output_file):
                mp3_size = os.path.getsize(final_output_file)
                logger.info(f"ffmpeg conversion successful. MP3 size: {mp3_size / 1024:.2f} KB.")
                if mp3_size > 1000:
                    return True
                else:
                    logger.warning("MP3 file is too small (likely silent/empty).")
                
            logger.error("ffmpeg failed to convert TS to MP3.")
            return False

        except Exception as e:
            logger.error(f"Native audio recording failed: {e}")
            if os.path.exists(ts_file):
                os.remove(ts_file)
            return False
