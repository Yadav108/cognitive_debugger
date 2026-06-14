from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, model_validator


class ConceptNode(BaseModel):
    node_id: int
    level: int
    concept: str
    operation: str
    expected_representation: str
    representation_type: Literal["diagram", "equation", "expression", "scalar", "statement"]
    expected_input_state: Optional[str] = None
    validation_question: str
    node_type: Literal["setup", "representation", "transformation", "equation", "solution", "interpretation"]
    prerequisites: List[int] = []
    is_parallelizable: bool = False
    required: bool = True
    metadata: Optional[Dict[str, str]] = None
    animation_key: Optional[str] = None


class ConceptGraph(BaseModel):
    graph_id: str
    nodes: List[ConceptNode]
    validated_by: Literal["llm", "human"] = "llm"
    validation_notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_graph_structure(self) -> "ConceptGraph":
        nodes = self.nodes
        node_ids = [n.node_id for n in nodes]
        id_to_node: dict[int, ConceptNode] = {n.node_id: n for n in nodes}

        # 1. All node_id values unique
        seen: set[int] = set()
        duplicates: set[int] = set()
        for nid in node_ids:
            (duplicates if nid in seen else seen).add(nid)
        if duplicates:
            raise ValueError(f"Duplicate node_ids found: {sorted(duplicates)}")

        # 2. node_id values sequential 1..N
        n = len(nodes)
        if set(node_ids) != set(range(1, n + 1)):
            raise ValueError(
                f"node_ids must be sequential 1..{n}, got {sorted(node_ids)}"
            )

        # 3. Levels start at 0 and are contiguous
        all_levels = sorted({node.level for node in nodes})
        if all_levels[0] != 0:
            raise ValueError(
                f"Levels must start at 0; minimum level found is {all_levels[0]}"
            )
        if all_levels != list(range(len(all_levels))):
            raise ValueError(
                f"Levels must be contiguous starting at 0; found gaps in {all_levels}"
            )

        # 4. Each level has >= 1 node with required=True
        for lvl in all_levels:
            if not any(node.required for node in nodes if node.level == lvl):
                raise ValueError(
                    f"Level {lvl} has no node with required=True"
                )

        # 5, 6, 7. Per-node prerequisite checks
        for node in nodes:
            for prereq_id in node.prerequisites:
                # 6. Prerequisite node_id must exist in the graph
                if prereq_id not in id_to_node:
                    raise ValueError(
                        f"Node {node.node_id} references prerequisite {prereq_id} "
                        f"which does not exist in the graph"
                    )
                prereq_level = id_to_node[prereq_id].level

                # 5. Prerequisites must reference strictly lower levels
                if prereq_level >= node.level:
                    raise ValueError(
                        f"Node {node.node_id} (level {node.level}) has prerequisite "
                        f"{prereq_id} at level {prereq_level}; prerequisites must be "
                        f"at a strictly lower level"
                    )

                # 7. Parallelizable nodes must have no intra-level prerequisites
                if node.is_parallelizable and prereq_level == node.level:
                    raise ValueError(
                        f"Parallelizable node {node.node_id} (level {node.level}) has "
                        f"intra-level prerequisite {prereq_id} at the same level"
                    )

        return self
