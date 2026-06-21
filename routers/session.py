import json
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from config import MAX_TURNS, UPLOADS_PATH
from database import get_iterations, get_session, insert_session, update_session
from orchestrator.image import extract_image_content
from orchestrator.manim_gen import generate_manim_script, render_animation
from orchestrator.pipeline import LLMServiceError, generate_concept_graph, run_diagnosis
from schemas.concept_graph import ConceptGraph
from schemas.diagnosis import (
    CoverageEntry,
    DiagnosisOutput,
    InterNodeFailure,
    MissingNode,
    ParsedStep,
    RootDivergence,
    TeachingContent,
)
from schemas.session import SessionState

router = APIRouter()

# Ephemeral animation state keyed by session_id.
# Resets on server restart — animations are optional UI enhancements only.
_animation_state: dict[str, dict] = {}


async def _reconstruct_session(row: dict) -> SessionState:
    """Rebuild a SessionState from a sessions DB row + its iteration rows.

    DiagnosisOutput stubs use error_classification="conceptual" and
    surface_divergence_step=None for fields not stored in the iterations
    table — pipeline.py only reads root_divergence from prior iterations.
    """
    if not row["concept_graph_json"]:
        raise HTTPException(status_code=422, detail="Session graph missing")
    concept_graph = ConceptGraph(**json.loads(row["concept_graph_json"]))
    iteration_rows = await get_iterations(row["session_id"])

    iterations: list[DiagnosisOutput] = []
    for ir in iteration_rows:
        root_div = (
            RootDivergence(**json.loads(ir["root_divergence_json"]))
            if ir["root_divergence_json"]
            else None
        )
        inter_node_failures = (
            [InterNodeFailure(**f) for f in json.loads(ir["inter_node_failures_json"])]
            if ir["inter_node_failures_json"]
            else []
        )
        coverage_matrix = (
            [CoverageEntry(**e) for e in json.loads(ir["coverage_matrix_json"])]
            if ir["coverage_matrix_json"]
            else []
        )
        missing_nodes = (
            [MissingNode(**m) for m in json.loads(ir["missing_nodes_json"])]
            if ir["missing_nodes_json"]
            else []
        )
        parsed_steps = (
            [ParsedStep(**s) for s in json.loads(ir["parsed_steps_json"])]
            if ir["parsed_steps_json"]
            else []
        )
        teaching = (
            TeachingContent(**json.loads(ir["teaching_json"]))
            if ir["teaching_json"]
            else None
        )

        iterations.append(
            DiagnosisOutput(
                concept_graph_id=concept_graph.graph_id,
                parsed_steps=parsed_steps,
                coverage_matrix=coverage_matrix,
                missing_nodes=missing_nodes,
                surface_divergence_step=None,
                root_divergence=root_div,
                inter_node_failures=inter_node_failures,
                error_classification="conceptual",
                confidence=float(ir["confidence"]),
                feedback=ir["feedback"] or "",
                probe_question=ir["probe_question"],
                iteration_complete=bool(ir["iteration_complete"]),
                animation_key=None,
                teaching=teaching,
            )
        )

    # Derive current_turn from the actual iteration count rather than the DB
    # column. insert_iteration() runs synchronously inside run_diagnosis before
    # the response returns, but update_session(current_turn+1) runs as a
    # background task. Using row["current_turn"] would fail the SessionState
    # validator (current_turn != len(iterations)) on any request that arrives
    # before that background task flushes.
    return SessionState(
        session_id=row["session_id"],
        problem_text=row["problem_text"],
        problem_image_path=row["problem_image_path"],
        concept_graph=concept_graph,
        iterations=iterations,
        current_turn=len(iterations),
        max_turns=row["max_turns"],
        resolved=bool(row["resolved"]),
        final_root_cause=row["final_root_cause"],
        created_at=datetime.fromisoformat(row["created_at"].rstrip("Z")),
        updated_at=datetime.fromisoformat(row["updated_at"].rstrip("Z")),
    )


async def _run_animation(session_id: str, error_classification: str) -> None:
    """Background task: generate Manim script via Groq, render to mp4, update state."""
    try:
        row = await get_session(session_id)
        if row is None:
            _animation_state[session_id].update(
                {"status": "error", "error": "Session not found"}
            )
            return

        iteration_rows = await get_iterations(session_id)
        last_iter = iteration_rows[-1] if iteration_rows else {}
        feedback = (last_iter.get("feedback") or "") if last_iter else ""
        teaching = (
            TeachingContent(**json.loads(last_iter["teaching_json"]))
            if last_iter.get("teaching_json")
            else None
        )

        script = await generate_manim_script(
            problem=row["problem_text"],
            domain=row["domain"],
            root_cause=row["final_root_cause"] or "unknown root cause",
            error_classification=error_classification,
            diagnosis_text=feedback,
            concept_summary=teaching.concept_summary if teaching else "",
            general_approach=teaching.general_approach if teaching else [],
            worked_solution=teaching.worked_solution if teaching else [],
            common_pitfall=teaching.common_pitfall if teaching else "",
        )
        # Store script so the frontend debug viewer can display it
        _animation_state[session_id]["script"] = script

        await render_animation(session_id, script)
        _animation_state[session_id].update({
            "status": "done",
            "url": f"/static/animations/{session_id}.mp4",
        })

    except Exception as exc:
        traceback.print_exc()
        _animation_state[session_id].update({"status": "error", "error": str(exc)})


