import os
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

def check_telegram(token):
    print("Checking Telegram Bot Token...")
    if not token or "your_telegram" in token:
        print("❌ Telegram Bot Token is missing or invalid.")
        return False
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        if r.status_code == 200:
            print(f"✅ Telegram Bot connected: @{r.json()['result']['username']}")
            return True
        else:
            print("❌ Telegram Bot Token is rejected by Telegram API.")
            return False
    except Exception as e:
        print(f"❌ Telegram API connection error: {e}")
        return False

def check_spotify(client_id, client_secret):
    print("Checking Spotify Credentials...")
    if not client_id or "your_spotify" in client_id:
        print("❌ Spotify Client ID is missing.")
        return False
    # Just checking if the credentials can fetch an app token (Client Credentials flow)
    # Note: user flow requires manual auth, but this validates the ID/Secret
    try:
        from spotipy.oauth2 import SpotifyClientCredentials
        auth = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
        token = auth.get_access_token(as_dict=False)
        if token:
            print("✅ Spotify App credentials are valid.")
            return True
    except Exception as e:
        print(f"❌ Spotify App credentials rejected: {e}")
        return False

def check_twitch(channel):
    print(f"Checking Twitch Channel ({channel})...")
    if not channel or "your_twitch" in channel:
        print("❌ Twitch Channel is missing.")
        return False
    # Simple check if channel exists via HTML fetch
    try:
        r = requests.get(f"https://twitch.tv/{channel}", timeout=5)
        if r.status_code == 200:
            print(f"✅ Twitch channel '{channel}' is accessible.")
            return True
        else:
            print(f"❌ Twitch channel '{channel}' might not exist.")
            return False
    except Exception as e:
        print(f"❌ Twitch connection error: {e}")
        return False

def main():
    load_dotenv()
    
    success = True
    
    print("\n--- StreamTracks Configuration Check ---\n")
    
    # 1. Telegram
    if not check_telegram(os.getenv("TELEGRAM_BOT_TOKEN")):
        success = False
        
    print("")
        
    # 2. Spotify
    if not check_spotify(os.getenv("SPOTIFY_CLIENT_ID"), os.getenv("SPOTIFY_CLIENT_SECRET")):
        success = False
        
    print("")
        
    # 3. Twitch
    if not check_twitch(os.getenv("TWITCH_CHANNEL")):
        success = False
        
    print("\n----------------------------------------")
    if success:
        print("✅ All pre-flight checks passed!")
        exit(0)
    else:
        print("❌ Some checks failed. Please review your .env file.")
        exit(1)

if __name__ == "__main__":
    main()
