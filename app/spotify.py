import os
import spotipy
import logging
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException

logger = logging.getLogger("spotify")

class SpotifyClient:
    def __init__(self):
        # We no longer need user OAuth or scopes since we only search for tracks!
        self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET")
        ))

    def search_track(self, title: str, artist: str):
        import re
        
        # 1. Try exact search
        query = f"track:{title} artist:{artist}"
        try:
            results = self.sp.search(q=query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            if tracks:
                track = tracks[0]
                return track["id"], track["external_urls"]["spotify"]
                
            # 2. Smart fallback: strip all brackets and parentheses from the title (e.g. "[Mixed]", "(feat. ...)")
            clean_title = re.sub(r'[\(\[].*?[\)\]]', '', title).strip()
            if clean_title and clean_title != title:
                logger.info(f"Exact match failed. Retrying search with cleaned title: '{clean_title}'")
                query = f"track:{clean_title} artist:{artist}"
                results = self.sp.search(q=query, type="track", limit=1)
                tracks = results.get("tracks", {}).get("items", [])
                if tracks:
                    track = tracks[0]
                    return track["id"], track["external_urls"]["spotify"]
                    
            return None, None
        except SpotifyException as e:
            logger.error(f"Search API error [{e.http_status}]: {e.msg}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected search error: {e}")
            return None, None
