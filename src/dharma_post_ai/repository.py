"""Supabase repository for Dharma post lifecycle records."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time
from typing import Any, TypeVar

from postgrest.exceptions import APIError

from supabase import Client, create_client

from .config import Settings
from .models import DharmaContent, StoredPost

QueryResult = TypeVar("QueryResult")


class SupabaseSchemaError(RuntimeError):
    """Raised when the required DharmaPostAI database schema is not installed."""


class DharmaPostRepository:
    """Server-side data access for the dharma_posts Supabase table."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    async def _execute(self, operation: Callable[[], QueryResult]) -> QueryResult:
        try:
            return await asyncio.to_thread(operation)
        except APIError as error:
            message = str(error)
            if "PGRST205" in message or (
                "dharma_posts" in message and "schema cache" in message.lower()
            ):
                raise SupabaseSchemaError(
                    "Supabase cannot find public.dharma_posts. Run "
                    "supabase/migrations/001_create_dharma_posts.sql in Supabase Dashboard → SQL Editor, "
                    "then redeploy or trigger one new Render run."
                ) from error
            raise

    async def count_published_today(self) -> int:
        """Return the number of posts published since midnight in the configured timezone."""
        now = datetime.now(self._settings.timezone)
        day_start = datetime.combine(now.date(), time.min, tzinfo=self._settings.timezone)
        response = await self._execute(
            lambda: self._client.table("dharma_posts")
            .select("id", count="exact")
            .eq("status", "published")
            .gte("published_at", day_start.isoformat())
            .execute()
        )
        return int(response.count or 0)

    async def create_post(
        self,
        content: DharmaContent,
        status: str,
        poster_path: str,
        poster_checksum: str,
        scheduled_for: datetime | None = None,
    ) -> StoredPost:
        row: dict[str, Any] = {
            "topic": content.topic,
            "title": content.title,
            "pali_source": content.pali_source,
            "buddhavacana": content.buddhavacana,
            "explanation": content.explanation,
            "reflection_question": content.reflection_question,
            "hashtags": content.hashtags,
            "status": status,
            "poster_path": poster_path,
            "poster_checksum": poster_checksum,
        }
        if scheduled_for is not None:
            row["scheduled_for"] = scheduled_for.isoformat()

        response = await self._execute(
            lambda: self._client.table("dharma_posts").insert(row).execute()
        )
        if not response.data:
            raise RuntimeError("Supabase did not return the created Dharma post.")
        return StoredPost.from_row(response.data[0])

    async def get_approved_posts(self, limit: int) -> list[StoredPost]:
        response = await self._execute(
            lambda: self._client.table("dharma_posts")
            .select("*")
            .eq("status", "approved")
            .order("created_at")
            .limit(limit)
            .execute()
        )
        return [StoredPost.from_row(row) for row in response.data or []]

    async def mark_published(self, post_id: str, facebook_post_id: str) -> None:
        now = datetime.now(self._settings.timezone).isoformat()
        await self._execute(
            lambda: self._client.table("dharma_posts")
            .update(
                {
                    "status": "published",
                    "facebook_posted": True,
                    "facebook_post_id": facebook_post_id,
                    "published_at": now,
                    "last_error": None,
                    "attempts": 1,
                }
            )
            .eq("id", post_id)
            .execute()
        )

    async def mark_failed(self, post_id: str, error_message: str) -> None:
        await self._execute(
            lambda: self._client.rpc(
                "record_dharma_post_failure",
                {"post_uuid": post_id, "failure_message": error_message[:1500]},
            ).execute()
        )

    async def approve(self, post_id: str) -> None:
        await self._execute(
            lambda: self._client.table("dharma_posts")
            .update({"status": "approved", "last_error": None})
            .eq("id", post_id)
            .eq("status", "pending_review")
            .execute()
        )
