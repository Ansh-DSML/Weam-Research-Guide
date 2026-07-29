from app.extraction.base import ExtractionResult


class NullExtractor:
    """Used when no Groq API keys are configured. The graph still gets fully populated from
    structured fields (graph_mapper.py) at zero cost — this just means free-text notes aren't
    LLM-extracted yet, which is additive enrichment, not a core feature, per the "must work
    with zero API keys configured" requirement."""

    def extract(self, text: str) -> ExtractionResult:
        return ExtractionResult()
