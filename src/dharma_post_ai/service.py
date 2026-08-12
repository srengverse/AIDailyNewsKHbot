"""Business workflow for generating, approving, and publishing Dharma posts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .facebook import FacebookPagePublisher
from .gemini_engine import GeminiDharmaGenerator
from .models import DharmaContent, StoredPost
from .poster import DharmaPosterRenderer, RenderedPoster
from .repository import DharmaPostRepository

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """The record and poster generated in one content workflow."""

    post: StoredPost
    poster: RenderedPoster
    was_published: bool


class DailyLimitReached(RuntimeError):
    """Raised when the configured publishing limit has already been reached."""


class DharmaPostService:
    """Coordinates all application components without exposing any API secret."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.generator = GeminiDharmaGenerator(settings)
        self.renderer = DharmaPosterRenderer(settings)
        self.repository = DharmaPostRepository(settings)
        self.publisher = FacebookPagePublisher(settings)

    async def generate(
        self,
        topic: str = "សតិ និងសេចក្តីមេត្តា",
        publish_immediately: bool = False,
    ) -> GenerationResult:
        """Generate a poster and create a Supabase record, optionally publishing it."""
        self.settings.validate_for_generation()
        should_publish = publish_immediately or (
            self.settings.auto_publish and not self.settings.require_approval
        )
        if should_publish:
            self.settings.validate_for_publishing()
            await self._assert_daily_capacity()

        content = await self.generator.generate(topic)
        poster = self.renderer.render(content)
        status = "approved" if should_publish else "pending_review"
        post = await self.repository.create_post(
            content=content,
            status=status,
            poster_path=str(poster.output_path),
            poster_checksum=poster.checksum,
        )
        LOGGER.info("Created Dharma record %s with status %s", post.id, post.status)

        if should_publish:
            await self._publish(content, poster, str(post.id))
            # The returned value is intentionally rebuilt only after the status update.
            return GenerationResult(post=post, poster=poster, was_published=True)
        return GenerationResult(post=post, poster=poster, was_published=False)

    async def publish_approved(self, limit: int | None = None) -> int:
        """Render and publish reviewed posts that were approved in Supabase."""
        self.settings.validate_for_publishing()
        already_published = await self.repository.count_published_today()
        remaining = self.settings.max_daily_posts - already_published
        if remaining <= 0:
            LOGGER.info("Daily publishing limit (%s) has already been reached.", self.settings.max_daily_posts)
            return 0

        posts = await self.repository.get_approved_posts(min(limit or remaining, remaining))
        published_count = 0
        for post in posts:
            try:
                poster = self.renderer.render(post.content)
                await self._publish(post.content, poster, str(post.id))
                published_count += 1
            except Exception as error:  # Record the failure then allow later approved records to continue.
                LOGGER.exception("Publishing approved record %s failed", post.id)
                await self.repository.mark_failed(str(post.id), str(error))
        return published_count

    async def approve(self, post_id: str) -> None:
        """Move one pending post to approved status for the next publishing cycle."""
        self.settings.validate_for_generation()
        await self.repository.approve(post_id)
        LOGGER.info("Approved Dharma record %s", post_id)

    async def scheduled_cycle(self) -> None:
        """Run the daily workflow according to the configured approval policy."""
        LOGGER.info("Starting scheduled DharmaPostAI cycle")
        if self.settings.require_approval:
            count = await self.publish_approved()
            LOGGER.info("Published %s approved Dharma post(s).", count)
            return
        result = await self.generate()
        LOGGER.info("Scheduled generation completed; published=%s", result.was_published)

    async def _assert_daily_capacity(self) -> None:
        published_count = await self.repository.count_published_today()
        if published_count >= self.settings.max_daily_posts:
            raise DailyLimitReached(
                f"The configured daily limit of {self.settings.max_daily_posts} Facebook post(s) has been reached."
            )

    async def _publish(self, content: DharmaContent, poster: RenderedPoster, post_id: str) -> None:
        try:
            publication = await self.publisher.publish_photo(
                poster.image_bytes,
                content.facebook_caption(),
            )
            await self.repository.mark_published(post_id, publication.post_id or publication.photo_id)
        except Exception as error:
            await self.repository.mark_failed(post_id, str(error))
            raise


def poster_file_exists(path: str | None) -> bool:
    """Small helper that may be useful to administrative tools later."""
    return bool(path and Path(path).is_file())
