from contextlib import asynccontextmanager
from pathlib import Path

import config
from database import init_db
from fastapi import FastAPI
from orchestrator.pipeline import list_available_models
from fastapi.staticfiles import StaticFiles
from routers import session

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("[startup] Configured OpenRouter models:")
    await list_available_models()
    if not config.OPENROUTER_API_KEY:
        print("[startup] WARNING: OPENROUTER_API_KEY is not configured.")
    yield


app = FastAPI(lifespan=lifespan)
Path("static/animations").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(session.router, prefix="/session", tags=["session"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        reload=True,
        reload_excludes=["static/*"],  # prevents restart when Manim scripts are written
    )
