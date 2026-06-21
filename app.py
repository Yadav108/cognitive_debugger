import time

import httpx
import streamlit as st

API_BASE = "http://localhost:8000/session"
API_HOST = "http://localhost:8000"
# Session creation can take longer because it runs concept-graph generation + self-check.
REQUEST_TIMEOUT = 120.0
CREATE_SESSION_TIMEOUT = 300.0
DOMAINS = ["statics", "dynamics", "circuits", "thermodynamics", "general"]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _post(url: str, data: dict, files: dict | None = None, timeout: float = REQUEST_TIMEOUT):
    with httpx.Client(timeout=timeout) as client:
        return client.post(url, data=data, files=files)


def _get(url: str):
    with httpx.Client(timeout=30.0) as client:
        return client.get(url)


# ── State init ────────────────────────────────────────────────────────────────

def _init():
    defaults = {
        "view": "create",
        "session_id": None,
        "problem_text": None,
        "domain": None,
        "current_turn": 0,
        "last_diagnosis": None,
        # Animation state
        "anim_polling": False,
        "anim_url": None,
        "anim_error": None,
        "anim_script": None,
        # Learning guide state
        "learn_session_id": None,
        "learn_anim_polling": False,
        "learn_anim_url": None,
        "learn_anim_error": None,
        "learn_anim_script": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init()

st.set_page_config(page_title="Cognitive Debugger", layout="centered")
st.title("Cognitive Debugger")

# ── View 1 — Submit Problem ───────────────────────────────────────────────────

if st.session_state.view == "create":
    tab1, tab2 = st.tabs(["📝 Analyze Problem", "📚 Learn Solution"])
    
    with tab1:
        st.subheader("Submit a Problem")

        problem_text = st.text_area("Problem statement", height=150)
        domain = st.selectbox("Domain", DOMAINS)
        image_file = st.file_uploader(
            "Problem diagram (optional)", type=["png", "jpg", "jpeg"]
        )

        if st.button("Analyze Problem", type="primary"):
            if not problem_text.strip():
                st.error("Problem statement is required.")
            else:
                with st.spinner("Building concept graph…"):
                    try:
                        files = (
                            {"image": (image_file.name, image_file.getvalue(), "image/jpeg")}
                            if image_file
                            else None
                        )
                        resp = _post(
                            f"{API_BASE}/create",
                            data={"problem_text": problem_text, "domain": domain},
                            files=files,
                            timeout=CREATE_SESSION_TIMEOUT,
                        )
                        resp.raise_for_status()
                        payload = resp.json()
                        st.session_state.session_id = payload["session_id"]
                        st.session_state.problem_text = problem_text
                        st.session_state.domain = domain
                        st.session_state.view = "submit"
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to create session: {exc}")
    
    with tab2:
        st.subheader("Learn How to Solve a Problem")
        st.markdown("Enter a problem and select available solving methods to learn the solution step by step.")
        
        learning_problem = st.text_area("Problem statement", height=150, key="learn_problem")
        learning_domain = st.selectbox("Domain", DOMAINS, key="learn_domain")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            show_concept = st.checkbox("Core Concept", value=True)
        with col2:
            show_approach = st.checkbox("General Approach", value=True)
        with col3:
            show_solution = st.checkbox("Worked Solution", value=True)
        show_pitfall = st.checkbox("Common Pitfall", value=True)
        
        if st.button("Get Learning Guide", type="primary"):
            if not learning_problem.strip():
                st.error("Problem statement is required.")
            else:
                with st.spinner("Generating learning guide…"):
                    try:
                        resp = _post(
                            f"{API_BASE}/create",
                            data={"problem_text": learning_problem, "domain": learning_domain},
                            timeout=CREATE_SESSION_TIMEOUT,
                        )
                        resp.raise_for_status()
                        payload = resp.json()
                        session_id = payload["session_id"]
                        
                        # Get teaching content from the dedicated endpoint
                        with st.spinner("Generating teaching content…"):
                            teach_resp = _get(f"{API_BASE}/{session_id}/learn")
                            teach_resp.raise_for_status()
                            teach_data = teach_resp.json()
                            teaching = teach_data.get("teaching", {})
                            
                            if teaching:
                                st.success("Learning Guide Generated!")
                                st.divider()
                                
                                if show_concept and teaching.get("concept_summary"):
                                    st.markdown("### 📖 Core Concept")
                                    st.write(teaching.get("concept_summary"))
                                
                                if show_approach and teaching.get("general_approach"):
                                    st.markdown("### 🎯 General Approach")
                                    for i, step in enumerate(teaching.get("general_approach", []), 1):
                                        st.write(f"{i}. {step}")
                                
                                if show_solution and teaching.get("worked_solution"):
                                    st.markdown("### ✅ Worked Solution")
                                    for i, step in enumerate(teaching.get("worked_solution", []), 1):
                                        st.write(f"{i}. {step}")
                                
                                if show_pitfall and teaching.get("common_pitfall"):
                                    st.warning(f"⚠️ **Common Pitfall:** {teaching.get('common_pitfall')}")
                                
                                # Store session_id for animation generation
                                st.session_state.learn_session_id = session_id
                                
                                st.divider()
                                st.subheader("📺 Visualisation")
                                
                                # Polling loop: runs on every rerun while learn_anim_polling=True
                                if st.session_state.learn_anim_polling:
                                    try:
                                        status_resp = _get(f"{API_BASE}/{session_id}/animate/status")
                                        status_resp.raise_for_status()
                                        anim = status_resp.json()
                                    except Exception as poll_exc:
                                        st.session_state.learn_anim_polling = False
                                        st.session_state.learn_anim_error = f"Status poll failed: {poll_exc}"
                                        st.rerun()
                                    else:
                                        anim_status = anim.get("status", "idle")
                                        if anim_status == "rendering":
                                            with st.spinner("Rendering animation (~20s)…"):
                                                time.sleep(3)
                                            st.rerun()
                                        elif anim_status == "done":
                                            st.session_state.learn_anim_polling = False
                                            st.session_state.learn_anim_url = anim.get("url")
                                            st.session_state.learn_anim_script = anim.get("script")
                                            st.rerun()
                                        elif anim_status == "error":
                                            st.session_state.learn_anim_polling = False
                                            st.session_state.learn_anim_error = anim.get("error", "Unknown render error")
                                            st.session_state.learn_anim_script = anim.get("script")
                                            st.rerun()
                                
                                # Show video when ready
                                if st.session_state.learn_anim_url:
                                    video_url = f"{API_HOST}{st.session_state.learn_anim_url}"
                                    st.video(video_url)
                                    with st.expander("View generated Manim script", expanded=False):
                                        st.code(st.session_state.learn_anim_script or "", language="python")
                                
                                # Show error with retry
                                elif st.session_state.learn_anim_error:
                                    st.error(f"Animation failed: {st.session_state.learn_anim_error}")
                                    with st.expander("View generated Manim script (debug)", expanded=False):
                                        st.code(st.session_state.learn_anim_script or "(script not generated)", language="python")
                                    if st.button("Retry Animation"):
                                        st.session_state.learn_anim_error = None
                                        st.session_state.learn_anim_script = None
                                        try:
                                            resp = _post(
                                                f"{API_BASE}/{session_id}/animate",
                                                data={"error_classification": "conceptual"},
                                            )
                                            resp.raise_for_status()
                                            st.session_state.learn_anim_polling = True
                                            st.rerun()
                                        except Exception as exc:
                                            st.error(f"Failed to start animation: {exc}")
                                
                                # Generate button (idle state)
                                elif not st.session_state.learn_anim_polling:
                                    if st.button("Generate Animation", type="primary"):
                                        try:
                                            resp = _post(
                                                f"{API_BASE}/{session_id}/animate",
                                                data={"error_classification": "conceptual"},
                                            )
                                            resp.raise_for_status()
                                            st.session_state.learn_anim_polling = True
                                            st.rerun()
                                        except Exception as exc:
                                            st.error(f"Failed to start animation: {exc}")
                            else:
                                st.info("Unable to generate teaching content at this time.")
                    except Exception as exc:
                        st.error(f"Failed to generate learning guide: {exc}")


# ── View 2 — Submit Student Work ─────────────────────────────────────────────

elif st.session_state.view == "submit":
    st.subheader("Submit Your Work")
    st.info(f"**Problem:** {st.session_state.problem_text}")

    student_work = st.text_area("Your solution / work", height=200)
    work_image = st.file_uploader(
        "Work image (optional)", type=["png", "jpg", "jpeg"]
    )

    if st.button("Submit for Diagnosis", type="primary"):
        if not student_work.strip():
            st.error("Please enter your work.")
        else:
            with st.spinner("Running diagnosis…"):
                try:
                    files = (
                        {"image": (work_image.name, work_image.getvalue(), "image/jpeg")}
                        if work_image
                        else None
                    )
                    resp = _post(
                        f"{API_BASE}/{st.session_state.session_id}/submit",
                        data={"student_work_text": student_work},
                        files=files,
                    )
                    resp.raise_for_status()
                    diagnosis = resp.json()
                    st.session_state.last_diagnosis = diagnosis
                    st.session_state.current_turn += 1

                    if diagnosis.get("iteration_complete"):
                        st.session_state.view = "final"
                    else:
                        st.session_state.view = "result"
                    st.rerun()
                except Exception as exc:
                    st.error(f"Submission failed: {exc}")


# ── View 2b — Show Result + Continue ─────────────────────────────────────────

elif st.session_state.view == "result":
    diagnosis = st.session_state.last_diagnosis
    st.subheader(f"Diagnosis — Turn {st.session_state.current_turn}")

    confidence = diagnosis.get("confidence", 0.0)
    st.progress(confidence, text=f"Confidence: {confidence:.0%}")
    st.info(diagnosis.get("feedback", ""))

    probe = diagnosis.get("probe_question")
    if probe:
        st.warning(f"**Follow-up:** {probe}")

    if st.button("Continue →"):
        st.session_state.view = "followup"
        st.rerun()


# ── View 3 — Follow-up Response ──────────────────────────────────────────────

elif st.session_state.view == "followup":
    diagnosis = st.session_state.last_diagnosis
    st.subheader("Follow-up Response")

    probe = diagnosis.get("probe_question") if diagnosis else None
    if probe:
        st.warning(f"**{probe}**")

    followup_text = st.text_area("Your response", height=150)
    followup_image = st.file_uploader(
        "Image (optional)", type=["png", "jpg", "jpeg"]
    )

    if st.button("Submit Response", type="primary"):
        if not followup_text.strip():
            st.error("Please enter a response.")
        else:
            with st.spinner("Running diagnosis…"):
                try:
                    files = (
                        {"image": (followup_image.name, followup_image.getvalue(), "image/jpeg")}
                        if followup_image
                        else None
                    )
                    resp = _post(
                        f"{API_BASE}/{st.session_state.session_id}/submit",
                        data={"student_work_text": followup_text},
                        files=files,
                    )
                    resp.raise_for_status()
                    diagnosis = resp.json()
                    st.session_state.last_diagnosis = diagnosis
                    st.session_state.current_turn += 1

                    if diagnosis.get("iteration_complete"):
                        st.session_state.view = "final"
                    else:
                        st.session_state.view = "result"
                    st.rerun()
                except Exception as exc:
                    st.error(f"Submission failed: {exc}")


# ── View 4 — Final Diagnosis ──────────────────────────────────────────────────

elif st.session_state.view == "final":
    diagnosis = st.session_state.last_diagnosis
    sid = st.session_state.session_id

    st.subheader("Final Diagnosis")

    root_div = diagnosis.get("root_divergence") or {}
    if root_div:
        st.success(f"**Root cause:** {root_div.get('concept', 'N/A')}")

    error_cls = diagnosis.get("error_classification", "unknown")
    st.error(f"Error classification: **{error_cls}**")
    st.info(diagnosis.get("feedback", ""))

    # ── Teaching section ──────────────────────────────────────────────────────
    teaching = diagnosis.get("teaching")
    if teaching:
        st.divider()
        st.subheader("How to Solve This")

        st.markdown("**Core Concept**")
        st.write(teaching.get("concept_summary", ""))

        approach = teaching.get("general_approach", [])
        if approach:
            st.markdown("**General Approach** (use this method for similar problems)")
            for i, step in enumerate(approach, 1):
                st.write(f"{i}. {step}")

        solution = teaching.get("worked_solution", [])
        if solution:
            st.markdown("**Worked Solution**")
            for i, step in enumerate(solution, 1):
                st.write(f"{i}. {step}")

        pitfall = teaching.get("common_pitfall", "")
        if pitfall:
            st.warning(f"**Common Pitfall:** {pitfall}")

    coverage = diagnosis.get("coverage_matrix", [])
    if coverage:
        st.subheader("Coverage Matrix")
        st.dataframe(coverage, use_container_width=True)

    try:
        hist_resp = _get(f"{API_BASE}/{sid}/history")
        hist_resp.raise_for_status()
        hist = hist_resp.json()
        traj = hist.get("confidence_trajectory", [])
        if len(traj) > 1:
            st.subheader("Confidence Trajectory")
            st.line_chart(traj)
        elif len(traj) == 1:
            st.metric("Final confidence", f"{traj[0]:.0%}")
    except Exception:
        pass

    # ── Animation section ─────────────────────────────────────────────────────

    st.divider()
    st.subheader("Visualisation")

    # ── Polling loop: runs on every rerun while anim_polling=True ─────────────
    if st.session_state.anim_polling:
        try:
            status_resp = _get(f"{API_BASE}/{sid}/animate/status")
            status_resp.raise_for_status()
            anim = status_resp.json()
        except Exception as poll_exc:
            st.session_state.anim_polling = False
            st.session_state.anim_error = f"Status poll failed: {poll_exc}"
            st.rerun()
        else:
            anim_status = anim.get("status", "idle")
            if anim_status == "rendering":
                with st.spinner("Rendering animation (~20s)…"):
                    time.sleep(3)
                st.rerun()
            elif anim_status == "done":
                st.session_state.anim_polling = False
                st.session_state.anim_url = anim.get("url")
                st.session_state.anim_script = anim.get("script")
                st.rerun()
            elif anim_status == "error":
                st.session_state.anim_polling = False
                st.session_state.anim_error = anim.get("error", "Unknown render error")
                st.session_state.anim_script = anim.get("script")
                st.rerun()

    # ── Show video when ready ─────────────────────────────────────────────────
    if st.session_state.anim_url:
        video_url = f"{API_HOST}{st.session_state.anim_url}"
        st.video(video_url)
        with st.expander("View generated Manim script", expanded=False):
            st.code(st.session_state.anim_script or "", language="python")

    # ── Show error with retry ─────────────────────────────────────────────────
    elif st.session_state.anim_error:
        st.error(f"Animation failed: {st.session_state.anim_error}")
        with st.expander("View generated Manim script (debug)", expanded=False):
            st.code(st.session_state.anim_script or "(script not generated)", language="python")
        if st.button("Retry Animation"):
            st.session_state.anim_error = None
            st.session_state.anim_script = None
            try:
                resp = _post(
                    f"{API_BASE}/{sid}/animate",
                    data={"error_classification": error_cls},
                )
                resp.raise_for_status()
                st.session_state.anim_polling = True
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to start animation: {exc}")

    # ── Generate button (idle state) ──────────────────────────────────────────
    elif not st.session_state.anim_polling:
        if st.button("Generate Animation", type="primary"):
            try:
                resp = _post(
                    f"{API_BASE}/{sid}/animate",
                    data={"error_classification": error_cls},
                )
                resp.raise_for_status()
                st.session_state.anim_polling = True
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to start animation: {exc}")

    # ── New session ───────────────────────────────────────────────────────────

    st.divider()
    if st.button("Start New Session"):
        for k in ["session_id", "problem_text", "domain", "last_diagnosis",
                  "anim_url", "anim_error", "anim_script"]:
            st.session_state[k] = None
        st.session_state.current_turn = 0
        st.session_state.anim_polling = False
        st.session_state.view = "create"
        st.rerun()
