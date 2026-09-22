#!/bin/bash
set -e

echo "=== StreamTracks Bot Setup ==="

# Check if docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker could not be found. Please install Docker first."
    echo "curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh"
    exit 1
fi

if [ ! -f .env ]; then
    echo "Creating .env file.."
    cp .env.example .env

    read -p "Enter Twitch Channel to monitor: " twitch_channel
    sed -i "s/TWITCH_CHANNEL=.*/TWITCH_CHANNEL=$twitch_channel/" .env

    read -p "Enter your Twitch OAuth token (auth-token cookie): " twitch_oauth
    sed -i "s/TWITCH_OAUTH_TOKEN=.*/TWITCH_OAUTH_TOKEN=$twitch_oauth/" .env

    echo "---"
    echo "To get Spotify credentials, go to https://developer.spotify.com/dashboard"
    echo "Create an app and add http://localhost:8080/callback to Redirect URIs."
    echo "---"
    read -p "Enter Spotify Client ID: " spotify_client_id
    sed -i "s/SPOTIFY_CLIENT_ID=.*/SPOTIFY_CLIENT_ID=$spotify_client_id/" .env

    read -p "Enter Spotify Client Secret: " spotify_secret
    sed -i "s/SPOTIFY_CLIENT_SECRET=.*/SPOTIFY_CLIENT_SECRET=$spotify_secret/" .env

    read -p "Enter Target Spotify Playlist ID: " spotify_playlist
    sed -i "s/SPOTIFY_PLAYLIST_ID=.*/SPOTIFY_PLAYLIST_ID=$spotify_playlist/" .env
fi

echo "Building Docker image.."
docker compose build

echo "Setting up Spotify Auth.."
# Run the python script interactively to generate the token cache
docker compose run --rm -v $(pwd)/data:/data bot python app/setup_spotify.py

echo "Starting the bot.."
docker compose up -d

echo "=== Setup Complete! ==="
echo "You can check logs with: docker compose logs -f bot"
