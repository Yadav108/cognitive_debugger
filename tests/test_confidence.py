import pytest
from orchestrator.confidence import compute_final_confidence, should_resolve
from schemas.diagnosis import CoverageEntry, MissingNode, RootDivergence


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def centry(node_id: int, confidence: float, *, mapped: bool = True) -> CoverageEntry:
    return CoverageEntry(
        node_id=node_id,
        mapped=mapped,
        combined_confidence=confidence,
        propagation_capped=False,
        capping_prerequisite_ids=[],
    )


def mnode(node_id: int, confidence_applied: float) -> MissingNode:
    return MissingNode(node_id=node_id, confidence_applied=confidence_applied)


def rdiv(node_id: int) -> RootDivergence:
    return RootDivergence(
        node_id=node_id,
        failure_type="missing_node",
        level=1,
        concept=f"concept_{node_id}",
    )


# ---------------------------------------------------------------------------
# compute_final_confidence
# ---------------------------------------------------------------------------

def test_perfect_coverage_stable_root():
    # All four signals at maximum:
    #   coverage_score = 1.0  (all entries at full confidence)
    #   root_score     = 1.0  (same node_id as previous turn)
    #   ambiguity_score= 1.0  (no missing nodes)
    #   failure_score  = 1.0  (no inter-node failures)
    # raw = 0.4*1 + 0.3*1 + 0.2*1 + 0.1*1 = 1.0
    matrix = [centry(1, 1.0), centry(2, 1.0), centry(3, 1.0)]
    result = compute_final_confidence(
        coverage_matrix=matrix,
        missing_nodes=[],
        root_divergence=rdiv(2),
        inter_node_failures=[],
        prev_root_divergence=rdiv(2),
    )
    assert result >= 0.95


def test_missing_fbd_no_root():
    # coverage_score = 0.0  (single unmapped entry, confidence 0.0)
    # root_score     = 0.0  (root_divergence is None)
    # ambiguity_score= 1.0  (no missing nodes)
    # failure_score  = 1.0  (no failures)
    # raw = 0 + 0 + 0.20 + 0.10 = 0.30
    matrix = [centry(1, 0.0, mapped=False)]
    result = compute_final_confidence(
        coverage_matrix=matrix,
        missing_nodes=[],
        root_divergence=None,
        inter_node_failures=[],
        prev_root_divergence=None,
    )
    assert result < 0.5


def test_first_turn_no_prev_root():
    # root_divergence present but prev_root_divergence=None → root_score = 0.7
    # root contribution = 0.3 * 0.7 = 0.21
    # Isolate by zeroing coverage; keep ambiguity and failure at max:
    #   raw = 0 + 0.21 + 0.20 + 0.10 = 0.51
    result = compute_final_confidence(
        coverage_matrix=[],
        missing_nodes=[],
        root_divergence=rdiv(1),
        inter_node_failures=[],
        prev_root_divergence=None,
    )
    # Verify the root signal contributes exactly 0.21 to the total
    assert result == pytest.approx(0.51, abs=1e-4)


def test_unstable_root():
    # root_divergence.node_id != prev_root_divergence.node_id → root_score = 0.3
    # root contribution = 0.3 * 0.3 = 0.09
    # raw = 0 + 0.09 + 0.20 + 0.10 = 0.39
    result = compute_final_confidence(
        coverage_matrix=[],
        missing_nodes=[],
        root_divergence=rdiv(5),
        inter_node_failures=[],
        prev_root_divergence=rdiv(2),
    )
    assert result == pytest.approx(0.39, abs=1e-4)


def test_ambiguous_missing_nodes():
    # Two missing nodes with confidence_applied=0.5 — both fall in [0.4, 0.6]
    # ambiguity_score = max(0.0, 1.0 - 2 * 0.3) = 0.4
    # ambiguity contribution = 0.2 * 0.4 = 0.08
    # raw = 0 + 0 + 0.08 + 0.10 = 0.18
    nodes = [mnode(1, 0.5), mnode(2, 0.5)]
    result = compute_final_confidence(
        coverage_matrix=[],
        missing_nodes=nodes,
        root_divergence=None,
        inter_node_failures=[],
        prev_root_divergence=None,
    )
    assert result == pytest.approx(0.18, abs=1e-4)


