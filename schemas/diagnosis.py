from typing import List, Literal, Optional

from pydantic import BaseModel, model_validator


class ParsedStep(BaseModel):
    step_id: int
    content: str


class CoverageEntry(BaseModel):
    node_id: int
    mapped: bool
    combined_confidence: float
    propagation_capped: bool = False
    capping_prerequisite_ids: List[int] = []


class MissingNode(BaseModel):
    node_id: int
    confidence_applied: float


class RootDivergence(BaseModel):
    node_id: int
    failure_type: Literal[
        "missing_node", "incorrect_concept",
        "incorrect_application", "input_state_mismatch",
    ]
    level: int
    concept: str


class InterNodeFailure(BaseModel):
    from_node: int
    to_node: int
    issue: str


class DiagnosisOutput(BaseModel):
    concept_graph_id: str
    parsed_steps: List[ParsedStep]
    coverage_matrix: List[CoverageEntry]
    missing_nodes: List[MissingNode]
    surface_divergence_step: Optional[int] = None
    root_divergence: Optional[RootDivergence] = None
    inter_node_failures: List[InterNodeFailure] = []
    error_classification: Literal[
        "conceptual", "assumption",
        "mathematical", "representation", "unit_scale",
    ]
    confidence: float
    feedback: str
    probe_question: Optional[str] = None
    iteration_complete: bool
    animation_key: Optional[str] = None

    @model_validator(mode="after")
    def _validate_diagnosis(self) -> "DiagnosisOutput":
        # 1. confidence in [0.0, 1.0]
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )

        # 2. If iteration_complete=True, probe_question must be None
        if self.iteration_complete and self.probe_question is not None:
            raise ValueError(
                "probe_question must be None when iteration_complete is True"
            )

        # 3. surface_divergence_step must match an existing step_id
        if self.surface_divergence_step is not None:
            valid_ids = {s.step_id for s in self.parsed_steps}
            if self.surface_divergence_step not in valid_ids:
                raise ValueError(
                    f"surface_divergence_step {self.surface_divergence_step} does not "
                    f"match any step_id in parsed_steps: {sorted(valid_ids)}"
                )

        return self
