"""Gemini integration for generating Khmer Dharma reflections safely."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types

from .config import Settings
from .models import DharmaContent

LOGGER = logging.getLogger(__name__)

CONTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "title",
        "pali_source",
        "buddhavacana",
        "explanation",
        "reflection_question",
        "hashtags",
    ],
    "properties": {
        "title": {"type": "string"},
        "pali_source": {"type": "string"},
        "buddhavacana": {"type": "string"},
        "explanation": {"type": "string"},
        "reflection_question": {"type": "string"},
        "hashtags": {"type": "string"},
    },
}

SYSTEM_INSTRUCTION = """
You are a careful Khmer-language Buddhist education editor. Generate a short, calm,
non-sectarian Dharma reflection for a Cambodian Facebook audience. Write in clear,
natural Khmer and do not use sensational, fear-based, political, medical, financial,
or partisan claims.

Source integrity is mandatory. Do not invent a Pali Canon source, a Dhammapada verse
number, or a direct quotation of the Buddha. If you are fully certain an exact
canonical reference is correct, state it precisely. Otherwise, set `pali_source` to
`គតិធម៌សម្រាប់ពិចារណា` and make it clear through the wording that the text is a
reflection rather than a direct canonical quote. Never claim that a generated sentence
is a verbatim Buddhavacana when it is not verified.

Return only the requested structured JSON. The content should promote compassion,
mindfulness, non-harm, patience, wisdom, and personal reflection. Do not exceed the
specified fields or introduce HTML.
""".strip()


def _build_prompt(topic: str) -> str:
    sanitized_topic = " ".join(topic.split()) or "សតិ និងសេចក្តីមេត្តា"
    return f"""
Create one Khmer Dharma post on this theme: {sanitized_topic}

Field requirements:
- title: a calm Khmer title, at most 70 Khmer words.
- pali_source: an exact canonical source only if certain; otherwise exactly
  `គតិធម៌សម្រាប់ពិចារណា`.
- buddhavacana: one short teaching or reflection, 1-3 sentences, maximum 220 Khmer words.
- explanation: 2-3 practical sentences, maximum 170 Khmer words.
- reflection_question: one gentle Khmer question, maximum 40 Khmer words.
- hashtags: 3-6 relevant hashtags, including #ព្រះធម៌ and #DharmaPostAI.
""".strip()


class GeminiDharmaGenerator:
    """Generate validated Dharma content with the current Google GenAI Python SDK."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def generate(self, topic: str = "សតិ និងសេចក្តីមេត្តា") -> DharmaContent:
        """Request structured Khmer Dharma content and validate the resulting fields."""
        prompt = _build_prompt(topic)
        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self._settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_json_schema=CONTENT_SCHEMA,
                temperature=0.6,
                max_output_tokens=1600,
            ),
        )
        payload = self._extract_json(response)
        content = DharmaContent.from_gemini(payload, topic=topic)
        LOGGER.info("Generated Dharma content with source label: %s", content.pali_source)
        return content

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any]:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, dict):
            return parsed

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Gemini returned no usable structured content.")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise RuntimeError("Gemini returned invalid JSON despite the structured-output request.") from error
        if not isinstance(payload, dict):
            raise TypeError("Gemini structured output must be a JSON object.")
        return payload
