import asyncio
import glob
import re
import subprocess
from pathlib import Path

import httpx

from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODELS

ANIMATIONS_DIR = Path("static/animations")
ANIMATIONS_DIR.mkdir(parents=True, exist_ok=True)

# Keep system prompt tight to stay within model token budget (~420 tokens here)
_SYSTEM = (
    "You are a Manim CE 0.18 code generator creating a short teaching animation "
    "in the style of Richard Feynman: plain language, build intuition before "
    "formalism, always explain WHY before HOW.\n"
    "Output ONLY raw Python — no markdown, no code fences, no explanations.\n"
    "Single class named CognitiveDebuggerScene(Scene). "
    "Only allowed import: from manim import *\n"
    "Stay under 160 lines. No 3D. No external assets.\n\n"
    "CRITICAL: Do NOT use MathTex or Tex — use Text only. "
    "LaTeX is not available on this machine. "
    "Write equations as plain Unicode strings, e.g. "
    "Text('ΣM_B = 0'), Text('F_wall × 4sin(60°) = W_L × 2cos(60°)'), "
    "Text('N_floor = 882 N'). Never call MathTex(...) or Tex(...).\n\n"
    "The frame is only ~14.2 units wide — oversized Text is auto-shrunk by the "
    "renderer, but it is NEVER auto-enlarged, so do NOT call "
    ".scale_to_fit_width(...) yourself (it can make short text huge). Just keep "
    "wording short.\n\n"
    "Structure construct(self) in FOUR acts. "
    "MANDATORY scene-clearing rule: immediately before starting Act 2, Act 3, "
    "and Act 4, call self.play(FadeOut(*self.mobjects)); self.wait(0.3) so "
    "NOTHING from a previous act remains on screen. Never let Act 1's text or "
    "Act 3's steps stay visible during a later act.\n\n"
    "Act 1 — Big Idea: ONE short sentence, at most 10 words, font_size=32, "
    "stating the core principle in plain language (no jargon), e.g. 'Forces on "
    "this ladder must balance.' Pair it with a tiny illustrative sketch (a few "
    "arrows or shapes), not the full problem diagram yet.\n"
    "Act 2 — The Setup: Physics diagram of THIS problem — Arrows, Lines, "
    "Rectangle, Dot, short Text labels.\n"
    "Act 3 — Solving It: Pick 2-4 key steps from 'Worked solution steps' and "
    "CONDENSE each into a SHORT phrase of at most 8-10 words / 55 characters, "
    "e.g. worked step 'Step 4: Solve for N: N = (196*1 + ...) / 3.464 = 353.8 N.' "
    "becomes Text('N = 353.8 N'). Keep any numeric values and units EXACTLY as "
    "given — never recompute, round differently, or invent different numbers — "
    "but drop the surrounding wording so each line is short. Animate one at a "
    "time with Write(), font_size=28-32, arranged with VGroup + arrange(DOWN).\n"
    "Act 4 — Watch Out: SurroundingRectangle around the element related to the "
    "student's mistake; Text label naming the pitfall in RED using color=RED. "
    "Keep every mobject within the visible frame: roughly x in [-6.5, 6.5] and "
    "y in [-3.5, 3.5]. If a label would land outside that range, use "
    ".next_to(target, DOWN) instead of UP (or vice versa), or .move_to(ORIGIN) "
    "then .shift(...) to stay inside bounds.\n\n"
    "The background is BLACK. Never use color=BLACK (or BLACK-ish colors) for "
    "any Line, Rectangle, Arrow, or other shape — it will be invisible. Use "
    "WHITE, GRAY, or a bright color instead.\n\n"
    "Allowed animations: Write, Create, FadeIn, FadeOut, Indicate, Transform, GrowArrow.\n"
    "Forbidden: MathTex, Tex, ThreeDScene, SVGMobject, ImageMobject, ValueTracker, "
    "DecimalNumber, Axes, NumberPlane, OpenGLSurface."
)

_USER = (
    "Problem: {problem}\n"
    "Domain: {domain}\n"
    "Core concept — explain this simply in Act 1: {concept_summary}\n"
    "General method (for context): {general_approach}\n"
    "Worked solution steps — pick 2-4 for Act 3: {worked_solution}\n"
    "Root cause of student's error: {root_cause}\n"
    "Error type: {error_classification}\n"
    "Pitfall to call out in Act 4: {common_pitfall}\n\n"
    "Generate CognitiveDebuggerScene."
)


def _join_truncate(items: list[str], max_chars: int, sep: str = " | ") -> str:
    return sep.join(items)[:max_chars]


