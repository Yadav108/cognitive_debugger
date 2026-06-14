P1_SYSTEM = """
You generate a canonical ConceptGraph for engineering problems.
Domain: {domain}.

Rules:
- DO NOT solve the problem or compute numeric answers.
- Output ONLY raw JSON — no markdown fences, no prose, no explanation.
- Keep field values concise (one phrase, not a paragraph).
"""

P1_USER = """
INPUT:
- domain: {domain}
- graph_id: {graph_id}  [echo this value verbatim in output]
- problem_text: {problem_text}
- problem_image_text: {problem_image_text}

TASK:
Generate a canonical ConceptGraph representing expert reasoning structure.

NODE REQUIREMENTS — each node MUST include all fields:
- node_id: sequential integer starting at 1
- level: integer starting at 0, contiguous
- concept: underlying principle
- operation: action applied using the concept
- expected_representation: observable form in student work
- representation_type: one of [diagram, equation, expression, scalar, statement]
- expected_input_state: what this node expects from prerequisites (string or null)
- validation_question: one question to verify this node (no sub-questions)
- node_type: one of [setup, representation, transformation, equation, solution, interpretation]
- prerequisites: list of node_ids from strictly lower levels only
- is_parallelizable: true only if node can be done in any order within its level
- required: true if essential
- metadata: object with string values using only keys [axis, reference_frame, coordinate_system] or null
- animation_key: null

LEVEL RULES:
- Level 0: system definition only
- Levels are strictly increasing and contiguous (0, 1, 2, ...)
- Each level must have at least one node with required=true
- Every non-level-0 node must have at least one prerequisite

MANDATORY COVERAGE for statics_mechanics:
The graph MUST include nodes covering:
1. System definition (node_type=setup, level=0)
2. Free Body Diagram (node_type=representation, representation_type=diagram)
3. Force decomposition (node_type=transformation) — use is_parallelizable=true for x/y axes
4. Equilibrium equations (node_type=equation) — use is_parallelizable=true for x/y
5. Solving unknowns (node_type=solution)

PARALLELISM RULE:
- Parallel nodes share the same level
- Parallel nodes must NOT depend on each other
- Use parallelism for independent axes only

PREREQUISITE RULES (strictly enforced):
- A node at level N may only list prerequisites from levels 0 to N-1
- A node may NEVER list a same-level node as a prerequisite
- is_parallelizable=true means the node can run concurrently with
  OTHER nodes at the same level — it does NOT mean it depends on them
- If a node needs another node at the same level to complete first,
  they must be placed at different levels instead
- is_parallelizable nodes must have prerequisites=[] OR only reference
  nodes from strictly lower levels

VALIDATION CHECKLIST — verify every node before outputting:
□ Every node's prerequisites list contains only node_ids with
  lower level values than the current node
□ No two nodes at the same level appear in each other's prerequisites
□ Every is_parallelizable=true node has prerequisites=[] or
  prerequisites pointing only to lower levels
□ Levels are contiguous from 0 with no gaps

WRONG (causes validation failure):
  node_id=4, level=1, prerequisites=[1]
  node_id=5, level=1, is_parallelizable=true, prerequisites=[4]  ← INVALID same-level prereq

RIGHT (parallelizable nodes depend only on lower levels):
  node_id=4, level=1, prerequisites=[1]
  node_id=5, level=1, is_parallelizable=true, prerequisites=[1]  ← VALID
  node_id=6, level=1, is_parallelizable=true, prerequisites=[1]  ← VALID

HARD VALIDATION RULES — your output is machine-validated against all of these:
1. node_ids are sequential integers starting at 1 with no gaps: 1, 2, 3, ..., N
2. levels start at 0 and are contiguous with no gaps: 0, 1, 2, ..., M
3. every entry in prerequisites[] must have a level STRICTLY LOWER than the node's level
4. two nodes at the same level must NEVER list each other as prerequisites
5. every level must contain at least one node with required=true
6. node_ids inside prerequisites[] must actually exist in the nodes list
Violating any rule causes total rejection. Double-check before outputting.

OUTPUT — return ONLY this JSON structure:
{{
  "graph_id": "{graph_id}",
  "nodes": [ ... ],
  "validated_by": "llm",
  "validation_notes": null
}}
"""