def test_empty_coverage_matrix():
    # coverage_score = 0.0 (empty list)
    # root_score     = 0.0 (no root divergence)
    # ambiguity_score= 1.0, failure_score = 1.0
    # raw = 0 + 0 + 0.20 + 0.10 = 0.30
    result = compute_final_confidence(
        coverage_matrix=[],
        missing_nodes=[],
        root_divergence=None,
        inter_node_failures=[],
        prev_root_divergence=None,
    )
    assert result < 0.4


def test_output_clamped_to_01():
    # combined_confidence=2.0 is a valid float — Pydantic applies no upper bound.
    # coverage_score = 2.0 → raw = 0.4*2.0 + 0.3*1.0 + 0.2*1.0 + 0.1*1.0 = 1.4
    # Without the clamp this would return 1.4; with it the result must be 1.0.
    matrix = [centry(1, 2.0)]
    result = compute_final_confidence(
        coverage_matrix=matrix,
        missing_nodes=[],
        root_divergence=rdiv(1),
        inter_node_failures=[],
        prev_root_divergence=rdiv(1),
    )
    assert result <= 1.0


# ---------------------------------------------------------------------------
# should_resolve
# ---------------------------------------------------------------------------

def test_resolves_when_all_conditions_met():
    # All five gates pass:
    #   confidence=0.85 >= 0.8
    #   root_divergence is not None
    #   same node_id as prev → stable
    #   coverage entry is mapped=True → gate 4 skips it
    #   no missing nodes → no ambiguity
    result = should_resolve(
        confidence=0.85,
        root_divergence=rdiv(3),
        prev_root_divergence=rdiv(3),
        coverage_matrix=[centry(1, 0.9)],
        missing_nodes=[],
    )
    assert result is True


def test_fails_low_confidence():
    # Gate 1: 0.75 < 0.8 → False immediately
    result = should_resolve(
        confidence=0.75,
        root_divergence=rdiv(1),
        prev_root_divergence=rdiv(1),
        coverage_matrix=[],
        missing_nodes=[],
    )
    assert result is False


def test_fails_no_root_divergence():
    # Gate 2: root_divergence=None → False
    result = should_resolve(
        confidence=0.85,
        root_divergence=None,
        prev_root_divergence=None,
        coverage_matrix=[],
        missing_nodes=[],
    )
    assert result is False


def test_fails_unstable_root():
    # Gate 3: root shifts node_id 1 → 4 across turns → False
    result = should_resolve(
        confidence=0.85,
        root_divergence=rdiv(4),
        prev_root_divergence=rdiv(1),
        coverage_matrix=[],
        missing_nodes=[],
    )
    assert result is False


def test_fails_unresolved_structural_ambiguity():
    # Gate 4: mapped=False and combined_confidence=0.3 < 0.5 → False
    result = should_resolve(
        confidence=0.85,
        root_divergence=rdiv(1),
        prev_root_divergence=rdiv(1),
        coverage_matrix=[centry(1, 0.3, mapped=False)],
        missing_nodes=[],
    )
    assert result is False


def test_fails_ambiguous_missing_nodes():
    # Gate 5: confidence_applied=0.5 ∈ [0.4, 0.6] → ambiguous → False
    result = should_resolve(
        confidence=0.85,
        root_divergence=rdiv(1),
        prev_root_divergence=rdiv(1),
        coverage_matrix=[],
        missing_nodes=[mnode(1, 0.5)],
    )
    assert result is False


def test_first_turn_no_prev_root_does_not_block_resolve():
    # Gate 3 only fires when prev_root_divergence is not None.
    # On the first turn prev=None → stability check is skipped entirely → True.
    result = should_resolve(
        confidence=0.85,
        root_divergence=rdiv(2),
        prev_root_divergence=None,
        coverage_matrix=[],
        missing_nodes=[],
    )
    assert result is True