async def generate_manim_script(
    problem: str,
    domain: str,
    root_cause: str,
    error_classification: str,
    diagnosis_text: str,
    concept_summary: str = "",
    general_approach: list[str] | None = None,
    worked_solution: list[str] | None = None,
    common_pitfall: str = "",
) -> str:
    """Call OpenRouter to produce a runnable Manim CE script string."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")
    if not OPENROUTER_MODELS:
        raise RuntimeError("OPENROUTER_MODELS is empty.")

    user_msg = _USER.format(
        problem=problem[:350],
        domain=domain,
        concept_summary=concept_summary[:300] or "(use your own judgment based on the problem)",
        general_approach=_join_truncate(general_approach or [], 300, "; "),
        worked_solution=_join_truncate(worked_solution or [], 500) or "(derive from the problem)",
        root_cause=root_cause[:180],
        error_classification=error_classification,
        common_pitfall=common_pitfall[:200] or diagnosis_text[:200],
    )
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        last_error = "OpenRouter API request failed for all configured models."
        for model in OPENROUTER_MODELS:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.2,
                "max_tokens": 2560,
            }
            resp = await client.post(OPENROUTER_BASE_URL, headers=headers, json=payload)
            if resp.status_code >= 400:
                last_error = f"{model} -> OpenRouter API error {resp.status_code}: {resp.text[:800]}"
                continue
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                last_error = f"{model} -> no choices in OpenRouter response: {str(data)[:400]}"
                continue
            raw = (choices[0].get("message", {}).get("content") or "").strip()
            break
        else:
            raise RuntimeError(last_error)
    # llama-3.x sometimes wraps output in markdown fences despite instructions
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*$", "", raw, flags=re.MULTILINE)
    return raw.strip()


# Free models routinely ignore the "Text only" instruction and emit MathTex/Tex
# for equations. LaTeX is not installed on this machine, so those calls crash
# the renderer with FileNotFoundError. This shim redefines MathTex/Tex to fall
# back to plain Text so a non-compliant script still renders.
#
# It also wraps Text itself to shrink (never enlarge) any mobject wider than
# the visible frame — generated scripts sometimes copy long worked-solution
# sentences into a single Text line, which would otherwise overflow both edges.
_TEX_FALLBACK_SHIM = '''

_OriginalText = Text


class Text(_OriginalText):
    """Text that auto-shrinks (never grows) to fit within the visible frame."""

    _MAX_WIDTH = 12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.width > self._MAX_WIDTH:
            self.scale_to_fit_width(self._MAX_WIDTH)


def _tex_fallback(*args, **kwargs):
    content = " ".join(str(a) for a in args)
    safe_kwargs = {k: v for k, v in kwargs.items() if k in ("font_size", "color", "weight", "slant")}
    return Text(content, **safe_kwargs)


MathTex = _tex_fallback
Tex = _tex_fallback
'''


def _sanitize_script(script: str) -> str:
    """Append the MathTex/Tex fallback shim to a generated script."""
    return script + _TEX_FALLBACK_SHIM


async def render_animation(session_id: str, script: str) -> str:
    """Write script to disk, invoke manim -ql, move output to static/animations/.

    Returns the destination path string.
    Raises RuntimeError (with stderr in message) on any failure.
    """
    ANIMATIONS_DIR.mkdir(parents=True, exist_ok=True)

    script_path = ANIMATIONS_DIR / f"{session_id}.py"
    script_path.write_text(_sanitize_script(script), encoding="utf-8")

    # asyncio.create_subprocess_exec is not supported on Windows with
    # SelectorEventLoop (uvicorn's default). Use subprocess.run in a thread
    # executor so the event loop stays unblocked during the ~20s render.
    # -ql = low quality 480p15 for speed; swap -qh for production
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["manim", "render", "-ql", "--progress_bar", "none",
             str(script_path), "CognitiveDebuggerScene"],
            capture_output=True,
            text=True,
        ),
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Manim render failed (exit {result.returncode}):\n{result.stderr}"
        )

    # Manim outputs to media/videos/<script_stem>/<quality>/ClassName.mp4
    stem = script_path.stem  # equals session_id
    pattern = str(
        Path("media") / "videos" / stem / "**" / "CognitiveDebuggerScene.mp4"
    )
    matches = glob.glob(pattern, recursive=True)
    if not matches:
        raise RuntimeError(
            f"Rendered video not found under media/videos/{stem}/.\n"
            f"stderr: {result.stderr}"
        )

    dest = ANIMATIONS_DIR / f"{session_id}.mp4"
    dest.unlink(missing_ok=True)  # remove stale file if retrying
    Path(matches[0]).rename(dest)
    return str(dest)
