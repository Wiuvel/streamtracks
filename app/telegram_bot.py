import os
import logging
import requests

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

    def send_message(self, text: str) -> bool:
        if not self.enabled:
            return False
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.debug("Successfully sent message to Telegram.")
                return True
            else:
                logger.error(f"Failed to send message to Telegram: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending message to Telegram: {e}")
            return False

    def send_live_alert(self, channel: str, title: str) -> bool:
        text = (
            f"<b>Стрим начался!</b>\n\n"
            f"Канал: <b>{channel}</b>\n"
            f"Трансляция: <i>{title}</i>\n\n"
            f"<a href='https://twitch.tv/{channel}'>Смотреть на Twitch</a>"
        )
        return self.send_message(text)
        
    def send_track(self, track_full_name: str, spotify_url: str, timecode_sec: float) -> bool:
        # Format timecode
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
            
        return self.send_message(text)
