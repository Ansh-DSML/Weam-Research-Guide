"""Real Groq-backed extractor. Groq's API is OpenAI-compatible (chat completions, JSON mode).

Key rotation: on 401/403/429/5xx or a network-level error, try the next key in the list —
a rate-limited or exhausted key must not stall extraction. If every key fails, extraction is
skipped for this save (empty result, never raised) — it's best-effort enrichment layered on
top of a save that has already committed; it must never fail or block the core feature.
"""

import json

import httpx

from app.extraction.base import ExtractedEntity, ExtractedRelation, ExtractionResult
from app.logging_config import get_logger

logger = get_logger("app.extraction.groq")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_TEXT_CHARS = 4000
RETRYABLE_STATUS_CODES = {401, 403, 429}

VALID_ENTITY_TYPES = {"Person", "Tool", "Location", "Competitor", "Theme", "Other"}
VALID_REL_TYPES = {"WORKS_AT", "USES_TOOL", "LOCATED_IN", "COMPETES_WITH", "MENTIONS"}

SYSTEM_PROMPT = (
    "You extract business entities and relationships from research notes about a company. "
    "Return ONLY a JSON object matching this exact schema, no prose, no markdown fences:\n"
    '{"entities": [{"name": string, "type": "Person"|"Tool"|"Location"|"Competitor"|"Theme"|"Other"}], '
    '"relations": [{"source": string, "rel_type": "WORKS_AT"|"USES_TOOL"|"LOCATED_IN"|'
    '"COMPETES_WITH"|"MENTIONS", "target": string}]}\n'
    "If nothing is worth extracting, return empty lists. Never invent facts not present in the text."
)


def _is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES or status_code >= 500


def _to_extraction_result(parsed) -> ExtractionResult:
    entities: list[ExtractedEntity] = []
    for item in parsed.get("entities", []) if isinstance(parsed, dict) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        entity_type = item.get("type")
        if name and entity_type in VALID_ENTITY_TYPES:
            entities.append(ExtractedEntity(name=name, type=entity_type))

    relations: list[ExtractedRelation] = []
    for item in parsed.get("relations", []) if isinstance(parsed, dict) else []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        rel_type = item.get("rel_type")
        if source and target and rel_type in VALID_REL_TYPES:
            relations.append(ExtractedRelation(source=source, rel_type=rel_type, target=target))

    return ExtractionResult(entities=entities, relations=relations)


class GroqExtractor:
    def __init__(self, api_keys: list[str], model: str, client: httpx.Client | None = None, timeout: float = 20.0):
        if not api_keys:
            raise ValueError("GroqExtractor requires at least one API key")
        self._api_keys = api_keys
        self._model = model
        self._client = client or httpx.Client(timeout=timeout)

    def extract(self, text: str) -> ExtractionResult:
        text = (text or "").strip()
        if not text:
            return ExtractionResult()
        text = text[:MAX_TEXT_CHARS]

        for key_index, key in enumerate(self._api_keys):
            try:
                response = self._client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": text},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0,
                    },
                )
            except httpx.HTTPError as e:
                logger.warning(
                    "groq_request_error", extra={"key_index": key_index, "error_type": type(e).__name__}
                )
                continue

            if _is_retryable_status(response.status_code):
                logger.warning(
                    "groq_key_rotating", extra={"key_index": key_index, "status": response.status_code}
                )
                continue

            if response.status_code != 200:
                logger.warning("groq_unexpected_status", extra={"status": response.status_code})
                return ExtractionResult()

            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                parsed = json.loads(content)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                logger.warning("groq_malformed_response", extra={"error_type": type(e).__name__})
                return ExtractionResult()

            return _to_extraction_result(parsed)

        logger.warning("groq_all_keys_exhausted", extra={"key_count": len(self._api_keys)})
        return ExtractionResult()
