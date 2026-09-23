import os
import asyncio
import logging
import aiohttp
from datetime import datetime

logger = logging.getLogger("twitch")

class TwitchMonitor:
    def __init__(self):
        self.channel = os.getenv("TWITCH_CHANNEL")
        self.oauth_token = os.getenv("TWITCH_OAUTH_TOKEN")
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.cached_m3u8_url = None
        self.ad_flush_delay = int(os.getenv("AD_FLUSH_DELAY_SEC", "55"))
            
    async def get_audio_stream_url(self) -> str:
        """Uses yt-dlp to get the direct M3U8 URL for the live stream asynchronously."""
        url = f"https://twitch.tv/{self.channel}"
        try:
            cmd = ["yt-dlp", "-g", "-f", "best", url]
            if self.oauth_token and "your_" not in self.oauth_token:
                cmd.extend(["--extractor-args", f"twitch:api_header=Authorization=OAuth {self.oauth_token}"])
                
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and stdout:
                return stdout.decode().strip()
            return None
        except Exception as e:
            logger.error(f"Error getting stream URL: {e}")
            return None

    def get_stream_title(self) -> str:
        """Returns the current date as the stream title per user preference."""
        return datetime.now().strftime("%Y-%m-%d")

    async def record_audio(self, final_output_file: str, duration_sec: int = 25) -> tuple[bool, float]:
        """Downloads HLS segments asynchronously and converts to MP3. Returns (success, timecode_sec)."""
        
        if os.path.exists(final_output_file):
            os.remove(final_output_file)

        is_new_session = False
        if not self.cached_m3u8_url:
            self.cached_m3u8_url = await self.get_audio_stream_url()
            is_new_session = True
            
        m3u8_url = self.cached_m3u8_url
        if not m3u8_url:
            logger.error("Failed to get M3U8 URL from yt-dlp.")
            return False, 0.0

        ts_file = final_output_file.replace(".mp3", ".ts")
        logger.info(f"Using M3U8 URL: {m3u8_url[:50]}...[truncated]")
        
        headers = {'User-Agent': self.user_agent}
        
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                if is_new_session:
                    # 1. Start the HLS session to trigger the pre-roll ad timer
                    async with session.get(m3u8_url, timeout=10) as response:
                        pass # Throw away the ad playlist
                        
                    logger.info(f"New session started. Waiting {self.ad_flush_delay} seconds to completely flush the silent pre-roll ad...")
                    await asyncio.sleep(self.ad_flush_delay)
                
                # 2. Fetch the M3U8 playlist
                async with session.get(m3u8_url, timeout=10) as response:
                    m3u8_content = await response.text()
                
                # 3. Extract TS segment URLs and stream uptime
                ts_urls = []
                elapsed_secs = 0.0
                
                for line in m3u8_content.splitlines():
                    if line.startswith('#EXT-X-TWITCH-ELAPSED-SECS:'):
                        try:
                            elapsed_secs = float(line.split(':')[1])
                        except ValueError:
                            pass
                    elif line and not line.startswith('#'):
                        if line.startswith('http'):
                            ts_urls.append(line)
                        else:
                            base_url = m3u8_url.rsplit('/', 1)[0]
                            ts_urls.append(f"{base_url}/{line}")

                if not ts_urls:
                    logger.error("No TS segments found in M3U8 playlist.")
                    return False, 0.0

                logger.info(f"Found {len(ts_urls)} raw segment URLs in playlist. First URL: {ts_urls[0][:50]}...[truncated]")

                # Filter out known Twitch ad server segments
                real_ts_urls = [url for url in ts_urls if "weaver" not in url.lower() and "stitched" not in url.lower()]
                if not real_ts_urls:
                    logger.warning("All segments appear to be ad servers! Falling back to raw list.")
                    real_ts_urls = ts_urls

                chunks_needed = (duration_sec // 2) + 2
                target_urls = real_ts_urls[-chunks_needed:]
                
                logger.info(f"Selected {len(target_urls)} segments from the live edge to download.")

                # 4. Download the TS chunks natively using aiohttp
                with open(ts_file, 'wb') as f_out:
                    for ts_url in target_urls:
                        try:
                            async with session.get(ts_url, timeout=10) as ts_res:
                                chunk_data = await ts_res.read()
                                f_out.write(chunk_data)
                        except Exception as e:
                            logger.warning(f"Failed to download a TS chunk: {e}")
                            continue
                
            # Check if we downloaded anything
            if not os.path.exists(ts_file):
                logger.error("TS file does not exist after download attempt.")
                return False, 0.0
                
            ts_size = os.path.getsize(ts_file)
            logger.info(f"Downloaded TS file natively. Total size: {ts_size / 1024:.2f} KB.")
            
            if ts_size < 10000:
                logger.error("Failed to download sufficient TS data natively (file too small).")
                return False, 0.0

            # 5. Use ffprobe asynchronously to detect audio streams
            probe_cmd = [
                "ffprobe", "-v", "error", 
                "-select_streams", "a", 
                "-show_entries", "stream=index", 
                "-of", "csv=p=0", 
                ts_file
            ]
            
            try:
                probe_proc = await asyncio.create_subprocess_exec(
                    *probe_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                probe_stdout, _ = await probe_proc.communicate()
                probe_out = probe_stdout.decode('utf-8').strip()
                unique_streams = set([x for x in probe_out.splitlines() if x.strip()])
                num_audio = len(unique_streams)
                logger.info(f"ffprobe output: '{probe_out.replace(chr(10), ',')}', Unique tracks detected: {num_audio}")
            except Exception as e:
                logger.warning(f"ffprobe failed: {e}")
                num_audio = 1

            if num_audio > 1:
                logger.info(f"Detected {num_audio} audio tracks in TS chunk! Mixing them.")
                filter_inputs = "".join([f"[0:a:{i}]" for i in range(num_audio)])
                filter_str = f"{filter_inputs}amix=inputs={num_audio}:duration=longest[a]"
                
                cmd = [
                    "ffmpeg", "-y", "-i", ts_file,
                    "-filter_complex", filter_str,
                    "-map", "[a]",
                    "-vn", "-acodec", "libmp3lame", "-ac", "1", "-b:a", "64k", final_output_file
                ]
            else:
                logger.info("Only 1 audio track detected. Proceeding with standard extraction.")
                cmd = [
                    "ffmpeg", "-y", "-i", ts_file,
                    "-vn", "-acodec", "libmp3lame", "-ac", "1", "-b:a", "64k", final_output_file
                ]
            
            # Run ffmpeg asynchronously
            ffmpeg_proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            _, ffmpeg_stderr = await ffmpeg_proc.communicate()
            
            # Cleanup temp TS
            if os.path.exists(ts_file):
                os.remove(ts_file)
                
            if ffmpeg_proc.returncode == 0 and os.path.exists(final_output_file):
                mp3_size = os.path.getsize(final_output_file)
                logger.info(f"ffmpeg conversion successful. MP3 size: {mp3_size / 1024:.2f} KB.")
                if mp3_size > 1000:
                    return True, elapsed_secs
                else:
                    logger.warning("MP3 file is too small (likely silent/empty).")
            else:
                stderr_text = ffmpeg_stderr.decode('utf-8') if ffmpeg_stderr else "Unknown error"
                logger.error(f"ffmpeg failed to convert TS to MP3: {stderr_text}")
                
            return False, 0.0

        except aiohttp.ClientError as e:
            logger.warning(f"Network error while fetching M3U8: {e}. Session may have expired. Clearing cache.")
            self.cached_m3u8_url = None
            if os.path.exists(ts_file):
                os.remove(ts_file)
            return False, 0.0
        except Exception as e:
            logger.error(f"Native audio recording failed: {e}")
            self.cached_m3u8_url = None
            if os.path.exists(ts_file):
                os.remove(ts_file)
            return False, 0.0
