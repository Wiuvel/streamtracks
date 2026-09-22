import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    print("Starting Spotify authorization...", flush=True)
    
    cache_path = os.getenv("SPOTIFY_CACHE_PATH", "data/.cache")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    
    sp_oauth = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback"),
        scope="playlist-modify-public playlist-modify-private",
        cache_path=cache_path,
        open_browser=False
    )
    
    # Explicitly handle the OAuth flow so we don't rely on spotipy's hidden inputs
    token_info = sp_oauth.get_cached_token()
    
    if not token_info:
        print("\n[!] No valid token found. Authorization required.", flush=True)
        auth_url = sp_oauth.get_authorize_url()
        print(f"\n1. Open this link in your browser:\n\n{auth_url}\n", flush=True)
        print("2. Log in and click 'Agree'.", flush=True)
        print("3. You will be redirected to a blank page (or Connection Refused).", flush=True)
        
        response_url = input("\n4. Paste the ENTIRE redirected URL here: ").strip()
        
        try:
            code = sp_oauth.parse_response_code(response_url)
            token_info = sp_oauth.get_access_token(code, as_dict=False)
            print("[OK] Token saved successfully!\n", flush=True)
        except Exception as e:
            print(f"[ERROR] Failed to parse token: {e}", flush=True)
            return
            
    sp = spotipy.Spotify(auth_manager=sp_oauth)
    
    print("[INFO] Testing Web API access with your Premium account...", flush=True)
    try:
        # Force authentication by making a simple search request
        sp.search(q="test", type="track", limit=1)
        
        print("\n[OK] Authorization SUCCESSFUL!", flush=True)
        print("[OK] Web API Access: OK. Premium status is recognized.", flush=True)
        print("\nYou are ready to deploy the bot.", flush=True)
        
    except SpotifyException as e:
        if e.http_status == 403:
            print("\n[ERROR] Web API Access FAILED (Error 403).", flush=True)
            print("Spotify API returned: 'Active premium subscription required'.", flush=True)
            print("If you recently bought Premium, please wait. Spotify states:", flush=True)
            print("'It can take a few hours before requests are allowed again.'", flush=True)
        else:
            print(f"\n[ERROR] Spotify API Error: {e}", flush=True)
    except Exception as e:
        print(f"\n[ERROR] Unexpected Error: {e}", flush=True)

if __name__ == "__main__":
    main()
