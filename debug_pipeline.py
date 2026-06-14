"""
Diagnose generate_concept_graph failures.

    python debug_pipeline.py

Runs P1 + P2 with the same inputs as the smoke test and prints exactly
where the pipeline fails so we can fix the root cause.
"""
import asyncio
import json
import re
import uuid

from groq import AsyncGroq
from pydantic import ValidationError

from config import GROQ_API_KEY, GROQ_MODEL
from orchestrator.pipeline import sanitize_graph_prerequisites
from prompts.p1_graph import P1_SYSTEM, P1_USER
from prompts.p2_selfcheck import P2_SYSTEM, P2_USER
from schemas.concept_graph import ConceptGraph

CLIENT = AsyncGroq(api_key=GROQ_API_KEY)
MODEL = GROQ_MODEL
PROBLEM = (
    "A ladder of mass 20 kg and length 4 m leans against a smooth vertical "
    "wall, making an angle of 60° with the horizontal ground. The floor is "
    "rough. A person of mass 70 kg stands 3 m up the ladder. Find the normal "
    "force from the wall and the friction force at the floor."
)
DOMAIN = "statics"


async def raw_call(system: str, user: str, label: str) -> str:
    print(f"\n{'='*60}\n[{label}] Calling Groq...")
    resp = await CLIENT.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=4096,
    )
    choice = resp.choices[0]
    raw = choice.message.content
    finish = choice.finish_reason
    total_tokens = resp.usage.total_tokens if resp.usage else "?"
    print(f"[{label}] finish_reason={finish}  total_tokens={total_tokens}  len(raw)={len(raw)}")
    if finish == "length":
        print(f"[{label}] ⚠️  OUTPUT TRUNCATED — hit max_tokens limit. JSON will be incomplete.")
    print(f"[{label}] First 400 chars:\n{raw[:400]}\n")
    return raw


def try_parse(raw: str, label: str) -> dict | None:
    # Attempt 1: direct parse
    try:
        return json.loads(raw)
    except Exception as e1:
        print(f"[{label}] Direct JSON parse FAILED: {e1}")

    # Attempt 2: strip any markdown fence language tag (```json, ```python, ```, etc.)
    match = re.search(r"```\w*\s*([\s\S]*?)```", raw)
    if match:
        candidate = match.group(1).strip()
        try:
            result = json.loads(candidate)
            print(f"[{label}] JSON parse OK after stripping markdown fences.")
            return result
        except Exception as e2:
            print(f"[{label}] Parse failed after fence stripping: {e2}")
            print(f"[{label}] Stripped candidate (first 300 chars):\n{candidate[:300]}")

    # Attempt 3: find the first { ... } block (handles preamble text + no closing fence)
    brace_match = re.search(r"(\{[\s\S]*\})", raw)
    if brace_match:
        candidate = brace_match.group(1).strip()
        try:
            result = json.loads(candidate)
            print(f"[{label}] JSON parse OK via brace extraction (no fences).")
            return result
        except Exception as e3:
            print(f"[{label}] Brace extraction also failed: {e3}")
            

    print(f"[{label}] ❌ Output is NOT parseable JSON in any form.")
    print(f"[{label}] Full raw output:\n{raw}")
    return None


async def main():
    graph_id = str(uuid.uuid4())

    # ── P1 ────────────────────────────────────────────────────────────────────
    raw1 = await raw_call(
        P1_SYSTEM.format(domain=DOMAIN),
        P1_USER.format(
            domain=DOMAIN,
            graph_id=graph_id,
            problem_text=PROBLEM,
            problem_image_text="",
        ),
        "P1_graph",
    )

    parsed1 = try_parse(raw1, "P1_graph")
    if parsed1 is None:
        print("\n[DIAGNOSIS] ❌ P1 JSON parse failure → pipeline returns None silently (no log).")
        print("[FIX NEEDED] Add JSON-fence stripping to _llm_call, OR update P1_SYSTEM prompt.")
        return

    print("[P1_graph] Attempting ConceptGraph validation...")
    try:
        graph = ConceptGraph(**sanitize_graph_prerequisites(parsed1))
        print(
            f"[P1_graph] ✅ ConceptGraph valid — {len(graph.nodes)} nodes, "
            f"levels={sorted({n.level for n in graph.nodes})}"
        )
    except ValidationError as e:
        print(f"\n[DIAGNOSIS] ❌ ConceptGraph Pydantic validation FAILED:\n{e}")
        print("\nNode ids in LLM output:", [n.get("node_id") for n in parsed1.get("nodes", [])])
        print("Levels in LLM output:   ", [n.get("level") for n in parsed1.get("nodes", [])])
        print("is_parallelizable:      ", [
            (n.get("node_id"), n.get("is_parallelizable"), n.get("prerequisites"))
            for n in parsed1.get("nodes", [])
        ])
        return 

    # ── P2 ────────────────────────────────────────────────────────────────────
    raw2 = await raw_call(
        P2_SYSTEM,
        P2_USER.format(
            domain=DOMAIN,
            problem_text=PROBLEM,
            concept_graph_json=graph.model_dump_json(),
        ),
        "P2_selfcheck",
    )

    parsed2 = try_parse(raw2, "P2_selfcheck")
    if parsed2 is None:
        print("\n[P2] Non-JSON output — pipeline keeps graph. This is NOT the failure.")
    else:
        severity = parsed2.get("severity", "none")
        mandatory_ok = parsed2.get("mandatory_coverage_satisfied", True)
        print(f"[P2] severity={severity}  mandatory_coverage_satisfied={mandatory_ok}")
        if severity == "critical" or not mandatory_ok:
            print(f"\n[DIAGNOSIS] ❌ P2 REJECTED the graph:")
            print(json.dumps(parsed2.get("issues", []), indent=2))
            return
        print("[P2] ✅ Graph accepted by self-check.")

    print("\n[RESULT] ✅ generate_concept_graph would SUCCEED with this input.")


asyncio.run(main())
