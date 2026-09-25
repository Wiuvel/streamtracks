import os
import logging
import aiohttp

logger = logging.getLogger("telegram")

class TelegramBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not self.token or not self.chat_id:
            logger.warning("Telegram Bot is not fully configured. Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
            self.enabled = False
        else:
            self.enabled = True

    async def send_message(self, text: str) -> int:
        """Sends a message and returns the message_id on success, or None on failure."""
        if not self.enabled:
            return None
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        logger.debug("Successfully sent message to Telegram.")
                        data = await response.json()
                        return data.get("result", {}).get("message_id")
                    else:
                        resp_text = await response.text()
                        logger.error(f"Failed to send message to Telegram: {resp_text}")
                        return None
        except Exception as e:
            logger.error(f"Error sending message to Telegram: {e}")
            return None

    async def delete_message(self, message_id: int) -> bool:
        """Deletes a specific message in the chat."""
        if not self.enabled or not message_id:
            return False
            
        url = f"https://api.telegram.org/bot{self.token}/deleteMessage"
        payload = {
            "chat_id": self.chat_id,
            "message_id": message_id
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    return response.status == 200
        except Exception:
            return False

    async def pin_message(self, message_id: int) -> bool:
        """Pins a specific message in the chat and attempts to delete the system notification."""
        if not self.enabled or not message_id:
            return False
            
        url = f"https://api.telegram.org/bot{self.token}/pinChatMessage"
        payload = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "disable_notification": True
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        logger.debug(f"Successfully pinned message {message_id}.")
                        await self.delete_message(message_id + 1)
                        return True
                    else:
                        resp_text = await response.text()
                        logger.error(f"Failed to pin message: {resp_text}")
                        return False
        except Exception as e:
            logger.error(f"Error pinning message: {e}")
            return False

    async def send_live_alert(self, channel: str, title: str) -> bool:
        import time
        cache_buster = int(time.time())
        text = (
            f"<b>Стрим начался!</b>\n\n"
            f"Канал: <b>{channel}</b>\n"
            f"Трансляция: {title}\n\n"
            f"<a href='https://twitch.tv/{channel}?v={cache_buster}'>Смотреть на Twitch</a>"
        )
        msg_id = await self.send_message(text)
        if msg_id:
            await self.pin_message(msg_id)
            return True
        return False
        
    async def send_track(self, track_full_name: str, spotify_url: str, timecode_sec: float) -> bool:
        time_str = ""
        if timecode_sec and timecode_sec > 0:
            m, s = divmod(int(timecode_sec), 60)
            h, m = divmod(m, 60)
            if h > 0:
                time_str = f" [{h:02d}:{m:02d}:{s:02d}]"
            else:
                time_str = f" [{m:02d}:{s:02d}]"
                
        text = f"<b>{track_full_name}</b>{time_str}\n\n"
        if spotify_url:
            text += f"<a href='{spotify_url}'>Слушать в Spotify</a>"
        else:
            text += f"<i>(В Spotify не найдено)</i>"
            
        return bool(await self.send_message(text))
