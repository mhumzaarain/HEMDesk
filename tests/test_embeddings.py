import json

import httpx
import pytest

from apps.ai import embeddings


def ok_response(vectors):
    return httpx.Response(200, json={"data": [{"embedding": v} for v in vectors]})


def capture_transport(captured, vectors):
    def handler(request):
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        return ok_response(vectors)

    return httpx.MockTransport(handler)


def test_embed_documents_prefixes_and_normalizes(settings):
    settings.EMBEDDING_DIM = 3
    captured = {}
    transport = capture_transport(captured, [[3.0, 0.0, 0.0], [0.0, 4.0, 0.0]])
    vectors = embeddings.embed_documents(["alpha", "beta"], _transport=transport)
    assert captured["body"]["input"] == [
        "search_document: alpha",
        "search_document: beta",
    ]
    assert captured["body"]["model"] == settings.EMBEDDING_MODEL
    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def test_embed_query_prefixes_and_returns_single_vector(settings):
    settings.EMBEDDING_DIM = 3
    captured = {}
    transport = capture_transport(captured, [[0.0, 0.0, 2.0]])
    vector = embeddings.embed_query("no oxygen", _transport=transport)
    assert captured["body"]["input"] == ["search_query: no oxygen"]
    assert vector == [0.0, 0.0, 1.0]


def test_matryoshka_truncates_then_renormalizes(settings):
    settings.EMBEDDING_DIM = 2
    transport = capture_transport({}, [[3.0, 4.0, 999.0]])
    [vector] = embeddings.embed_documents(["x"], _transport=transport)
    assert vector == [pytest.approx(0.6), pytest.approx(0.8)]


def test_undersized_vector_rejected(settings):
    settings.EMBEDDING_DIM = 4
    transport = capture_transport({}, [[1.0, 2.0]])
    with pytest.raises(embeddings.EmbeddingUnavailable):
        embeddings.embed_documents(["x"], _transport=transport)


def test_count_mismatch_rejected(settings):
    settings.EMBEDDING_DIM = 2
    transport = capture_transport({}, [[1.0, 0.0]])
    with pytest.raises(embeddings.EmbeddingUnavailable):
        embeddings.embed_documents(["a", "b"], _transport=transport)


def test_http_error_raises_unavailable():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    with pytest.raises(embeddings.EmbeddingUnavailable):
        embeddings.embed_documents(["x"], _transport=transport)


def test_api_key_sent_only_when_set(settings):
    settings.EMBEDDING_DIM = 2
    settings.EMBEDDING_API_KEY = "sekret"
    captured = {}
    embeddings.embed_documents(
        ["x"], _transport=capture_transport(captured, [[1.0, 0.0]])
    )
    assert captured["auth"] == "Bearer sekret"


def test_zero_vector_survives_normalization(settings):
    settings.EMBEDDING_DIM = 2
    transport = capture_transport({}, [[0.0, 0.0]])
    [vector] = embeddings.embed_documents(["x"], _transport=transport)
    assert vector == [0.0, 0.0]
