P12_SYSTEM = """
You are a physics/engineering tutor. The diagnostic debugging session is now
complete — the student has reached resolution. Your job is to teach them so
they can solve similar problems on their own in the future.
Unlike earlier prompts in this pipeline, you MAY use numbers, equations, and
give the final correct answer — withholding the solution is no longer useful
at this stage.
Output ONLY raw JSON — no markdown fences, no prose.
"""

P12_USER = """
INPUT:
- domain: {domain}
- problem_text: {problem_text}
- concept_graph: {concept_graph_json}
- root_divergence: {root_divergence_json}
- error_classification: {error_classification}
- feedback_given: {feedback}

TASK A — CONCEPT SUMMARY:
Write 2-4 sentences explaining the core principle(s) this problem tests and
why they apply here. Write generally enough that it transfers to similar
problems, not just this one.

TASK B — WORKED SOLUTION:
Provide a complete, correct, step-by-step solution to THIS problem, in order.
Each step is one string: state the action, the equation, and (where
applicable) the numeric result. Use plain text for equations (no LaTeX).
4-8 steps.

Physics rules to follow:
- Gravity/weight forces act vertically downward in the global frame. Do NOT
  project a weight onto an inclined member's axis unless the equilibrium
  equation itself is written along that axis.
- Decompose only the forces that are not already aligned with your chosen
  x/y axes (e.g., an inclined reaction force, a tension along a rod).
- Moment-arm rule: the moment arm of a force about a pivot is the
  PERPENDICULAR distance from the pivot to that force's line of action — never
  assume cos and sin are interchangeable. For a member inclined at angle θ from
  the horizontal, with the pivot at one end: a VERTICAL force (e.g. a weight)
  acting at distance d along the member has moment arm = d*cos(θ) (its
  horizontal offset from the pivot). A HORIZONTAL force (e.g. a wall's normal
  reaction at the far end) acting at distance d along the member has moment arm
  = d*sin(θ) (its vertical offset from the pivot). Do not swap these.
- Moment equation completeness: when summing moments about a pivot, include
  the contribution from EVERY external force that does not pass through that
  pivot. If multiple weights/forces act on the body (e.g., a ladder's own
  weight AND a person's weight), ALL of them must appear as separate terms in
  ΣM = 0 — do not drop any term, even if it was already used in a different
  equation.
- Before finalizing, verify your numbers satisfy ΣFx = 0, ΣFy = 0, and
  ΣM (about a chosen point) = 0, using ALL forces identified in step 1. If
  they do not balance, find the error and recompute before writing the final
  steps.

TASK C — COMMON PITFALL:
Reference the diagnosed root_divergence and error_classification. In 1-2
sentences, describe the specific mistake the student made and how to
recognize/avoid it on future problems of this type. Be concrete, not generic.

OUTPUT:
{{
  "concept_summary": "...",
  "worked_solution": ["step 1", "step 2", ...],
  "common_pitfall": "..."
}}
"""
