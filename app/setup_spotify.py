import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Load .env explicitly if running standalone
load_dotenv("../.env")

def setup():
    print("=== Spotify Authentication Setup ===")
    
    # Ensure data directory exists
    os.makedirs("/data", exist_ok=True)
    cache_path = os.getenv("SPOTIFY_CACHE_PATH", "/data/.cache")
    
    auth_manager = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback"),
        scope="playlist-modify-public playlist-modify-private",
        cache_path=cache_path,
        open_browser=False
    )
    
    # This will prompt the user to visit a URL and paste the redirect URL back
    token = auth_manager.get_access_token(as_dict=False)
    
    if token:
        print("\nSuccess! Token saved to cache file.")
        print(f"Cache file located at: {cache_path}")
    else:
        print("\nFailed to get token.")

if __name__ == "__main__":
    setup()
