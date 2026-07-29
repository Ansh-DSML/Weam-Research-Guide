"""Extractor interface for turning free text into candidate graph entities/relations.

Implementations:
- FakeExtractor  — deterministic, zero network. Used by every automated test.
- GroqExtractor  — real, hits the Groq API. Used by the running app only when
  GROQ_API_KEYS is configured; otherwise the app runs fine without it (structured-field
  mapping alone still populates the graph — text extraction is additive enrichment).
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    type: str


@dataclass(frozen=True)
class ExtractedRelation:
    source: str
    rel_type: str
    target: str


@dataclass(frozen=True)
class ExtractionResult:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)


class Extractor(Protocol):
    def extract(self, text: str) -> ExtractionResult: ...
