import pytest

from apps.ai.fusion import rrf_fuse


def test_union_universe_includes_single_list_hits():
    fused = rrf_fuse({1: 1, 2: 2}, {2: 1, 3: 2})
    ids = [i for i, _ in fused]
    assert set(ids) == {1, 2, 3}
    assert ids[0] == 2  # present in both lists → highest fused score


def test_rank_arithmetic():
    scores = dict(rrf_fuse({1: 1}, {1: 2}))
    assert scores[1] == pytest.approx(1 / 61 + 1 / 62)


def test_tiebreak_ascending_id():
    fused = rrf_fuse({5: 1}, {2: 1})
    assert [i for i, _ in fused] == [2, 5]


def test_empty_inputs():
    assert rrf_fuse({}, {}) == []
