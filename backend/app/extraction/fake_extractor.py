"""Deterministic, zero-network extractor used by every automated test — keeps the graph
storage/orchestration logic fully testable without ever touching the real Groq API."""

import re

from app.extraction.base import ExtractedEntity, ExtractionResult

_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b")
_MAX_ENTITIES = 20


class FakeExtractor:
    """Pulls out Title-Case multi-word phrases (e.g. "Jane Doe", "Acme Corp") as `Other`
    entities. Good enough to exercise the pipeline end-to-end; not meant to be smart."""

    def extract(self, text: str) -> ExtractionResult:
        if not text or not text.strip():
            return ExtractionResult()

        seen: set[str] = set()
        entities: list[ExtractedEntity] = []
        for match in _PHRASE_RE.finditer(text):
            phrase = match.group(1)
            if phrase in seen:
                continue
            seen.add(phrase)
            entities.append(ExtractedEntity(name=phrase, type="Other"))
            if len(entities) >= _MAX_ENTITIES:
                break

        return ExtractionResult(entities=entities)
