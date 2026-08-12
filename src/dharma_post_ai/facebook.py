"""Facebook Graph API publisher for Dharma posters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from .config import Settings

LOGGER = logging.getLogger(__name__)


class FacebookPublishingError(RuntimeError):
    """Raised when the Facebook Page photo request is unsuccessful."""


@dataclass(frozen=True, slots=True)
class FacebookPublication:
    """Identifiers returned after Facebook accepts a Page photo post."""

    photo_id: str
    post_id: str | None


class FacebookPagePublisher:
    """Publish JPEG poster bytes and a caption to the configured Facebook Page."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def publish_photo(self, image_bytes: bytes, caption: str) -> FacebookPublication:
        if not image_bytes:
            raise FacebookPublishingError("Poster image bytes are empty.")
        if len(image_bytes) > 10 * 1024 * 1024:
            raise FacebookPublishingError("Poster exceeds the 10 MB upload safety limit.")

        endpoint = (
            f"https://graph.facebook.com/{self._settings.facebook_graph_api_version}/"
            f"{self._settings.facebook_page_id}/photos"
        )
        form = aiohttp.FormData()
        form.add_field("access_token", self._settings.facebook_page_access_token)
        form.add_field("message", caption)
        form.add_field("source", image_bytes, filename="dharma-poster.jpg", content_type="image/jpeg")

        timeout = aiohttp.ClientTimeout(total=60, connect=15, sock_read=45)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(endpoint, data=form) as response,
            ):
                payload = await response.json(content_type=None)
        except TimeoutError as error:
            raise FacebookPublishingError("Facebook publishing request timed out.") from error
        except aiohttp.ClientError as error:
            raise FacebookPublishingError(f"Facebook publishing network error: {error}") from error

        if response.status >= 300:
            message = _error_message(payload)
            raise FacebookPublishingError(f"Facebook API returned HTTP {response.status}: {message}")
        if not isinstance(payload, dict) or not payload.get("id"):
            raise FacebookPublishingError(f"Facebook API returned an unexpected response: {_error_message(payload)}")

        photo_id = str(payload["id"])
        post_id = str(payload["post_id"]) if payload.get("post_id") else None
        LOGGER.info("Facebook Page accepted photo %s", photo_id)
        return FacebookPublication(photo_id=photo_id, post_id=post_id)


def _error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            code = error.get("code")
            return f"{message or 'Unknown Facebook error'} (code={code})"
        return str(payload)[:1000]
    return str(payload)[:1000]
