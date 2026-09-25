import os
import re
import logging
import base64
import time
import aiohttp

logger = logging.getLogger("spotify")

class SpotifyClient:
    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        self._access_token = None
        self._token_expires_at = 0
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get_token(self):
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
            
        auth_string = f"{self.client_id}:{self.client_secret}"
        auth_bytes = auth_string.encode("utf-8")
        auth_base64 = base64.b64encode(auth_bytes).decode("utf-8")
        
        headers = {
            "Authorization": f"Basic {auth_base64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"grant_type": "client_credentials"}
        
        session = await self._get_session()
        async with session.post("https://accounts.spotify.com/api/token", headers=headers, data=data) as resp:
            if resp.status == 200:
                resp_json = await resp.json()
                self._access_token = resp_json["access_token"]
                self._token_expires_at = time.time() + resp_json["expires_in"] - 60 # 1 minute buffer
                return self._access_token
            else:
                text = await resp.text()
                logger.error(f"Failed to get Spotify token: {resp.status} {text}")
                return None

    async def _search_api(self, query: str):
        token = await self._get_token()
        if not token:
            return None
            
        headers = {"Authorization": f"Bearer {token}"}
        params = {"q": query, "type": "track", "limit": 1}
        
        session = await self._get_session()
        async with session.get("https://api.spotify.com/v1/search", headers=headers, params=params, timeout=10) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                logger.error(f"Spotify API search failed: {resp.status} {text}")
                return None

    async def search_track(self, title: str, artist: str):
        try:
            # 1. Try exact search with field filters
            query = f"track:{title} artist:{artist}"
            results = await self._search_api(query)
            if results:
                tracks = results.get("tracks", {}).get("items", [])
                if tracks:
                    track = tracks[0]
                    return track["id"], track["external_urls"]["spotify"]
                
            # 2. Smart fallback: strip all brackets and parentheses from the title
            clean_title = re.sub(r'[\(\[].*?[\)\]]', '', title).strip()
            if clean_title and clean_title != title:
                logger.info(f"Exact match failed. Retrying search with cleaned title: '{clean_title}'")
                query = f"track:{clean_title} artist:{artist}"
                results = await self._search_api(query)
                if results:
                    tracks = results.get("tracks", {}).get("items", [])
                    if tracks:
                        track = tracks[0]
                        return track["id"], track["external_urls"]["spotify"]
            
            # 3. Broad fallback: no field filters.
            # Spotify's advanced search sometimes fails if Shazam's metadata differs slightly from Spotify's.
            logger.info("Field match failed. Retrying with broad query.")
            query = f"{title} {artist}"
            results = await self._search_api(query)
            if results:
                tracks = results.get("tracks", {}).get("items", [])
                if tracks:
                    track = tracks[0]
                    return track["id"], track["external_urls"]["spotify"]
                    
            return None, None
        except Exception as e:
            logger.error(f"Unexpected search error: {e}")
            return None, None
            
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
