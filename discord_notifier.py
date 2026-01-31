"""Discord webhook notification service with async background tasks and error handling"""
import os
import requests
from loguru import logger
from typing import Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
load_dotenv()


class DiscordNotifier:
    """Handles Discord webhook notifications with retry logic and error handling"""

    def __init__(self, webhook_url: Optional[str] = None, timeout: int = 10, max_retries: int = 3):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
        self.timeout = timeout
        self.max_retries = max_retries
        self.executor = ThreadPoolExecutor(max_workers=5)

    def send_sync(self, message: str, username: str = "Tetracubed-Fox") -> bool:
        """
        Synchronously send a Discord webhook notification with retry logic.
        Returns True if successful, False otherwise.
        """
        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured, skipping notification")
            return False

        payload = {
            "content": message,
            "username": username
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=self.timeout
                )

                if response.status_code == 204:
                    logger.debug(f"Discord notification sent: {message[:50]}...")
                    return True
                elif response.status_code == 429:
                    # Rate limited
                    retry_after = response.json().get('retry_after', 1)
                    logger.warning(f"Discord rate limited, retry after {retry_after}s")
                    if attempt < self.max_retries:
                        import time
                        time.sleep(retry_after)
                        continue
                else:
                    logger.warning(
                        f"Discord webhook failed (attempt {attempt}/{self.max_retries}): "
                        f"Status {response.status_code}"
                    )

            except requests.exceptions.Timeout:
                logger.warning(
                    f"Discord webhook timeout (attempt {attempt}/{self.max_retries})"
                )
            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Discord webhook error (attempt {attempt}/{self.max_retries}): {e}"
                )
            except Exception as e:
                logger.error(f"Unexpected error sending Discord notification: {e}")
                return False

            if attempt < self.max_retries:
                import time
                time.sleep(1)  # Wait before retry

        logger.error(f"Failed to send Discord notification after {self.max_retries} attempts")
        return False

    async def send_async(self, message: str, username: str = "Tetracubed-Fox") -> bool:
        """
        Asynchronously send a Discord webhook notification in the background.
        Returns immediately without blocking.
        """
        loop = asyncio.get_event_loop()

        def _send():
            return self.send_sync(message, username)

        # Run in background thread pool
        try:
            future = loop.run_in_executor(self.executor, _send)
            # Don't await - let it run in background
            return True
        except Exception as e:
            logger.error(f"Failed to queue Discord notification: {e}")
            return False


# Global instance
notifier = DiscordNotifier()


def notify(message: str, username: str = "Tetracubed-Fox") -> bool:
    """
    Synchronous helper function for Discord notifications.
    Use this for critical notifications where you want to wait for confirmation.
    """
    return notifier.send_sync(message, username)


async def notify_async(message: str, username: str = "Tetracubed-Fox") -> bool:
    """
    Async helper function for Discord notifications.
    Use this for status updates that shouldn't block operations.
    """
    return await notifier.send_async(message, username)
