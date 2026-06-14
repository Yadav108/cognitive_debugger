# TODO: implement
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GENAI_API_KEY: str = GOOGLE_API_KEY or GEMINI_API_KEY
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
    "gemini-2.5-flash",
)
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"
)
_OPENROUTER_MODELS_ENV = os.getenv("OPENROUTER_MODELS", "").strip()
# Last verified: 2026-04-30 — re-check at openrouter.ai/models?q=free
OPENROUTER_MODELS = [
    "nvidia/nemotron-super-49b-v1:free",
    "google/gemma-4-31b-instruct:free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "qwen/qwen3-coder-480b-a35b:free",
]
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
COVERAGE_THRESHOLD: float = 0.6
PROPAGATION_CAP_TRIGGER: float = 0.5
RESOLUTION_THRESHOLD: float = 0.8
MAX_TURNS: int = 3
DB_PATH: str = "storage/debugger.db"
UPLOADS_PATH: str = "uploads/"
