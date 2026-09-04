"""
Centralized configuration for the Movie Recommendation System.
All secrets and tuneable parameters live here — never hardcoded elsewhere.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve paths relative to the project root (two levels up from this file)
_HERE = Path(__file__).resolve().parent          # backend/
PROJECT_ROOT = _HERE.parent                       # project root

# Load .env from project root
load_dotenv(PROJECT_ROOT / ".env")

# ── TMDB ──────────────────────────────────────────────────────────────────────
TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "")
TMDB_BASE_URL: str = os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3")
TMDB_IMG_BASE: str = "https://image.tmdb.org/t/p/w780"
TMDB_POSTER_BASE: str = "https://image.tmdb.org/t/p/w780"
TMDB_BACKDROP_BASE: str = "https://image.tmdb.org/t/p/w1280"
TMDB_TIMEOUT: float = float(os.getenv("TMDB_TIMEOUT", "20"))
TMDB_RETRIES: int = int(os.getenv("TMDB_RETRIES", "3"))

# ── Model / pickle paths ───────────────────────────────────────────────────────
MODELS_DIR = PROJECT_ROOT / "models"
DF_PATH = MODELS_DIR / "Df.pkl"
INDICES_PATH = MODELS_DIR / "Indices.pkl"
TFIDF_PATH = MODELS_DIR / "TFIDF.pkl"
TFIDF_MATRIX_PATH = MODELS_DIR / "TFIDF_Matrix.pkl"

# ── CORS ───────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# ── Startup warnings ───────────────────────────────────────────────────────────
if not TMDB_API_KEY:
    print(
        "[config] WARNING: TMDB_API_KEY is not set. "
        "TMDB-powered endpoints will respond with 503 until you add it to .env"
    )


def tmdb_configured() -> bool:
    """Returns True if TMDB API key is available."""
    return bool(TMDB_API_KEY)
