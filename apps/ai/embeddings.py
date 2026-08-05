"""OpenAI-compatible /v1/embeddings client (spec §3). Mirrors client.py:
httpx, no vendor SDK, selected purely by EMBEDDING_* env vars. Every
returned vector is exactly EMBEDDING_DIM floats, L2-normalized; larger
native vectors are Matryoshka-truncated, smaller ones rejected."""

import math

import httpx
from django.conf import settings


class EmbeddingUnavailable(Exception):
    pass


def _l2_normalize(vec):
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _normalize_response(raw, expected_count, dim):
    if len(raw) != expected_count:
        raise EmbeddingUnavailable(
            f"embedding count mismatch: sent {expected_count}, got {len(raw)}"
        )
    vectors = []
    for vec in raw:
        if len(vec) < dim:
            raise EmbeddingUnavailable(
                f"embedding dim {len(vec)} smaller than EMBEDDING_DIM={dim}"
            )
        vectors.append(_l2_normalize(list(vec)[:dim]))
    return vectors


def _post(inputs, _transport=None):
    body = {
        "model": settings.EMBEDDING_MODEL,
        "input": inputs,
        "encoding_format": "float",
    }
    headers = {}
    if settings.EMBEDDING_API_KEY:
        headers["Authorization"] = f"Bearer {settings.EMBEDDING_API_KEY}"
    try:
        with httpx.Client(
            base_url=settings.EMBEDDING_BASE_URL,
            timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
            transport=_transport,
        ) as http:
            response = http.post("/embeddings", json=body, headers=headers)
        response.raise_for_status()
        raw = [item["embedding"] for item in response.json()["data"]]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise EmbeddingUnavailable(str(exc)) from exc
    return _normalize_response(raw, len(inputs), settings.EMBEDDING_DIM)


def embed_documents(texts, _transport=None):
    prefix = settings.EMBEDDING_DOCUMENT_PREFIX
    return _post([f"{prefix}{t}" for t in texts], _transport=_transport)


def embed_query(text, _transport=None):
    prefix = settings.EMBEDDING_QUERY_PREFIX
    return _post([f"{prefix}{text}"], _transport=_transport)[0]
