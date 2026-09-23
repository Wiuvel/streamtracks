import sys
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

# Append the app directory to sys.path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

from main import consumer_analyze, consumer_notify
from db import Database

class TestStreamTracksPipeline(unittest.IsolatedAsyncioTestCase):
    
    async def test_consumer_analyze_success(self):
        """Test that the analyzer properly processes a chunk, identifies a track, and pushes to notify queue."""
        # Setup mocks
        shazam_mock = AsyncMock()
        shazam_mock.analyze_file.return_value = {"title": "Test Song", "artist": "Test Artist"}
        
        db_mock = AsyncMock(spec=Database)
        db_mock.add_track.return_value = True # Simulate that the track was NOT played this stream yet
        
        analyze_queue = asyncio.Queue()
        notify_queue = asyncio.Queue()
        
        # Push fake data
        await analyze_queue.put({
            "file": "/data/fake_chunk.mp3",
            "timecode_sec": 120.0,
            "stream_id": "test_stream_session"
        })
        
        # Start task
        task = asyncio.create_task(consumer_analyze(shazam_mock, analyze_queue, notify_queue, db_mock))
        
        # Wait for the queue to be processed
        await asyncio.sleep(0.1) 
        
        # Assertions
        self.assertFalse(notify_queue.empty())
        result = await notify_queue.get()
        
        self.assertEqual(result["title"], "Test Song")
        self.assertEqual(result["track_full_name"], "Test Artist - Test Song")
        self.assertEqual(result["stream_id"], "test_stream_session")
        
        db_mock.add_track.assert_called_once_with("Test Song", "Test Artist", "test_stream_session", None)
        
        task.cancel()

    async def test_consumer_analyze_duplicate(self):
        """Test that the analyzer drops the track if it is a duplicate in the same stream."""
        shazam_mock = AsyncMock()
        shazam_mock.analyze_file.return_value = {"title": "Repeat Song", "artist": "Repeat Artist"}
        
        db_mock = AsyncMock(spec=Database)
        db_mock.add_track.return_value = False # Simulate DUPLICATE track
        
        analyze_queue = asyncio.Queue()
        notify_queue = asyncio.Queue()
        
        await analyze_queue.put({
            "file": "/data/fake_chunk_dup.mp3",
            "timecode_sec": 300.0,
            "stream_id": "test_stream_session"
        })
        
        task = asyncio.create_task(consumer_analyze(shazam_mock, analyze_queue, notify_queue, db_mock))
        await asyncio.sleep(0.1)
        
        # Since it's a duplicate, notify queue MUST be empty!
        self.assertTrue(notify_queue.empty())
        
        task.cancel()

    async def test_consumer_notify(self):
        """Test that the notifier queries Spotify and sends to Telegram correctly."""
        spotify_mock = AsyncMock()
        spotify_mock.search_track.return_value = ("spotify123", "https://open.spotify.com/track/123")
        
        telegram_mock = AsyncMock()
        telegram_mock.send_track.return_value = True
        
        db_mock = AsyncMock(spec=Database)
        
        notify_queue = asyncio.Queue()
        await notify_queue.put({
            "title": "Test Song",
            "artist": "Test Artist",
            "track_full_name": "Test Artist - Test Song",
            "timecode_sec": 120.0,
            "stream_id": "test_stream_session"
        })
        
        task = asyncio.create_task(consumer_notify(spotify_mock, db_mock, telegram_mock, notify_queue))
        await asyncio.sleep(0.1)
        
        # Verify telegram was called with exact args
        telegram_mock.send_track.assert_called_once_with(
            "Test Artist - Test Song", 
            "https://open.spotify.com/track/123", 
            120.0
        )
        
        task.cancel()

if __name__ == '__main__':
    unittest.main()
