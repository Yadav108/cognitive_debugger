from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, model_validator

from .concept_graph import ConceptGraph
from .diagnosis import DiagnosisOutput


class SessionState(BaseModel):
    session_id: str
    problem_text: str
    problem_image_path: Optional[str] = None
    concept_graph: ConceptGraph
    iterations: List[DiagnosisOutput] = []
    current_turn: int = 0
    max_turns: int = 3
    resolved: bool = False
    final_root_cause: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _validate_session(self) -> "SessionState":
        # 1. current_turn must equal the number of completed iterations
        if self.current_turn != len(self.iterations):
            raise ValueError(
                f"current_turn ({self.current_turn}) must equal len(iterations) "
                f"({len(self.iterations)})"
            )

        # 2. current_turn must not exceed max_turns
        if self.current_turn > self.max_turns:
            raise ValueError(
                f"current_turn ({self.current_turn}) exceeds max_turns ({self.max_turns})"
            )

        return self

    def update(self, **kwargs) -> "SessionState":
        if "concept_graph" in kwargs:
            raise ValueError(
                "concept_graph is immutable after creation and cannot be updated"
            )
        return self.model_copy(update=kwargs)
