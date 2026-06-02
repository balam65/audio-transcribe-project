"""
Meeting Transcription System — Main Application
FastAPI server with WebSocket support for real-time transcription.

Run with: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import config
from models.database import init_db
from routes.auth import router as auth_router
from routes.transcription import router as transcription_router
from routes.meetings import router as meetings_router
from routes.export import router as export_router
from services.summary import get_summary_provider_status
from services.transcription import get_transcription_provider_status

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and validate config on startup."""
    print("\n" + "=" * 60)
    print("  🎙️  Meeting Transcription System")
    print("=" * 60)
    config.validate()
    await init_db()
    FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
    print(f"\n  🌐 Server: http://{config.HOST}:{config.PORT}")
    print(f"  📁 Frontend: {FRONTEND_DIR}")
    print("=" * 60 + "\n")
    yield


# Create FastAPI app
app = FastAPI(
    title="Meeting Transcription System",
    description="Desktop meeting transcription with configurable speech-to-text and summary providers.",
    version="2.0.0",
    lifespan=lifespan,
)

if config.SESSION_SECRET:
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SESSION_SECRET,
        same_site="lax",
        https_only=config.hosted_mode(),
        max_age=60 * 60 * 24 * 14,
    )

# CORS middleware (allow frontend on same machine)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth_router)
app.include_router(transcription_router)
app.include_router(meetings_router)
app.include_router(export_router)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")



@app.get("/")
async def serve_frontend():
    """Serve the main frontend page."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Frontend not found. Place index.html in /frontend/"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    transcription_status = get_transcription_provider_status()
    summary_status = get_summary_provider_status()
    return {
        "status": "ok",
        "app_mode": config.APP_MODE,
        "auth_required": config.AUTH_REQUIRED,
        "auth_configured": config.auth_configured(),
        "capabilities": config.capabilities(),
        "engine": config.TRANSCRIPTION_ENGINE,
        "transcription_engine": config.TRANSCRIPTION_ENGINE,
        "transcription_model": transcription_status["model"],
        "transcription_provider": transcription_status["provider"],
        "transcription_ready": transcription_status["ready"],
        "transcription_detail": transcription_status["detail"],
        "transcription_model_available": transcription_status["model_available"],
        "summary_engine": config.SUMMARY_ENGINE,
        "summary_model": config.SUMMARY_MODEL,
        "summary_provider": summary_status["provider"],
        "summary_ready": summary_status["ready"],
        "summary_detail": summary_status["detail"],
        "summary_model_available": summary_status["model_available"],
        "ollama_reachable": summary_status["reachable"] if config.SUMMARY_ENGINE == "ollama" else False,
        "openai_configured": summary_status["ready"] if config.SUMMARY_ENGINE == "openai" else False,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
        log_level="info",
    )
