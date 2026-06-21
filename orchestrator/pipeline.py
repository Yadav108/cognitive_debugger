# Pipeline orchestration — coordinates all LLM calls for one diagnosis turn
import asyncio
import json
import re
import uuid
from datetime import datetime

import httpx
from fastapi import BackgroundTasks
from pydantic import ValidationError

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODELS,
    COVERAGE_THRESHOLD,
    PROPAGATION_CAP_TRIGGER,
    RESOLUTION_THRESHOLD,
    MAX_TURNS,
)
from schemas.concept_graph import ConceptGraph
from schemas.diagnosis import (
    DiagnosisOutput,
    ParsedStep,
    CoverageEntry,
    MissingNode,
    RootDivergence,
    InterNodeFailure,
    TeachingContent,
)
from schemas.session import SessionState
from orchestrator.confidence import compute_final_confidence, should_resolve
from database import insert_llm_call, insert_iteration, insert_backtracking_trace

LLM_BASE_URL = OPENROUTER_BASE_URL
LLM_MODELS = OPENROUTER_MODELS
MAX_PROMPT_TOKENS = 4000
PROMPT_BUDGET_STEPS = (MAX_PROMPT_TOKENS, 3200, 2600)
BACKOFF_BASE_SECONDS = 1.0
MAX_API_RETRIES = 3
MAX_RETRY_DELAY_SECONDS = 12.0


