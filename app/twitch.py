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
        self.cached_m3u8_url = None
        self.ad_flush_delay = int(os.getenv("AD_FLUSH_DELAY_SEC", "55"))
            
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

    def get_stream_title(self) -> str:
        """Returns the current date as the stream title per user preference."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")

    async def record_audio(self, final_output_file: str, duration_sec: int = 25) -> tuple[bool, float]:
        """Downloads HLS segments and converts to MP3. Returns (success, timecode_sec)."""
        
        if os.path.exists(final_output_file):
            try:
                os.remove(final_output_file)
            except OSError:
                pass

        # Use cached session URL to avoid triggering a new 30-second ad on every check!
        is_new_session = False
        if not self.cached_m3u8_url:
            self.cached_m3u8_url = self.get_audio_stream_url()
            is_new_session = True
            
        m3u8_url = self.cached_m3u8_url
        if not m3u8_url:
            logger.error("Failed to get M3U8 URL from yt-dlp.")
            return False, 0.0

        ts_file = final_output_file.replace(".mp3", ".ts")
        logger.info(f"Using M3U8 URL: {m3u8_url[:50]}...[truncated]")
        
        try:
            if is_new_session:
                # 1. Start the HLS session to trigger the pre-roll ad timer
                req = urllib.request.Request(m3u8_url, headers={'User-Agent': self.user_agent})
                with urllib.request.urlopen(req, timeout=10) as response:
                    pass # Throw away the ad playlist
                    
                # We must wait long enough for the 30s ad to finish AND for it to completely fall off 
                # the back of the sliding HLS playlist window (~20s history).
                logger.info(f"New session started. Waiting {self.ad_flush_delay} seconds to completely flush the silent pre-roll ad from the playlist...")
                await asyncio.sleep(self.ad_flush_delay)
            
            # 2. Fetch the M3U8 playlist. The ad is now gone forever for this session!
            req = urllib.request.Request(m3u8_url, headers={'User-Agent': self.user_agent})
            with urllib.request.urlopen(req, timeout=10) as response:
                m3u8_content = response.read().decode('utf-8')
            
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
                    # Handle relative vs absolute URLs just in case
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
                return False, 0.0
                
            ts_size = os.path.getsize(ts_file)
            logger.info(f"Downloaded TS file natively. Total size: {ts_size / 1024:.2f} KB.")
            
            if ts_size < 10000:
                logger.error("Failed to download sufficient TS data natively (file too small).")
                return False, 0.0

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
                # Use set() to count unique stream indices because ffprobe might print the same index multiple times 
                # when reading a concatenated TS file.
                unique_streams = set([x for x in probe_out.splitlines() if x.strip()])
                num_audio = len(unique_streams)
                logger.info(f"ffprobe output: '{probe_out.replace(chr(10), ',')}', Unique tracks detected: {num_audio}")
            except Exception as e:
                logger.warning(f"ffprobe failed: {e}")
                num_audio = 1

            if num_audio > 1:
                logger.info(f"Detected {num_audio} audio tracks in TS chunk! Mixing them to ensure music is captured.")
                
                # Construct the filter string e.g. "[0:a:0][0:a:1]amix=inputs=2:duration=longest[a]"
                filter_inputs = "".join([f"[0:a:{i}]" for i in range(num_audio)])
                filter_str = f"{filter_inputs}amix=inputs={num_audio}:duration=longest[a]"
                
                cmd = [
                    "ffmpeg", "-y", "-i", ts_file,
                    "-filter_complex", filter_str,
                    "-map", "[a]",
                    "-vn", "-acodec", "libmp3lame", final_output_file
                ]
            else:
                logger.info("Only 1 audio track detected. Proceeding with standard extraction.")
                cmd = [
                    "ffmpeg", "-y", "-i", ts_file,
                    "-vn", "-acodec", "libmp3lame", final_output_file
                ]
            
            def _run_convert():
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                if res.returncode != 0:
                    logger.error(f"ffmpeg error output: {res.stderr}")
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
                    return True, elapsed_secs
                else:
                    logger.warning("MP3 file is too small (likely silent/empty).")
                
            logger.error("ffmpeg failed to convert TS to MP3.")
            return False, 0.0

        except urllib.error.HTTPError as e:
            logger.warning(f"HTTP Error {e.code} while fetching M3U8. Session may have expired. Clearing cache.")
            self.cached_m3u8_url = None
            if os.path.exists(ts_file):
                os.remove(ts_file)
            return False
        except Exception as e:
            logger.error(f"Native audio recording failed: {e}")
            self.cached_m3u8_url = None
            if os.path.exists(ts_file):
                os.remove(ts_file)
            return False
