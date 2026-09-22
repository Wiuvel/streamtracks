from shazamio import Shazam
import logging

logger = logging.getLogger("shazam")

class ShazamAnalyzer:
    def __init__(self):
        self.shazam = Shazam()

    async def analyze_file(self, file_path: str):
        try:
            out = await self.shazam.recognize(file_path)
            
            if 'track' in out and out['track']:
                track_info = out['track']
                return {
                    "title": track_info.get('title'),
                    "artist": track_info.get('subtitle')
                }
            return None
        except Exception as e:
            logger.error(f"Recognition API error: {e}")
            return None
