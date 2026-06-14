P8_SYSTEM = """
You resolve ambiguity for missing nodes — estimate whether the student implicitly applied a
concept (competent compression) or failed to understand it.
DO NOT modify coverage_matrix. ONLY update confidence_applied for missing nodes.
Output ONLY raw JSON — no markdown fences, no prose.
"""

P8_USER = """
INPUT:
- domain: {domain}
- concept_graph: {concept_graph_json}
- parsed_steps: {parsed_steps_json}
- coverage_matrix: {coverage_matrix_json}
- missing_nodes: {missing_nodes_json}
- inter_node_failures: {inter_node_failures_json}

TASK:
For each node in missing_nodes, update confidence_applied.

RULES:

A) DOWNSTREAM CONSISTENCY:
   Identify nodes that depend on this missing node.
   If downstream nodes are present AND internally consistent
   (not in inter_node_failures): confidence_applied = 0.4–0.6
   If downstream nodes are present BUT inconsistent: 0.1–0.3
   If no downstream nodes attempted: 0.0–0.2

B) INTER-NODE FAILURE OVERRIDE:
   If missing node appears in inter_node_failures as from_node:
   confidence_applied must be <= 0.3

C) BOUNDS:
   0.0 <= confidence_applied <= 0.6 always
   Never exceed 0.6 (unconfirmed by definition)

D) Do NOT add or remove nodes from the list.
   Return the same node_ids, updated values only.

OUTPUT:
{{
  "updated_missing_nodes": [
    {{"node_id": 2, "confidence_applied": 0.15}}
  ],
  "ambiguity_summary": {{
    "likely_skipped": [],
    "likely_misunderstood": []
  }}
}}
"""
