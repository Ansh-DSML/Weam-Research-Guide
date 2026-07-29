import json

import httpx
import respx

from app.extraction.base import ExtractedEntity, ExtractedRelation, ExtractionResult
from app.extraction.groq_extractor import GROQ_URL, GroqExtractor


def _ok_body(entities=None, relations=None):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"entities": entities or [], "relations": relations or []})
                    }
                }
            ]
        },
    )


@respx.mock
def test_empty_text_makes_zero_http_calls():
    route = respx.post(GROQ_URL)
    extractor = GroqExtractor(api_keys=["k1"], model="test-model")
    result = extractor.extract("   ")
    assert result == ExtractionResult()
    assert route.call_count == 0


@respx.mock
def test_successful_extraction_parses_entities_and_relations():
    respx.post(GROQ_URL).mock(
        return_value=_ok_body(
            entities=[{"name": "Jane Doe", "type": "Person"}],
            relations=[{"source": "Jane Doe", "rel_type": "WORKS_AT", "target": "Acme"}],
        )
    )
    extractor = GroqExtractor(api_keys=["k1"], model="test-model")
    result = extractor.extract("Jane Doe is the CEO of Acme.")
    assert result == ExtractionResult(
        entities=[ExtractedEntity(name="Jane Doe", type="Person")],
        relations=[ExtractedRelation(source="Jane Doe", rel_type="WORKS_AT", target="Acme")],
    )


@respx.mock
def test_invalid_entity_type_and_rel_type_are_dropped():
    respx.post(GROQ_URL).mock(
        return_value=_ok_body(
            entities=[
                {"name": "Jane Doe", "type": "Person"},
                {"name": "Bogus", "type": "NotARealType"},
            ],
            relations=[{"source": "A", "rel_type": "NOT_A_REAL_REL", "target": "B"}],
        )
    )
    extractor = GroqExtractor(api_keys=["k1"], model="test-model")
    result = extractor.extract("some text")
    assert result.entities == [ExtractedEntity(name="Jane Doe", type="Person")]
    assert result.relations == []


@respx.mock
def test_rotation_on_429_succeeds_on_second_key():
    route = respx.post(GROQ_URL)
    route.side_effect = [
        httpx.Response(429, json={"error": "rate limited"}),
        _ok_body(entities=[{"name": "Jane Doe", "type": "Person"}]),
    ]
    extractor = GroqExtractor(api_keys=["k1", "k2"], model="test-model")
    result = extractor.extract("some text")
    assert route.call_count == 2
    assert result.entities == [ExtractedEntity(name="Jane Doe", type="Person")]
    # confirm the second call actually used the second key
    assert route.calls[1].request.headers["authorization"] == "Bearer k2"


@respx.mock
def test_all_keys_exhausted_returns_empty_not_raise():
    respx.post(GROQ_URL).mock(return_value=httpx.Response(429, json={"error": "rate limited"}))
    extractor = GroqExtractor(api_keys=["k1", "k2", "k3"], model="test-model")
    result = extractor.extract("some text")
    assert result == ExtractionResult()  # empty, no exception raised


@respx.mock
def test_malformed_json_response_handled_gracefully():
    respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "not valid json { at all"}}]}
        )
    )
    extractor = GroqExtractor(api_keys=["k1"], model="test-model")
    result = extractor.extract("some text")
    assert result == ExtractionResult()


@respx.mock
def test_network_error_rotates_to_next_key():
    route = respx.post(GROQ_URL)
    route.side_effect = [httpx.ConnectError("boom"), _ok_body(entities=[{"name": "X", "type": "Other"}])]
    extractor = GroqExtractor(api_keys=["k1", "k2"], model="test-model")
    result = extractor.extract("some text")
    assert result.entities == [ExtractedEntity(name="X", type="Other")]


@respx.mock
def test_long_text_is_truncated_before_request_sent():
    route = respx.post(GROQ_URL).mock(return_value=_ok_body())
    extractor = GroqExtractor(api_keys=["k1"], model="test-model")
    huge_text = "A" * 10_000
    extractor.extract(huge_text)
    sent_body = json.loads(route.calls[0].request.content)
    sent_user_message = sent_body["messages"][1]["content"]
    assert len(sent_user_message) <= 4000
