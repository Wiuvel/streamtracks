import os
import spotipy
import logging
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

logger = logging.getLogger("spotify")

class SpotifyClient:
    def __init__(self):
        self.playlist_id = os.getenv("SPOTIFY_PLAYLIST_ID")
        cache_path = os.getenv("SPOTIFY_CACHE_PATH", "/data/.cache")
        
        self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback"),
            scope="playlist-modify-public playlist-modify-private",
            cache_path=cache_path,
            open_browser=False
        ))

    def search_track(self, title: str, artist: str):
        query = f"track:{title} artist:{artist}"
        try:
            results = self.sp.search(q=query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            if tracks:
                return tracks[0]["id"]
            return None
        except SpotifyException as e:
            logger.error(f"Search API error [{e.http_status}]: {e.msg}")
            return None
        except Exception as e:
            logger.error(f"Unexpected search error: {e}")
            return None

    def add_to_playlist(self, track_id: str) -> bool:
        if not self.playlist_id:
            logger.error("Configuration missing: SPOTIFY_PLAYLIST_ID")
            return False
            
        try:
            results = self.sp.playlist_items(self.playlist_id, limit=100)
            existing_ids = [item["track"]["id"] for item in results["items"] if item.get("track")]
            
            if track_id in existing_ids:
                logger.debug("Track duplicate found in recent playlist history.")
                return False
                
            self.sp.playlist_add_items(self.playlist_id, [track_id])
            return True
        except SpotifyException as e:
            logger.error(f"Playlist API error [{e.http_status}]: {e.msg}")
            return False
        except Exception as e:
            logger.error(f"Unexpected playlist error: {e}")
            return False
