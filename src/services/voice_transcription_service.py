"""
Voice transcription for inbound WhatsApp voice notes.

Uses OpenAI's audio transcription endpoint (Whisper). Cost is billed per
audio minute (not chat tokens), so enabling voice notes adds only a small,
predictable cost; the resulting transcript flows through the normal text
ordering pipeline.
"""

import logging
from typing import Any, Dict, Optional

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)

# whisper-1 supports verbose_json, which returns the detected language too.
_TRANSCRIBE_MODEL = getattr(settings, "VOICE_TRANSCRIBE_MODEL", "whisper-1")
_OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"


def _ext_for_mime(mime_type: str) -> str:
    mime = (mime_type or "").split(";")[0].strip().lower()
    return {
        "audio/ogg": "ogg",
        "audio/opus": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "mp4",
        "audio/m4a": "m4a",
        "audio/x-m4a": "m4a",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/amr": "amr",
    }.get(mime, "ogg")


class VoiceTranscriptionService:
    """Transcribe audio bytes to text via OpenAI Whisper."""

    def __init__(self):
        self.api_key = getattr(settings, "OPENAI_API_KEY", "") or ""

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def transcribe(
        self, audio_bytes: bytes, mime_type: str = "audio/ogg"
    ) -> Dict[str, Any]:
        """
        Returns { success, text, language } where language is an ISO code when
        detected (e.g. 'en', 'sw'). Falls back gracefully on any error.
        """
        if not self.enabled:
            return {"success": False, "error": "OPENAI_API_KEY not configured"}
        if not audio_bytes:
            return {"success": False, "error": "Empty audio"}

        try:
            filename = f"voice.{_ext_for_mime(mime_type)}"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("model", _TRANSCRIBE_MODEL)
                form.add_field("response_format", "verbose_json")
                form.add_field(
                    "file",
                    audio_bytes,
                    filename=filename,
                    content_type=(mime_type or "audio/ogg").split(";")[0],
                )
                async with session.post(
                    _OPENAI_TRANSCRIBE_URL, data=form, headers=headers
                ) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        return {
                            "success": False,
                            "error": data.get("error", {}).get("message", str(data)),
                        }
                    text = (data.get("text") or "").strip()
                    language = (data.get("language") or "").strip().lower()
                    # Whisper returns full language names (e.g. "english"); map common ones to ISO
                    language = _LANGUAGE_NAME_TO_ISO.get(language, language[:2] if language else "")
                    return {"success": True, "text": text, "language": language}
        except Exception as e:
            logger.error(f"[VOICE] Transcription failed: {e}")
            return {"success": False, "error": str(e)}


_LANGUAGE_NAME_TO_ISO = {
    "english": "en",
    "swahili": "sw",
    "kiswahili": "sw",
    "french": "fr",
    "arabic": "ar",
    "spanish": "es",
    "portuguese": "pt",
    "hindi": "hi",
    "somali": "so",
    "amharic": "am",
}


voice_transcription_service = VoiceTranscriptionService()
