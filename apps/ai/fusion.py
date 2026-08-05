"""Reciprocal Rank Fusion (spec §3), ported from openradx/radis#226."""


def rrf_fuse(vec_rank, fts_rank, k=60):
    """vec_rank / fts_rank map chunk_id -> 1-based rank in each retriever.
    Returns (chunk_id, fused_score) sorted by descending score with a
    stable ascending-id tiebreak. Universe is the union of both sides so
    a semantic-only hit still surfaces."""
    all_ids = set(vec_rank) | set(fts_rank)

    def score(cid):
        s = 0.0
        if cid in vec_rank:
            s += 1.0 / (k + vec_rank[cid])
        if cid in fts_rank:
            s += 1.0 / (k + fts_rank[cid])
        return s

    scored = [(cid, score(cid)) for cid in all_ids]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored
