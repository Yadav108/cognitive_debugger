# Pure computation — no IO, no async
from schemas.diagnosis import CoverageEntry, MissingNode, RootDivergence


def compute_final_confidence(
    coverage_matrix: list[CoverageEntry],
    missing_nodes: list[MissingNode],
    root_divergence: RootDivergence | None,
    inter_node_failures: list,
    prev_root_divergence: RootDivergence | None,
) -> float:
    """Aggregate four diagnostic signals into a single confidence score in [0.0, 1.0].

    Signal 1 — Coverage Score (weight 0.4)
        Mean of combined_confidence across every CoverageEntry. Represents
        how completely the learner's steps map onto the concept graph.
        Returns 0.0 for an empty matrix.

    Signal 2 — Root Divergence Clarity (weight 0.3)
        Measures how well-localised and stable the identified root cause is:
          • No root found               → 0.0 (diagnosis incomplete)
          • First turn (no prior)       → 0.7 (found but unconfirmed)
          • Same node as previous turn  → 1.0 (stable across turns)
          • Different node              → 0.3 (shifted — unstable)

    Signal 3 — Ambiguity Penalty (weight 0.2)
        Missing nodes with confidence_applied in [0.4, 0.6] are genuinely
        ambiguous. Each one subtracts 0.3, floored at 0.0.

    Signal 4 — Inter-node Failure Penalty (weight 0.1)
        Each inter-node failure subtracts 0.25, floored at 0.0. Captures
        broken transitions between otherwise-identified nodes.

    Final value is clamped to [0.0, 1.0] and rounded to 4 decimal places.
    """
    # Signal 1 — Coverage Score
    if coverage_matrix:
        coverage_score = (
            sum(e.combined_confidence for e in coverage_matrix) / len(coverage_matrix)
        )
    else:
        coverage_score = 0.0

    # Signal 2 — Root Divergence Clarity
    if root_divergence is None:
        root_score = 0.0
    elif prev_root_divergence is None:
        root_score = 0.7
    elif root_divergence.node_id == prev_root_divergence.node_id:
        root_score = 1.0
    else:
        root_score = 0.3

    # Signal 3 — Ambiguity Penalty
    ambiguous = [m for m in missing_nodes if 0.4 <= m.confidence_applied <= 0.6]
    ambiguity_score = max(0.0, 1.0 - len(ambiguous) * 0.3)

    # Signal 4 — Inter-node Failure Penalty
    failure_score = max(0.0, 1.0 - len(inter_node_failures) * 0.25)

    raw = (
        0.4 * coverage_score
        + 0.3 * root_score
        + 0.2 * ambiguity_score
        + 0.1 * failure_score
    )
    return round(min(max(raw, 0.0), 1.0), 4)


def should_resolve(
    confidence: float,
    root_divergence: RootDivergence | None,
    prev_root_divergence: RootDivergence | None,
    coverage_matrix: list[CoverageEntry],
    missing_nodes: list[MissingNode],
) -> bool:
    """Return True only when every resolution gate passes, checked in strict order.

    Gate 1 — Confidence floor
        A score below 0.8 means the four signals collectively indicate the
        diagnosis is not yet trustworthy enough to close the session.

    Gate 2 — Root cause identified
        Resolution without a localised root divergence is premature; the
        pipeline has not converged on the error source.

    Gate 3 — Root stability across turns
        If a prior turn identified a root and this turn identifies a
        different one, the diagnosis is oscillating. Require stability
        before resolving.

    Gate 4 — No structural ambiguity in coverage
        Any unmapped entry (mapped=False) with combined_confidence < 0.5
        represents a node the pipeline could not place or confidently
        exclude. The session must not close with open structural gaps.

    Gate 5 — No ambiguous missing nodes
        Missing nodes with confidence_applied in [0.4, 0.6] are on the
        fence; the model cannot decide whether they are absent or present.
        At least one such node means the session needs another turn.
    """
    # Gate 1 — Confidence floor
    if confidence < 0.8:
        return False

    # Gate 2 — Root cause must be identified
    if root_divergence is None:
        return False

    # Gate 3 — Root must be stable across turns
    if (
        prev_root_divergence is not None
        and root_divergence.node_id != prev_root_divergence.node_id
    ):
        return False

    # Gate 4 — No unresolved structural gaps in coverage
    for entry in coverage_matrix:
        if not entry.mapped and entry.combined_confidence < 0.5:
            return False

    # Gate 5 — No ambiguous missing nodes
    ambiguous_missing = [m for m in missing_nodes if 0.4 <= m.confidence_applied <= 0.6]
    if ambiguous_missing:
        return False

    return True
