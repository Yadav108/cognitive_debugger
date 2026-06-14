P5_SYSTEM = """
You compute node coverage for a ConceptGraph from student step mappings.
DO NOT solve the problem. Compute coverage and propagate confidence mathematically.
Output ONLY raw JSON — no markdown fences, no prose.
"""

P5_USER = """
INPUT:
- domain: {domain}
- concept_graph: {concept_graph_json}
- parsed_steps: {parsed_steps_json}
- mappings: {mappings_json}
- coverage_threshold: {coverage_threshold}
- propagation_cap_trigger: {propagation_cap_trigger}

COMPUTATION RULES:

A) SINGLE MAPPING to a node:
   combined_confidence = that mapping's confidence
   mapped = combined_confidence >= coverage_threshold

B) MULTIPLE MAPPINGS to the same node:
   combined_confidence = 1 - product of (1 - c) for each mapping
   [probabilistic OR]
   mapped = combined_confidence >= coverage_threshold

C) ZERO MAPPINGS:
   combined_confidence = 0.0
   mapped = false
   Do NOT infer coverage.

D) PROPAGATION CAP — apply BEFORE threshold check:
   For each node, check all prerequisite nodes.
   If ANY required prerequisite has combined_confidence < propagation_cap_trigger:
     combined_confidence = min(node_combined_confidence, propagation_cap_trigger)
   Set propagation_capped = true and list capping_prerequisite_ids.

E) MISSING NODES:
   A node is missing if: required=true AND mapped=false
   Estimate confidence_applied (likelihood student implicitly applied it):
   - Downstream steps present and consistent → 0.4–0.6
   - Downstream steps present but inconsistent → 0.1–0.3
   - No downstream steps → 0.0–0.2
   Never exceed 0.6 for missing nodes.

F) REPRESENTATION ALIGNMENT:
   Use representation_type when evaluating mapping plausibility:
   diagram → visual/spatial content only
   equation → symbolic expressions only
   scalar → final numeric values only
   expression → partial symbolic content
   statement → declarative text

G) INTENT MATCHING — apply before scoring confidence:
   Map a student step to a node if the student's calculation is ATTEMPTING
   to perform that node's operation, even if the attempt is incorrect.
   Match on computational intent, not surface vocabulary.

   Examples:
   - "I used 4m as the moment arm" → maps to the perpendicular-distance
     node even if 4m is wrong and the node description says "trigonometric
     projection"
   - "T1 × sin(30°) = 500" → maps to an equilibrium equation node even if
     the equation is missing the second tension term
   - A numeric value stated without derivation → maps to the node whose
     operation produces that type of value

   A step that uses the WRONG value or method for a node still maps to
   that node with reduced confidence (0.3–0.5), not zero.
   Zero confidence is reserved for nodes the student left completely
   untouched — no value, no label, no equation involving that quantity.

OUTPUT:
{{
  "coverage_matrix": [
    {{
      "node_id": 1,
      "mapped": true,
      "combined_confidence": 0.85,
      "propagation_capped": false,
      "capping_prerequisite_ids": []
    }}
  ],
  "missing_nodes": [
    {{"node_id": 2, "confidence_applied": 0.2}}
  ],
  "coverage_summary": {{
    "total_nodes": 6,
    "covered_nodes": 5,
    "missing_required_nodes": 1
  }}
}}

IMPORTANT: coverage_matrix must contain one entry per node in concept_graph.
"""
