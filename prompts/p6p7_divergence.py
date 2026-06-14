P6P7_SYSTEM = """
You identify the surface divergence point and root cause of failure in a student's engineering solution.
Reason backward from observable failure to upstream cause.
DO NOT solve the problem. DO NOT generate feedback.
Output ONLY raw JSON — no markdown fences, no prose.
"""

P6P7_USER = """
INPUT:
- domain: {domain}
- concept_graph: {concept_graph_json}
- parsed_steps: {parsed_steps_json}
- coverage_matrix: {coverage_matrix_json}
- missing_nodes: {missing_nodes_json}

DEFINITIONS:
- Surface Divergence: first step where student output becomes
  observably wrong or inconsistent with the node's expected_representation
- Root Divergence: earliest node where a false premise or missing
  concept was silently introduced — may precede surface divergence

TASK A — SURFACE DIVERGENCE:
Scan parsed_steps in order.
Find the first step where:
- The step maps to a node with mapped=false
- OR the step's output is inconsistent with expected_representation
Set surface_divergence_step = that step_id.
If no clear surface failure: null.

TASK B — ROOT CAUSE BACKTRACKING:
From the level containing surface_divergence_step, walk BACKWARD
through levels toward level 0.

At each level check:
1. Is there a missing required node? → root candidate
2. Is there a node with propagation_capped=true?
   → its capping prerequisite is a root candidate
3. Does any node's expected_input_state mismatch
   what prior steps actually produced? → root candidate

ROOT SELECTION PRIORITY:
1. Missing required node (earliest level wins)
2. Input state mismatch
3. Incorrect concept applied
4. Incorrect application of correct concept

DEPTH PREFERENCE — apply before selection:
Prefer the root candidate that is most DOWNSTREAM (highest level / largest
node_id) while still being provably incorrect from the student's explicit
submission. Do NOT backtrack past that node to a prerequisite unless the
downstream node cannot be evaluated at all from the student's work.

A node is "provably incorrect" if:
- The student produced an explicit value or expression for it AND it is wrong
- The student explicitly applied the wrong operation for that node

A node is "unevaluable" only if the student left no trace of it — no
calculation, label, or value that maps to it even partially. In that case,
backtrack one level and apply this rule again.

failure_type values:
- missing_node
- input_state_mismatch
- incorrect_concept
- incorrect_application

TASK C — INTER-NODE FAILURES:
For each consecutive node pair (A → B) where B depends on A:
- If A is missing or low-confidence (<0.5) AND B was attempted:
  → InterNodeFailure with descriptive issue
- If A.expected_input_state defined AND student's input to B
  does not satisfy it: → InterNodeFailure

BACKTRACKING TRACE:
Record your reasoning at each level — used for internal debugging only.

OUTPUT:
{{
  "surface_divergence_step": 3,
  "root_divergence": {{
    "node_id": 2,
    "failure_type": "missing_node",
    "level": 1,
    "concept": "Free Body Diagram"
  }},
  "inter_node_failures": [
    {{
      "from_node": 2,
      "to_node": 3,
      "issue": "Force components derived without verified FBD"
    }}
  ],
  "backtracking_trace": [
    {{
      "level": 2,
      "checked_node_ids": [3, 4],
      "finding": "clean"
    }},
    {{
      "level": 1,
      "checked_node_ids": [2],
      "finding": "root_candidate"
    }}
  ]
}}
"""
