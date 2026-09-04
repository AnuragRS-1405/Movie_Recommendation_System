"""
main.py — CineMatch FastAPI application (v5.0 — Hybrid Recommender)

This file is a LEAN ORCHESTRATOR only.
  All ML math lives in backend/recommender.py.
  All TMDB HTTP lives in backend/tmdb_service.py.
  All feature preprocessing lives in backend/feature_builder.py.
  All caching lives in backend/cache_service.py.
  All config lives in backend/config.py.
  Hybrid recommendation logic lives in backend/movie_service.py.
  Discovery feeds live in backend/discovery_service.py.

API Endpoints:
  GET /                           — Root info
  GET /health                     — Health check
  GET /titles/exists              — Check if title exists locally
  GET /titles/suggest             — Autocomplete suggestions

  GET /home                       — Home feed (popular, trending, etc.)
  GET /tmdb/search                — Raw TMDB search
  GET /movie/id/{tmdb_id}         — Full movie details + cast + trailers
  GET /movie/id/{tmdb_id}/credits — Cast and crew only
  GET /movie/id/{tmdb_id}/trailer — Trailers only

  GET /recommend                  — Unified hybrid recommendation (paginated)

  GET /discover/metadata          — All available discovery categories
  GET /discover/indian            — Indian cinema (Bollywood/Tollywood/etc.)
  GET /discover/world             — International/world cinema
  GET /discover/genre/{genre}     — Movies by genre slug

  Legacy compatibility:
  GET /recommend/tfidf            — Legacy local-only TF-IDF endpoint
  GET /recommend/genre            — Legacy genre discovery
  GET /movie/search               — Legacy alias for /recommend
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config, recommender, tmdb_service, movie_service, discovery_service

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CineMatch — Hybrid Movie Recommender API",
    version="5.0",
    description=(
        "Blends a local TF-IDF/cosine-similarity model with live TMDB metadata. "
        "Never retrains. ML artifacts loaded once at startup. "
        "Supports Indian cinema, world cinema, and genre-based discovery."
    ),
)

# ── CORS ───────────────────────────────────────────────────────────────────────
_allow_credentials = config.ALLOWED_ORIGINS != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve frontend static files ────────────────────────────────────────────────
_FRONTEND_DIR = Path(__file__).parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

# ── Guaranteed-JSON error handler ──────────────────────────────────────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": type(exc).__name__},
    )


# ── Startup: load ML models ────────────────────────────────────────────────────
@app.on_event("startup")
def startup_load_models():
    recommender.load_models()


# =============================================================================
# ROOT & HEALTH
# =============================================================================

@app.get("/")
def root():
    return {
        "message": "CineMatch Hybrid Movie Recommender API",
        "status": "running",
        "version": app.version,
        "tmdb_configured": config.tmdb_configured(),
        "docs": "/docs",
        "frontend": "/app",
        "endpoints": {
            "health": "GET /health",
            "home_feed": "GET /home?category=popular",
            "tmdb_search": "GET /tmdb/search?query=",
            "movie_details": "GET /movie/id/{tmdb_id}",
            "movie_credits": "GET /movie/id/{tmdb_id}/credits",
            "movie_trailer": "GET /movie/id/{tmdb_id}/trailer",
            "recommend": "GET /recommend?query=",
            "title_exists": "GET /titles/exists?title=",
            "title_suggest": "GET /titles/suggest?query=",
            "discover_metadata": "GET /discover/metadata",
            "discover_indian": "GET /discover/indian",
            "discover_world": "GET /discover/world",
            "discover_genre": "GET /discover/genre/{genre}",
        },
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "dataset_loaded": recommender.is_loaded(),
        "dataset_size": recommender.dataset_size(),
        "tmdb_configured": config.tmdb_configured(),
        "version": app.version,
    }


# =============================================================================
# LOCAL DATASET HELPERS
# =============================================================================

@app.get("/titles/exists")
def title_exists(title: str = Query(..., min_length=1)):
    return {
        "title": title,
        "exists_locally": recommender.title_exists(title),
    }


@app.get("/titles/suggest")
def suggest_titles(
    query: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
):
    return recommender.suggest_titles(query, limit=limit)


# =============================================================================
# HOME FEED
# =============================================================================

@app.get("/home")
async def home(
    category: str = Query("popular"),
    limit: int = Query(24, ge=1, le=50),
):
    try:
        result = await discovery_service.get_home_feed(category=category, limit=limit)
        # Return just the movies list for backward compatibility with frontend
        return result.get("movies", [])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Home feed error: {type(e).__name__}")


# =============================================================================
# TMDB SEARCH & MOVIE DETAILS
# =============================================================================

@app.get("/tmdb/search")
async def tmdb_search(
    query: str = Query(..., min_length=1),
    page: int = Query(1, ge=1, le=10),
):
    return await tmdb_service.search_movies(query=query, page=page)


@app.get("/movie/id/{tmdb_id}")
async def movie_details_route(tmdb_id: int):
    """Full movie details including cast, crew, trailers, genres, runtime."""
    return await movie_service.get_full_movie_details(tmdb_id)


@app.get("/movie/id/{tmdb_id}/credits")
async def movie_credits_route(tmdb_id: int):
    """Cast and crew only for a given TMDB movie ID."""
    return await tmdb_service.get_movie_credits(tmdb_id)


@app.get("/movie/id/{tmdb_id}/trailer")
async def movie_trailer_route(tmdb_id: int):
    """Official trailers and teasers for a given TMDB movie ID."""
    trailers = await tmdb_service.get_movie_trailers(tmdb_id)
    return {"tmdb_id": tmdb_id, "trailers": trailers}


@app.get("/movie/trailer")
async def general_trailer_route(
    title: str = Query(..., min_length=1),
    tmdb_id: Optional[int] = Query(None)
):
    """Guaranteed official trailer lookup for any movie title or TMDB ID."""
    import urllib.parse
    trailers = []
    if tmdb_id:
        try:
            trailers = await tmdb_service.get_movie_trailers(tmdb_id)
        except Exception:
            trailers = []
    if not trailers:
        encoded = urllib.parse.quote_plus(f"{title} official trailer")
        trailers = [{
            "key": None,
            "name": f"{title} — Official Trailer",
            "type": "Trailer",
            "site": "YouTube",
            "embed_url": f"https://www.youtube.com/embed?listType=search&list={encoded}&autoplay=1",
            "watch_url": f"https://www.youtube.com/results?search_query={encoded}",
            "official": True,
        }]
    return {"title": title, "tmdb_id": tmdb_id, "trailers": trailers}


# =============================================================================
# UNIFIED HYBRID RECOMMEND ENDPOINT
# =============================================================================

@app.get("/recommend")
async def recommend(
    query: Optional[str] = Query(None),
    tmdb_id: Optional[int] = Query(None),
    language: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    local_top_n: int = Query(20, ge=1, le=50),
    external_top_n: int = Query(20, ge=1, le=50),
    genre_limit: int = Query(20, ge=1, le=50),
    local_offset: int = Query(0, ge=0),
    external_offset: int = Query(0, ge=0),
):
    """
    Unified hybrid recommendation endpoint (v5.0).
    Accepts either 'query' (text search), 'tmdb_id' (exact ID match), or both.
    """
    if not query and not tmdb_id:
        raise HTTPException(
            status_code=400,
            detail="Must provide either 'query' or 'tmdb_id' parameter."
        )
    return await movie_service.get_recommendations(
        query=query,
        tmdb_id=tmdb_id,
        language=language,
        year=year,
        local_top_n=local_top_n,
        external_top_n=external_top_n,
        genre_limit=genre_limit,
        local_offset=local_offset,
        external_offset=external_offset,
    )


# =============================================================================
# DISCOVERY ENDPOINTS
# =============================================================================

@app.get("/discover/metadata")
async def discover_metadata():
    """
    Returns all available discovery categories, languages, and genres
    for building dynamic navigation menus in the frontend.
    """
    return await discovery_service.get_discovery_metadata()


@app.get("/discover/indian")
async def discover_indian(
    language: Optional[str] = Query(None, description="Language code: hi, te, ta, ml, kn, bn, mr, pa, gu"),
    sort_by: str = Query("popularity.desc"),
    page: int = Query(1, ge=1, le=20),
    limit: int = Query(24, ge=1, le=50),
):
    """
    Indian cinema discovery feed.
    Supports filtering by language (Bollywood, Telugu, Tamil, Malayalam, etc.)
    """
    try:
        return await discovery_service.get_indian_cinema_feed(
            language=language,
            sort_by=sort_by,
            page=page,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Indian cinema feed error: {type(e).__name__}")


@app.get("/discover/world")
async def discover_world(
    language: Optional[str] = Query(None, description="Language code: ko, ja, fr, es, de, it, zh"),
    sort_by: str = Query("popularity.desc"),
    page: int = Query(1, ge=1, le=20),
    limit: int = Query(24, ge=1, le=50),
):
    """
    International / world cinema discovery feed.
    Supports filtering by language (Korean, Japanese, French, Spanish, etc.)
    """
    try:
        return await discovery_service.get_world_cinema_feed(
            language=language,
            sort_by=sort_by,
            page=page,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"World cinema feed error: {type(e).__name__}")


@app.get("/discover/genre/{genre}")
async def discover_genre(
    genre: str,
    sort_by: str = Query("popularity.desc"),
    page: int = Query(1, ge=1, le=20),
    limit: int = Query(24, ge=1, le=50),
):
    """
    Genre-based movie discovery.
    Valid genre slugs: action, adventure, animation, comedy, crime, documentary,
    drama, family, fantasy, history, horror, music, mystery, romance,
    sci-fi, thriller, war, western.
    """
    try:
        return await discovery_service.get_genre_feed(
            genre=genre,
            sort_by=sort_by,
            page=page,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Genre discovery error: {type(e).__name__}")


# =============================================================================
# LEGACY COMPATIBILITY ENDPOINTS
# =============================================================================

@app.get("/recommend/tfidf")
async def recommend_tfidf_legacy(
    title: str = Query(..., min_length=1),
    top_n: int = Query(10, ge=1, le=50),
):
    """Legacy endpoint — prefer /recommend for the full hybrid response."""
    recs = recommender.recommend_local_to_local(title, top_n=top_n)
    return [{"title": t, "score": s} for t, s in recs]


@app.get("/recommend/genre")
async def recommend_genre_legacy(
    tmdb_id: int = Query(...),
    limit: int = Query(18, ge=1, le=50),
):
    """Legacy endpoint — prefer /discover/genre/{genre} for the full response."""
    details = await tmdb_service.get_movie_details(tmdb_id)
    genres = details.get("genres", [])
    if not genres:
        return []
    return await tmdb_service.discover_by_genre(
        genre_id=genres[0]["id"],
        exclude_tmdb_id=tmdb_id,
        limit=limit,
    )


@app.get("/movie/search")
async def movie_search_legacy(
    query: str = Query(..., min_length=1),
    tfidf_top_n: int = Query(12, ge=1, le=30),
    genre_limit: int = Query(12, ge=1, le=30),
):
    """Legacy /movie/search endpoint — redirects to /recommend."""
    return await recommend(
        query=query,
        local_top_n=tfidf_top_n,
        external_top_n=tfidf_top_n,
        genre_limit=genre_limit,
        local_offset=0,
        external_offset=0,
    )