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