@router.post("/create")
async def create_session(
    background_tasks: BackgroundTasks,
    problem_text: str = Form(...),
    domain: str = Form(...),
    image: UploadFile | None = File(None),
):
    try:
        session_id = str(uuid.uuid4())

        image_path: str | None = None
        problem_image_text = ""
        if image and image.filename:
            suffix = Path(image.filename).suffix or ".jpg"
            image_path = f"{UPLOADS_PATH}{session_id}{suffix}"
            Path(image_path).write_bytes(await image.read())
            result = await extract_image_content(image_path)
            problem_image_text = result["extracted_text"]

        graph = await generate_concept_graph(
            session_id, problem_text, domain, problem_image_text, background_tasks
        )
        if graph is None:
            raise HTTPException(status_code=500, detail="Concept graph generation failed")

        now = datetime.utcnow().isoformat() + "Z"
        await insert_session({
            "session_id": session_id,
            "problem_text": problem_text,
            "problem_image_path": image_path,
            "concept_graph_json": graph.model_dump_json(),
            "domain": domain,
            "current_turn": 0,
            "max_turns": MAX_TURNS,
            "resolved": 0,
            "final_root_cause": None,
            "created_at": now,
            "updated_at": now,
        })

        return {"session_id": session_id, "concept_graph": graph.model_dump(mode="json")}

    except HTTPException:
        raise
    except LLMServiceError as e:
        headers = {"Retry-After": str(e.retry_after)} if e.retry_after is not None else None
        raise HTTPException(status_code=e.status_code, detail=e.detail, headers=headers)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/submit")
async def submit_work(
    session_id: str,
    background_tasks: BackgroundTasks,
    student_work_text: str = Form(...),
    image: UploadFile | None = File(None),
):
    try:
        row = await get_session(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if bool(row["resolved"]):
            raise HTTPException(status_code=409, detail="Session already resolved")

        session = await _reconstruct_session(row)

        student_image_text = ""
        if image and image.filename:
            suffix = Path(image.filename).suffix or ".jpg"
            student_image_path = (
                f"{UPLOADS_PATH}{session_id}_turn{row['current_turn']}{suffix}"
            )
            Path(student_image_path).write_bytes(await image.read())
            result = await extract_image_content(student_image_path)
            student_image_text = result["extracted_text"]

        diagnosis = await run_diagnosis(
            session, student_work_text, student_image_text, row["domain"], background_tasks
        )
        if diagnosis is None:
            raise HTTPException(status_code=500, detail="Diagnosis pipeline failed")

        # Use session.current_turn (derived from iteration count) as the
        # authoritative value so the background DB write is always consistent
        # even if row["current_turn"] is stale from a prior background task.
        updates: dict = {"current_turn": session.current_turn + 1}
        if diagnosis.iteration_complete:
            updates["resolved"] = 1
            if diagnosis.root_divergence:
                updates["final_root_cause"] = diagnosis.root_divergence.concept

        background_tasks.add_task(update_session, session_id, updates)

        return diagnosis.model_dump(mode="json")

    except HTTPException:
        raise
    except LLMServiceError as e:
        headers = {"Retry-After": str(e.retry_after)} if e.retry_after is not None else None
        raise HTTPException(status_code=e.status_code, detail=e.detail, headers=headers)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/animate")
async def start_animation(
    session_id: str,
    background_tasks: BackgroundTasks,
    error_classification: str = Form("conceptual"),
):
    """Kick off async Manim rendering for the final diagnosis screen.

    Idempotent: a second call while rendering is in progress returns immediately.
    The frontend polls GET /{session_id}/animate/status to check completion.
    """
    row = await get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if _animation_state.get(session_id, {}).get("status") == "rendering":
        return {"status": "rendering", "message": "Already rendering"}

    _animation_state[session_id] = {
        "status": "rendering",
        "url": None,
        "error": None,
        "script": None,
    }
    background_tasks.add_task(_run_animation, session_id, error_classification)
    return {"status": "rendering"}


@router.get("/{session_id}/animate/status")
async def get_animation_status(session_id: str):
    """Return current animation rendering state for a session."""
    row = await get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = _animation_state.get(session_id, {"status": "idle"})
    return {
        "status": state.get("status", "idle"),
        "url": state.get("url"),
        "error": state.get("error"),
        "script": state.get("script"),  # exposed for debug viewer in Streamlit
    }


@router.get("/{session_id}/history")
async def get_session_history(session_id: str):
    try:
        row = await get_session(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        iteration_rows = await get_iterations(session_id)
        return {
            "session_id": session_id,
            "iterations": iteration_rows,
            "confidence_trajectory": [float(ir["confidence"]) for ir in iteration_rows],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}")
async def get_session_state(session_id: str):
    try:
        row = await get_session(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session = await _reconstruct_session(row)
        return session.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/learn")
async def get_learning_guide(session_id: str, background_tasks: BackgroundTasks):
    """Generate teaching content for a problem (learning guide endpoint)."""
    try:
        from orchestrator.pipeline import run_teaching_only
        
        row = await get_session(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = await _reconstruct_session(row)
        domain = row["domain"]
        
        # Generate teaching content directly
        teaching = await run_teaching_only(
            session_id, session.problem_text, session.concept_graph, domain, background_tasks
        )
        
        if teaching is None:
            raise HTTPException(status_code=500, detail="Failed to generate teaching content")
        
        return {"teaching": teaching.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
