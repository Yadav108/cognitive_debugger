# Gemini vision extraction — single responsibility
import asyncio
import base64
from pathlib import Path

from google import genai
from google.genai import types

from config import GENAI_API_KEY, GEMINI_MODEL, GEMINI_FALLBACK_MODELS

client = genai.Client(api_key=GENAI_API_KEY)
MODEL = GEMINI_MODEL

EXTRACTION_PROMPT = """
You are extracting content from a student's handwritten engineering solution.

Extract ALL of the following if present:
- All equations (write symbolically, e.g. ΣFx = ma)
- All force labels and directions (e.g. N pointing up, mg pointing down)
- All diagram annotations (labels, angles, dimensions)
- All written steps or reasoning text
- Any numeric values with units

FORMAT RULES:
- Preserve mathematical notation as closely as possible
- List each distinct element on a new line
- Prefix diagram content with [DIAGRAM]:
- Prefix equations with [EQ]:
- Prefix text/reasoning with [TEXT]:
- Prefix numeric values with [VAL]:

If the image is blank, unreadable, or contains no engineering content,
respond with exactly: EXTRACTION_FAILED
"""

_FAILURE = {"extracted_text": "", "image_confidence": 0.0, "extraction_success": False}

_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _candidate_models() -> list[str]:
    seen = set()
    ordered = [MODEL, *GEMINI_FALLBACK_MODELS]
    candidates = []
    for model in ordered:
        if model and model not in seen:
            candidates.append(model)
            seen.add(model)
    return candidates


async def extract_image_content(image_path: str) -> dict:
    """Extract structured content from a student-submitted image.

    Calls the Gemini Vision API and returns normalised text so that all
    downstream pipeline calls receive text, never raw image bytes.

    Returns a dict with keys:
      - extracted_text: str   — full extraction; empty string on failure
      - image_confidence: float — 0.0–1.0 estimate of extraction quality,
            derived from line count and presence of [DIAGRAM]: / [EQ]: tags
      - extraction_success: bool

    Confidence heuristic:
      base = min(1.0, line_count / 10)   # normalised to 10 lines
      +0.2 if both diagram and equation tags are present
      +0.1 if only one of the two is present
    """
    if not image_path:
        return _FAILURE

    try:
        # Step 1 — file existence check
        path = Path(image_path)
        if not path.exists():
            return _FAILURE

        # Step 2 — read
        raw_bytes = path.read_bytes()

        # Step 3 — MIME type
        mime_type = _MIME_TYPES.get(path.suffix.lower())
        if mime_type is None:
            return _FAILURE

        # Step 5 — call Gemini natively using aio
        response = None
        last_error: Exception | None = None
        for model in _candidate_models():
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=[
                        types.Part.from_bytes(data=raw_bytes, mime_type=mime_type),
                        EXTRACTION_PROMPT,
                    ],
                )
                break
            except Exception as e:
                last_error = e
                print(f"[image.py] Extraction API error with model={model}: {e}")
        if response is None:
            if last_error:
                print(f"[image.py] Extraction failed after model fallback: {last_error}")
            return _FAILURE

        # Step 6 — parse response
        if response.text.strip() == "EXTRACTION_FAILED":
            return _FAILURE

        extracted_text = response.text.strip()

        line_count = len(extracted_text.splitlines())
        has_diagram = "[DIAGRAM]:" in extracted_text
        has_equation = "[EQ]:" in extracted_text

        base = min(1.0, line_count / 10)
        if has_diagram and has_equation:
            base = min(1.0, base + 0.2)
        elif has_diagram or has_equation:
            base = min(1.0, base + 0.1)
        image_confidence = round(base, 4)

        return {
            "extracted_text": extracted_text,
            "image_confidence": image_confidence,
            "extraction_success": True,
        }

    except Exception as e:
        print(f"[image.py] Extraction failed: {e}")
        return _FAILURE