class LLMServiceError(Exception):
    def __init__(self, detail: str, status_code: int = 503, retry_after: int | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


def _approx_tokens(text: str) -> int:
    # Conservative approximation for provider-side token limits.
    return max(1, len(text) // 4) if text else 0


def _truncate_text_tail(text: str, max_tokens: int) -> str:
    if not text:
        return ""
    if _approx_tokens(text) <= max_tokens:
        return text
    keep_chars = max(1, max_tokens * 4)
    return "[TRUNCATED]\n" + text[-keep_chars:]


def _truncate_for_token_budget(system_msg: str, user_msg: str, budget_tokens: int) -> tuple[str, str]:
    # Keep the latest user context ("conversation history") and trim older content first.
    system_budget = max(400, int(budget_tokens * 0.35))
    truncated_system = _truncate_text_tail(system_msg, system_budget)
    remaining = max(200, budget_tokens - _approx_tokens(truncated_system))
    truncated_user = _truncate_text_tail(user_msg, remaining)

    combined = _approx_tokens(truncated_system) + _approx_tokens(truncated_user)
    if combined > budget_tokens:
        overshoot = combined - budget_tokens
        truncated_user = _truncate_text_tail(
            truncated_user,
            max(150, _approx_tokens(truncated_user) - overshoot),
        )

    combined = _approx_tokens(truncated_system) + _approx_tokens(truncated_user)
    if combined > budget_tokens:
        overshoot = combined - budget_tokens
        truncated_system = _truncate_text_tail(
            truncated_system,
            max(120, _approx_tokens(truncated_system) - overshoot),
        )

    return truncated_system, truncated_user


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def list_available_models() -> None:
    """Debug helper — prints configured OpenRouter model list."""
    for model in LLM_MODELS:
        print(f"- {model}")


async def _openrouter_chat_completion(
    system_msg: str,
    user_msg: str,
    max_tokens: int,
) -> str:
    if not OPENROUTER_API_KEY:
        raise LLMServiceError(
            detail="OPENROUTER_API_KEY is not configured.",
            status_code=500,
        )
    if not LLM_MODELS:
        raise LLMServiceError(
            detail="OPENROUTER_MODELS is empty.",
            status_code=500,
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    terminal_errors: list[str] = []
    retry_after_max: int | None = None

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        for model in LLM_MODELS:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
            for attempt in range(MAX_API_RETRIES):
                try:
                    response = await http_client.post(
                        LLM_BASE_URL,
                        headers=headers,
                        json=payload,
                    )
                except httpx.TimeoutException as exc:
                    if attempt < MAX_API_RETRIES - 1:
                        await asyncio.sleep(BACKOFF_BASE_SECONDS * (2 ** attempt))
                        continue
                    raise LLMServiceError(
                        detail=f"OpenRouter request timed out for model '{model}': {exc}",
                        status_code=504,
                    ) from exc

                if response.status_code < 400:
                    data = response.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise LLMServiceError(
                            detail=f"No choices in OpenRouter response: {json.dumps(data)[:500]}",
                            status_code=503,
                        )
                    message = choices[0].get("message", {})
                    return message.get("content", "") or ""

                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                retry_after_max = max(retry_after_max or 0, retry_after or 0)
                detail = response.text[:2000]
                status = response.status_code
                retryable = status in {413, 429, 500, 502, 503, 504}
                if attempt < MAX_API_RETRIES - 1 and retryable:
                    delay = max(
                        min(float(retry_after or 0), MAX_RETRY_DELAY_SECONDS),
                        min(BACKOFF_BASE_SECONDS * (2 ** attempt), MAX_RETRY_DELAY_SECONDS),
                    )
                    await asyncio.sleep(delay)
                    continue

                terminal_errors.append(f"{model} -> {status}: {detail[:220]}")
                break

    detail = "OpenRouter API request failed for all configured models."
    if terminal_errors:
        detail = f"{detail} " + " | ".join(terminal_errors[-3:])
    raise LLMServiceError(
        detail=detail,
        status_code=503,
        retry_after=retry_after_max,
    )


async def _llm_call(
    session_id: str,
    iteration_id: int | None,
    call_name: str,
    system_msg: str,
    user_msg: str,
    background_tasks: BackgroundTasks,
    retry: bool = True,
    max_tokens: int = 8192,
) -> dict | None:
    """Single LLM call: invoke model, parse JSON, log to SQLite.

    On a JSON parse failure the call is retried once (retry=True → retry=False).
    Both the initial failure and the retry attempt are logged independently.
    Returns the parsed dict, or None if both attempts produce unparseable output.
    """
    raw_output = ""
    last_error: LLMServiceError | None = None
    api_errors: list[str] = []
    retry_after: int | None = None
    used_system_msg = system_msg
    used_user_msg = user_msg

    for budget in PROMPT_BUDGET_STEPS:
        truncated_system, truncated_user = _truncate_for_token_budget(
            system_msg, user_msg, budget
        )
        used_system_msg = truncated_system
        used_user_msg = truncated_user
        try:
            raw_output = await _openrouter_chat_completion(
                system_msg=truncated_system,
                user_msg=truncated_user,
                max_tokens=max_tokens,
            )
            break
        except LLMServiceError as e:
            last_error = e
            retry_after = max(retry_after or 0, e.retry_after or 0)
            api_errors.append(f"budget={budget}: {e.detail}")
            print(f"[_llm_call] API Error at budget={budget}: {e.detail}")
            # For 413, shrink prompt budget and retry.
            if e.status_code == 413:
                continue
            break

    if not raw_output and last_error is not None:
        error_message = (
            "Prompt exceeds provider limits after truncation."
            if last_error.status_code == 413
            else last_error.detail
        )
        background_tasks.add_task(
            insert_llm_call,
            {
                "session_id": session_id,
                "iteration_id": iteration_id,
                "call_name": call_name,
                "input_json": json.dumps({"system": used_system_msg, "user": used_user_msg}),
                "raw_output": "",
                "parsed_output_json": None,
                "valid": 0,
                "error_message": api_errors[-1][:1000] if api_errors else error_message[:1000],
                "retry_count": 0,
                "created_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        raise LLMServiceError(
            detail=error_message,
            status_code=last_error.status_code,
            retry_after=retry_after,
        )

    # llama-3.3-70b wraps JSON in markdown fences despite "JSON only" prompts.
    # Try fenced extraction first, then fall back to grabbing the first {...} block.
    _fence = re.search(r"```\w*\s*([\s\S]*?)```", raw_output)
    if _fence:
        raw_output = _fence.group(1).strip()
    else:
        _brace = re.search(r"(\{[\s\S]*\})", raw_output)
        if _brace:
            raw_output = _brace.group(1).strip()

    try:
        parsed = json.loads(raw_output)
    except Exception:
        parsed = None

    background_tasks.add_task(
        insert_llm_call,
        {
            "session_id": session_id,
            "iteration_id": iteration_id,
            "call_name": call_name,
            "input_json": json.dumps({"system": used_system_msg, "user": used_user_msg}),
            "raw_output": raw_output,
            "parsed_output_json": json.dumps(parsed) if parsed else None,
            "valid": 1 if parsed else 0,
            "error_message": None if parsed else "JSON parse failed",
            "retry_count": 0,
            "created_at": datetime.utcnow().isoformat() + "Z",
        },
    )

    if parsed is None and retry and raw_output:
        return await _llm_call(
            session_id, iteration_id, call_name,
            system_msg, user_msg, background_tasks,
            retry=False,
            max_tokens=max_tokens,
        )

    return parsed


def sanitize_graph_prerequisites(data: dict) -> dict:
    """Fix same-level prerequisites by promoting nodes to higher levels.
    Preserves all prerequisite edges — only level values change.
    Iterates until stable (handles chains).
    """
    nodes = data.get("nodes", [])
    node_levels = {n["node_id"]: n["level"] for n in nodes}

    changed = True
    iterations = 0
    while changed and iterations < 20:
        changed = False
        iterations += 1
        for node in nodes:
            nid = node["node_id"]
            current_level = node_levels[nid]
            prereqs = node.get("prerequisites", [])
            if not prereqs:
                continue
            max_prereq_level = max(
                (node_levels.get(p, 0) for p in prereqs), default=-1
            )
            required_level = max_prereq_level + 1
            if required_level > current_level:
                print(
                    f"[sanitize] Node {nid}: promoted level "
                    f"{current_level} → {required_level} "
                    f"(prereq levels: {[node_levels.get(p) for p in prereqs]})"
                )
                node_levels[nid] = required_level
                node["level"] = required_level
                changed = True

    # Compact levels to be contiguous from 0
    unique_levels = sorted(set(node_levels.values()))
    level_remap = {old: new for new, old in enumerate(unique_levels)}
    if level_remap != {lv: lv for lv in unique_levels}:
        for node in nodes:
            node["level"] = level_remap[node["level"]]
        print(f"[sanitize] Level compaction: {level_remap}")

    return data


def _general_approach_from_graph(graph: ConceptGraph) -> list[str]:
    """Derive the reusable solution method from required concept-graph nodes,
    ordered by level — this is the generalizable "how to solve problems
    like this" procedure, already encoded by P1's graph generation.
    """
    return [
        f"{n.concept}: {n.operation}"
        for n in sorted(graph.nodes, key=lambda n: (n.level, n.node_id))
        if n.required
    ]


async def generate_concept_graph(
    session_id: str,
    problem_text: str,
    domain: str,
    problem_image_text: str,
    background_tasks: BackgroundTasks,
) -> ConceptGraph | None:
    """Execute P1 (graph generation) and P2 (self-check).

    P1 asks the LLM to produce a structured ConceptGraph for the problem.
    P2 asks the LLM to verify mandatory coverage and flag critical issues.
    A 'critical' severity or failed mandatory coverage rejects the graph so
    the caller can retry rather than proceeding with a bad scaffold.

    Returns a validated ConceptGraph, or None on any failure.
    """
    from prompts.p1_graph import P1_SYSTEM, P1_USER
    from prompts.p2_selfcheck import P2_SYSTEM, P2_USER

    # --- Call 1: graph generation ---
    result = await _llm_call(
        session_id, None, "P1_graph",
        P1_SYSTEM.format(domain=domain),
        P1_USER.format(
            domain=domain,
            graph_id=str(uuid.uuid4()),
            problem_text=problem_text,
            problem_image_text=problem_image_text or "",
        ),
        background_tasks,
        max_tokens=2048,
    )
    if result is None:
        return None

    try:
        graph = ConceptGraph(**sanitize_graph_prerequisites(result))
    except ValidationError as e:
        print(f"[pipeline] ConceptGraph validation failed: {e}")
        return None

    # --- Call 2: self-check ---
    selfcheck = await _llm_call(
        session_id, None, "P2_selfcheck",
        P2_SYSTEM,
        P2_USER.format(
            domain=domain,
            problem_text=problem_text,
            concept_graph_json=graph.model_dump_json(),
        ),
        background_tasks,
        max_tokens=1024,
    )

    if selfcheck is not None:
        severity = selfcheck.get("severity", "none")
        mandatory_ok = selfcheck.get("mandatory_coverage_satisfied", True)

        if severity == "critical" or not mandatory_ok:
            # llama-3.1-8b-instant hallucinates orphan/structural issues on
            # complex graphs. Verify in Python from the already-validated
            # Pydantic object before trusting P2's rejection.
            required_types = {"representation", "equation", "solution"}
            present_types = {n.node_type for n in graph.nodes}
            missing = required_types - present_types
            if missing:
                print(
                    f"[pipeline] P2 + Python confirm: missing node types {missing}. "
                    f"Rejecting graph."
                )
                return None
            print(
                f"[pipeline] P2 flagged severity={severity}, mandatory_ok={mandatory_ok} "
                f"but Python confirms all required node types present — continuing."
            )

        graph.validation_notes = json.dumps(selfcheck.get("issues", []))

    return graph


async def run_diagnosis(
    session: SessionState,
    student_text: str,
    student_image_text: str,
    domain: str,
    background_tasks: BackgroundTasks,
) -> DiagnosisOutput | None:
    """Execute Calls 3–7 for a single diagnosis turn.

    Call 3 — P3+P4: parse the student solution into steps and map each
              step to concept-graph intent.
    Call 4 — P5:    compute coverage matrix and propagation-capped missing
              nodes against the concept graph.
    Call 5 — P6+P7: identify the surface-level divergence, trace back to
              the root cause node, and collect inter-node failures.
    Call 6 — P8:    resolve ambiguous missing nodes (confidence in [0.4, 0.6]);
              if call fails, the previous missing_nodes list is kept.
    Call 7 — P9+P10+P11: classify the error, generate student feedback, and
              assemble the final structured response.

    Confidence and iteration_complete are computed locally (pure Python)
    after Call 6. The iteration row is persisted to SQLite only after a
    successful DiagnosisOutput assembly, so all LLM call logs for this turn
    carry iteration_id=None.

    Returns DiagnosisOutput, or None on any unrecoverable failure.
    """
    from prompts.p3p4_parse import P3P4_SYSTEM, P3P4_USER
    from prompts.p5_coverage import P5_SYSTEM, P5_USER
    from prompts.p6p7_divergence import P6P7_SYSTEM, P6P7_USER
    from prompts.p8_ambiguity import P8_SYSTEM, P8_USER
    from prompts.p9p10p11_feedback import P7_SYSTEM, P7_USER
    from prompts.p12_teach import P12_SYSTEM, P12_USER

    session_id = session.session_id
    graph = session.concept_graph
    iteration_id = None  # will be set after insert_iteration
    prev_root = (
        session.iterations[-1].root_divergence if session.iterations else None
    )

    # --- Call 3: P3+P4 Parse + Intent Map ---
    result3 = await _llm_call(
        session_id, iteration_id, "P3P4_parse",
        P3P4_SYSTEM,
        P3P4_USER.format(
            domain=domain,
            concept_graph_json=graph.model_dump_json(),
            student_text=student_text,
            student_image_text=student_image_text or "",
        ),
        background_tasks,
    )
    if result3 is None:
        return None

    parsed_steps = [ParsedStep(**s) for s in result3["parsed_steps"]]
    mappings = result3["mappings"]
    modality = result3["modality"]

    # --- Call 4: P5 Coverage + Propagation ---
    result4 = await _llm_call(
        session_id, iteration_id, "P5_coverage",
        P5_SYSTEM,
        P5_USER.format(
            domain=domain,
            concept_graph_json=graph.model_dump_json(),
            parsed_steps_json=json.dumps([s.model_dump() for s in parsed_steps]),
            mappings_json=json.dumps(mappings),
            coverage_threshold=COVERAGE_THRESHOLD,
            propagation_cap_trigger=PROPAGATION_CAP_TRIGGER,
        ),
        background_tasks,
    )
    if result4 is None:
        return None

    coverage_matrix = [CoverageEntry(**e) for e in result4["coverage_matrix"]]
    missing_nodes = [MissingNode(**m) for m in result4["missing_nodes"]]

    # --- Call 5: P6+P7 Divergence + Root Cause ---
    result5 = await _llm_call(
        session_id, iteration_id, "P6P7_divergence",
        P6P7_SYSTEM,
        P6P7_USER.format(
            domain=domain,
            concept_graph_json=graph.model_dump_json(),
            parsed_steps_json=json.dumps([s.model_dump() for s in parsed_steps]),
            coverage_matrix_json=json.dumps([e.model_dump() for e in coverage_matrix]),
            missing_nodes_json=json.dumps([m.model_dump() for m in missing_nodes]),
        ),
        background_tasks,
    )
    if result5 is None:
        return None

    surface_divergence_step = result5.get("surface_divergence_step")
    root_divergence = (
        RootDivergence(**result5["root_divergence"])
        if result5.get("root_divergence")
        else None
    )
    inter_node_failures = [
        InterNodeFailure(**f) for f in result5.get("inter_node_failures", [])
    ]
    backtracking_trace = result5.get("backtracking_trace", [])

    # --- Call 6: P8 Ambiguity Resolution ---
    result6 = await _llm_call(
        session_id, iteration_id, "P8_ambiguity",
        P8_SYSTEM,
        P8_USER.format(
            domain=domain,
            concept_graph_json=graph.model_dump_json(),
            parsed_steps_json=json.dumps([s.model_dump() for s in parsed_steps]),
            coverage_matrix_json=json.dumps([e.model_dump() for e in coverage_matrix]),
            missing_nodes_json=json.dumps([m.model_dump() for m in missing_nodes]),
            inter_node_failures_json=json.dumps(
                [f.model_dump() for f in inter_node_failures]
            ),
        ),
        background_tasks,
    )
    if result6 is not None:
        missing_nodes = [MissingNode(**m) for m in result6["updated_missing_nodes"]]

    # --- Compute confidence + resolve decision ---
    confidence = compute_final_confidence(
        coverage_matrix, missing_nodes, root_divergence,
        inter_node_failures, prev_root,
    )

    current_turn_after = session.current_turn + 1
    max_turns_reached = current_turn_after >= session.max_turns

    iteration_complete = max_turns_reached or should_resolve(
        confidence, root_divergence, prev_root,
        coverage_matrix, missing_nodes,
    )

    # --- Call 7: P9+P10+P11 Classify + Feedback + Assemble ---
    result7 = await _llm_call(
        session_id, iteration_id, "P9P10P11_feedback",
        P7_SYSTEM,
        P7_USER.format(
            domain=domain,
            problem_text=session.problem_text,
            concept_graph_json=graph.model_dump_json(),
            parsed_steps_json=json.dumps([s.model_dump() for s in parsed_steps]),
            coverage_matrix_json=json.dumps([e.model_dump() for e in coverage_matrix]),
            root_divergence_json=(
                root_divergence.model_dump_json() if root_divergence else "null"
            ),
            inter_node_failures_json=json.dumps(
                [f.model_dump() for f in inter_node_failures]
            ),
            updated_missing_nodes_json=json.dumps(
                [m.model_dump() for m in missing_nodes]
            ),
            iteration_complete=str(iteration_complete),
        ),
        background_tasks,
    )
    if result7 is None:
        return None

    # --- Call 8: P12 Teaching Content (only once the student has resolved) ---
    teaching: TeachingContent | None = None
    if iteration_complete:
        result8 = await _llm_call(
            session_id, iteration_id, "P12_teach",
            P12_SYSTEM,
            P12_USER.format(
                domain=domain,
                problem_text=session.problem_text,
                concept_graph_json=graph.model_dump_json(),
                root_divergence_json=(
                    root_divergence.model_dump_json() if root_divergence else "null"
                ),
                error_classification=result7["error_classification"],
                feedback=result7["feedback"],
            ),
            background_tasks,
            max_tokens=2048,
        )
        if result8 is not None:
            try:
                teaching = TeachingContent(
                    concept_summary=result8["concept_summary"],
                    general_approach=_general_approach_from_graph(graph),
                    worked_solution=result8["worked_solution"],
                    common_pitfall=result8["common_pitfall"],
                )
            except (KeyError, ValidationError) as e:
                print(f"[pipeline] TeachingContent assembly failed: {e}")

    # --- Assemble DiagnosisOutput ---
    # DiagnosisOutput.validator requires probe_question=None when iteration_complete=True;
    # null it out here so a chatty LLM response never causes a ValidationError.
    probe_question = result7.get("probe_question") if not iteration_complete else None

    try:
        diagnosis = DiagnosisOutput(
            concept_graph_id=graph.graph_id,
            parsed_steps=parsed_steps,
            coverage_matrix=coverage_matrix,
            missing_nodes=missing_nodes,
            surface_divergence_step=surface_divergence_step,
            root_divergence=root_divergence,
            inter_node_failures=inter_node_failures,
            error_classification=result7["error_classification"],
            confidence=confidence,
            feedback=result7["feedback"],
            probe_question=probe_question,
            iteration_complete=iteration_complete,
            animation_key=None,
            teaching=teaching,
        )
    except ValidationError as e:
        print(f"[pipeline] DiagnosisOutput validation failed: {e}")
        return None

    # --- Persist iteration to SQLite ---
    iteration_id = await insert_iteration({
        "session_id": session_id,
        "turn_index": session.current_turn,
        "parsed_steps_json": json.dumps([s.model_dump() for s in parsed_steps]),
        "coverage_matrix_json": json.dumps([e.model_dump() for e in coverage_matrix]),
        "missing_nodes_json": json.dumps([m.model_dump() for m in missing_nodes]),
        "root_divergence_json": (
            root_divergence.model_dump_json() if root_divergence else None
        ),
        "inter_node_failures_json": json.dumps(
            [f.model_dump() for f in inter_node_failures]
        ),
        "confidence": confidence,
        "iteration_complete": int(iteration_complete),
        "feedback": diagnosis.feedback,
        "probe_question": diagnosis.probe_question,
        "teaching_json": teaching.model_dump_json() if teaching else None,
        "created_at": datetime.utcnow().isoformat() + "Z",
    })

    # --- Persist backtracking trace (non-blocking) ---
    if backtracking_trace:
        background_tasks.add_task(
            insert_backtracking_trace,
            iteration_id,
            json.dumps(backtracking_trace),
        )

    return diagnosis


async def run_teaching_only(
    session_id: str,
    problem_text: str,
    graph: ConceptGraph,
    domain: str,
    background_tasks: BackgroundTasks,
) -> TeachingContent | None:
    """Generate teaching content for a learning guide (without diagnosis).
    
    Skips the full diagnosis pipeline and goes directly to teaching content generation.
    """
    from prompts.p12_teach import P12_SYSTEM, P12_USER
    
    try:
        result = await _llm_call(
            session_id, None, "P12_teach_learn",
            P12_SYSTEM,
            P12_USER.format(
                domain=domain,
                problem_text=problem_text,
                concept_graph_json=graph.model_dump_json(),
                root_divergence_json="null",
                error_classification="conceptual",
                feedback="Learning request - showing how to solve this problem.",
            ),
            background_tasks,
            max_tokens=2048,
        )
        
        if result is None:
            return None
        
        try:
            teaching = TeachingContent(
                concept_summary=result["concept_summary"],
                general_approach=_general_approach_from_graph(graph),
                worked_solution=result["worked_solution"],
                common_pitfall=result["common_pitfall"],
            )
            return teaching
        except (KeyError, ValidationError) as e:
            print(f"[pipeline] TeachingContent assembly failed: {e}")
            return None
    except Exception as e:
        print(f"[pipeline] run_teaching_only failed: {e}")
        return None
