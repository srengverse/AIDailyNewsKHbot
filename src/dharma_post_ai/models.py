"""Domain models and validation for DharmaPostAI Bot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

PostStatus = Literal["pending_review", "approved", "published", "failed", "rejected"]


class ContentValidationError(ValueError):
    """Raised when Gemini output does not meet the content contract."""


def _required_text(data: dict[str, Any], field_name: str, max_length: int) -> str:
    value = data.get(field_name)
    if not isinstance(value, str):
        raise ContentValidationError(f"Gemini response field '{field_name}' must be a string.")
    normalized = " ".join(value.split())
    if not normalized:
        raise ContentValidationError(f"Gemini response field '{field_name}' cannot be empty.")
    if len(normalized) > max_length:
        raise ContentValidationError(
            f"Gemini response field '{field_name}' is longer than {max_length} characters."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class DharmaContent:
    """Validated content produced by Gemini."""

    topic: str
    title: str
    pali_source: str
    buddhavacana: str
    explanation: str
    reflection_question: str
    hashtags: str

    @classmethod
    def from_gemini(cls, payload: dict[str, Any], topic: str) -> DharmaContent:
        return cls(
            topic=topic,
            title=_required_text(payload, "title", 130),
            pali_source=_required_text(payload, "pali_source", 200),
            buddhavacana=_required_text(payload, "buddhavacana", 850),
            explanation=_required_text(payload, "explanation", 1200),
            reflection_question=_required_text(payload, "reflection_question", 300),
            hashtags=_required_text(payload, "hashtags", 350),
        )

    def facebook_caption(self) -> str:
        """Build a concise Khmer-first caption for a Facebook Page photo post."""
        return (
            f"☸ {self.title}\n\n"
            f"«{self.buddhavacana}»\n\n"
            f"ប្រភព៖ {self.pali_source}\n\n"
            f"ការពិចារណា៖\n{self.explanation}\n\n"
            f"សំណួរសម្រាប់ពិចារណា៖ {self.reflection_question}\n\n"
            f"សូមអនុមោទនា។ សូមឲ្យគ្រប់គ្នាប្រកបដោយសេចក្តីសុខ និងបញ្ញា។\n\n"
            f"{self.hashtags}"
        )


@dataclass(frozen=True, slots=True)
class StoredPost:
    """A content record loaded from Supabase."""

    id: UUID
    content: DharmaContent
    status: PostStatus
    facebook_post_id: str | None
    poster_path: str | None
    attempts: int
    scheduled_for: datetime | None
    published_at: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> StoredPost:
        content = DharmaContent(
            topic=row.get("topic") or "daily_dharma",
            title=row["title"],
            pali_source=row["pali_source"],
            buddhavacana=row["buddhavacana"],
            explanation=row["explanation"],
            reflection_question=row["reflection_question"],
            hashtags=row["hashtags"],
        )
        return cls(
            id=UUID(row["id"]),
            content=content,
            status=row["status"],
            facebook_post_id=row.get("facebook_post_id"),
            poster_path=row.get("poster_path"),
            attempts=int(row.get("attempts") or 0),
            scheduled_for=_parse_datetime(row.get("scheduled_for")),
            published_at=_parse_datetime(row.get("published_at")),
            created_at=_parse_datetime(row["created_at"]),
        )


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)
