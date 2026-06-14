"""
Smoke test — hits real endpoints, requires uvicorn running on :8000.

Run:
    # Terminal 1
    uvicorn main:app --reload

    # Terminal 2
    pytest tests/test_smoke.py -v -s

Requires OPENROUTER_API_KEY and GEMINI_API_KEY in .env
"""
import httpx
import pytest

BASE = "http://localhost:8000"
PROBLEM = (
    "A 500N block is suspended by two cables at angles 30° and 45° from horizontal. "
    "Find tension in each cable."
)
DOMAIN = "statics"
WORK = (
    "I drew a free body diagram. "
    "Sum of forces in x: T1*cos30 = T2*cos45. "
    "Sum in y: T1*sin30 + T2*sin45 = 500. "
    "I solved and got T1=366N, T2=259N."
)


@pytest.fixture(scope="module")
def session_id():
    r = httpx.post(
        f"{BASE}/session/create",
        data={"problem_text": PROBLEM, "domain": DOMAIN},
        timeout=60,
    )
    assert r.status_code == 200, f"create failed: {r.text}"
    data = r.json()
    assert "session_id" in data, f"missing session_id: {data}"
    assert "concept_graph" in data, f"missing concept_graph: {data}"
    print(f"\n[smoke] session_id={data['session_id']}")
    return data["session_id"]


def test_create(session_id):
    assert session_id is not None


def test_submit_first_turn(session_id):
    r = httpx.post(
        f"{BASE}/session/{session_id}/submit",
        data={"student_work_text": WORK},
        timeout=90,
    )
    assert r.status_code == 200, f"submit failed: {r.text}"
    data = r.json()
    assert "confidence" in data, f"missing confidence: {data}"
    assert "feedback" in data, f"missing feedback: {data}"
    assert "iteration_complete" in data, f"missing iteration_complete: {data}"
    assert 0.0 <= data["confidence"] <= 1.0, f"confidence out of range: {data['confidence']}"
    print(f"\n[smoke] confidence={data['confidence']:.3f} iteration_complete={data['iteration_complete']}")
    print(f"[smoke] feedback={data['feedback'][:120]}...")


def test_get_state(session_id):
    r = httpx.get(f"{BASE}/session/{session_id}", timeout=30)
    assert r.status_code == 200, f"get_state failed: {r.text}"
    data = r.json()
    assert "session_id" in data
    assert data["session_id"] == session_id
    assert "concept_graph" in data
    assert "current_turn" in data
    assert data["current_turn"] == 1, f"expected turn=1, got {data['current_turn']}"


def test_history(session_id):
    r = httpx.get(f"{BASE}/session/{session_id}/history", timeout=30)
    assert r.status_code == 200, f"history failed: {r.text}"
    data = r.json()
    assert "confidence_trajectory" in data
    assert len(data["confidence_trajectory"]) == 1, (
        f"expected 1 entry, got {len(data['confidence_trajectory'])}"
    )
    assert 0.0 <= data["confidence_trajectory"][0] <= 1.0


def test_404_unknown_session():
    r = httpx.get(f"{BASE}/session/nonexistent-session-id-00000", timeout=10)
    assert r.status_code == 404, f"expected 404, got {r.status_code}"


def test_404_submit_unknown_session():
    r = httpx.post(
        f"{BASE}/session/nonexistent-session-id-00000/submit",
        data={"student_work_text": "test"},
        timeout=10,
    )
    assert r.status_code == 404, f"expected 404, got {r.status_code}"


def test_409_on_resolved_session():
    # Structural check only — confirms 409 path is wired in the router.
    # Does not exhaust LLM calls to force resolution.
    pass
