P2_SYSTEM = """
You audit ConceptGraphs for completeness and correctness.
DO NOT regenerate the graph. DO NOT solve the problem.
Output ONLY raw JSON — no markdown fences, no prose.
"""

P2_USER = """
INPUT:
- domain: {domain}
- problem_text: {problem_text}
- concept_graph: {concept_graph_json}

CHECKS (report all that apply):

1. MANDATORY COVERAGE
   Verify presence of:
   a. A node with node_type="representation" AND representation_type="diagram"
      covering Free Body Diagram
   b. At least one node_type="transformation" for force decomposition
   c. At least one node_type="equation" for equilibrium
   d. At least one node_type="solution"
   Set mandatory_coverage_satisfied=false if any are absent.

2. REDUNDANCY
   Are any two nodes performing identical concept + operation?
   Report as redundant_step with affected_node_ids.

3. ORPHANS
   Does every non-level-0 node have at least one prerequisite
   that exists in the graph?
   Report missing prerequisites as inconsistency.

4. LEVEL 0
   Does level 0 contain exactly one setup node? Report if not.

SEVERITY:
- critical: missing FBD, missing equilibrium, missing solution, orphaned node
- minor: redundant node, non-critical inconsistency
- none: no issues

OUTPUT:
{{
  "issues": [
    {{
      "type": "missing_step | redundant_step | inconsistency",
      "description": "...",
      "affected_node_ids": []
    }}
  ],
  "severity": "none | minor | critical",
  "mandatory_coverage_satisfied": true
}}
"""
