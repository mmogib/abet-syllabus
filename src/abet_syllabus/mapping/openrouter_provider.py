"""OpenRouter provider for CLO-PLO mapping.

Uses the OpenRouter API (OpenAI-compatible) to call AI models for mapping
Course Learning Outcomes to Program Learning Outcomes.  The API key is read
from the OPENROUTER_API_KEY environment variable.

No additional dependencies — uses stdlib urllib.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any

from .anthropic_provider import SYSTEM_PROMPT, _build_user_prompt, _parse_response
from .provider import MappingProvider, MappingResult

logger = logging.getLogger(__name__)

# Default model on OpenRouter (cost-effective Claude)
DEFAULT_MODEL = "qwen/qwen3.6-plus:free"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(MappingProvider):
    """CLO-PLO mapping provider using the OpenRouter API.

    The API key must be set in the ``OPENROUTER_API_KEY`` environment variable.
    Keys are never logged, stored in the database, or written to disk.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 2000,
    ) -> None:
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "OpenRouter API key required. Set the OPENROUTER_API_KEY "
                "environment variable or pass api_key to the constructor."
            )

        self._api_key = resolved_key
        self._model = model
        self._max_tokens = max_tokens

    def map_clos_to_plos(
        self,
        course_code: str,
        course_title: str,
        course_description: str | None,
        clos: list[dict],
        plos: list[dict],
    ) -> list[MappingResult]:
        if not clos or not plos:
            return []

        user_prompt = _build_user_prompt(
            course_code, course_title, course_description, clos, plos
        )

        payload = json.dumps({
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/abet-syllabus",
            "X-Title": "ABET Syllabus Generator",
        }

        req = urllib.request.Request(
            OPENROUTER_API_URL, data=payload, headers=headers, method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except TimeoutError:
            raise RuntimeError(
                "OpenRouter API request timed out. The model may be slow or "
                "the connection is unstable. Try again or use a faster model."
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                detail = json.loads(exc.read().decode("utf-8"))
                msg = detail.get("error", {}).get("message", str(exc))
            except Exception:
                msg = str(exc)
            if status == 401:
                raise RuntimeError(
                    "OpenRouter API authentication failed. "
                    "Check your OPENROUTER_API_KEY environment variable."
                )
            elif status == 429:
                raise RuntimeError(
                    "OpenRouter API rate limit exceeded. Please try again later."
                )
            else:
                raise RuntimeError(f"OpenRouter API error (status {status}): {msg}")
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not connect to OpenRouter API: {exc.reason}"
            )

        # Extract response text (OpenAI format)
        choices = body.get("choices", [])
        if not choices:
            logger.warning("Empty response from OpenRouter for %s", course_code)
            return []

        response_text = choices[0].get("message", {}).get("content", "")
        if not response_text:
            logger.warning("Empty content from OpenRouter for %s", course_code)
            return []

        results = _parse_response(response_text)
        logger.info(
            "Mapped %d CLOs for %s: %d mapping suggestions",
            len(clos), course_code, len(results),
        )
        return results
