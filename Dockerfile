FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (ffmpeg is useful for audio processing, though we try to avoid it directly, some streamlink/shazam features might need it)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Disable python output buffering so logs show up immediately
ENV PYTHONUNBUFFERED=1

# We map a volume to /data in docker-compose
CMD ["python", "app/main.py"]
