"""
discovery_service.py — Curated discovery feeds for Indian and International cinema,
genre browsing, language browsing, and all home feed categories.

This service is the single entry-point for the /discover/* endpoints.
It encapsulates all regional and genre-based filtering logic, delegating
raw TMDB calls to tmdb_service.

Available discovery categories:
  - Indian cinema (by language: hi, te, ta, ml, kn, bn, mr, pa, gu)
  - International / World cinema (by language: ko, ja, fr, es, de, it, zh)
  - Genre-based discovery (Action, Drama, Sci-Fi, etc.)
  - Home feeds: trending, popular, top_rated, upcoming, now_playing

v5.0 new module — Did not exist in v4.0.
"""
from typing import Any, Dict, List, Optional

from backend import tmdb_service

# ─────────────────────────────────────────────────────────────────────────────
# Language / Region metadata
# ─────────────────────────────────────────────────────────────────────────────

INDIAN_LANGUAGES: Dict[str, str] = {
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
    "ml": "Malayalam",
    "kn": "Kannada",
    "bn": "Bengali",
    "mr": "Marathi",
    "pa": "Punjabi",
    "gu": "Gujarati",
}

WORLD_LANGUAGES: Dict[str, str] = {
    "ko": "Korean",
    "ja": "Japanese",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "zh": "Chinese",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "tr": "Turkish",
    "sv": "Swedish",
}

HOME_CATEGORIES: Dict[str, str] = {
    "popular": "Popular",
    "top_rated": "Top Rated",
    "now_playing": "Now Playing",
    "upcoming": "Upcoming",
    "trending": "Trending Today",
}

# TMDB genre ID map (for convenience)
GENRE_MAP: Dict[str, int] = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "history": 36,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "sci-fi": 878,
    "thriller": 53,
    "war": 10752,
    "western": 37,
}


# ─────────────────────────────────────────────────────────────────────────────
# Public service functions
# ─────────────────────────────────────────────────────────────────────────────

async def get_home_feed(category: str = "popular", limit: int = 24) -> dict:
    """
    Returns structured home feed for a given category.
    Args:
        category:  One of: popular, top_rated, now_playing, upcoming, trending.
        limit:     Number of movies to return.
    Returns:
        {
            "category": str,
            "label": str,
            "movies": list[dict],
        }
    """
    label = HOME_CATEGORIES.get(category, category.replace("_", " ").title())
    movies = await tmdb_service.get_home_feed(category=category, limit=limit)
    return {
        "category": category,
        "label": label,
        "movies": movies,
    }


async def get_indian_cinema_feed(
    language: Optional[str] = None,
    sort_by: str = "popularity.desc",
    page: int = 1,
    limit: int = 24,
) -> dict:
    """
    Returns structured Indian cinema feed.
    Args:
        language:  Optional language code (hi, te, ta, ml, kn, bn, mr, pa, gu).
                   If None, returns a blend of top Indian languages.
        sort_by:   TMDB sort order.
        page:      TMDB page.
        limit:     Number of movies.
    Returns:
        {
            "region": "Indian Cinema",
            "language": str | None,
            "language_label": str | None,
            "available_languages": dict[code -> label],
            "movies": list[dict],
        }
    """
    language_label = INDIAN_LANGUAGES.get(language) if language else None
    movies = await tmdb_service.get_indian_cinema(
        language=language,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )
    return {
        "region": "Indian Cinema",
        "language": language,
        "language_label": language_label,
        "available_languages": INDIAN_LANGUAGES,
        "movies": movies,
    }


async def get_world_cinema_feed(
    language: Optional[str] = None,
    sort_by: str = "popularity.desc",
    page: int = 1,
    limit: int = 24,
) -> dict:
    """
    Returns structured international / world cinema feed.
    Args:
        language:  Optional language code (ko, ja, fr, es, de, it, zh, etc.).
                   If None, returns a blend of popular world cinema languages.
        sort_by:   TMDB sort order.
        page:      TMDB page.
        limit:     Number of movies.
    Returns:
        {
            "region": "World Cinema",
            "language": str | None,
            "language_label": str | None,
            "available_languages": dict[code -> label],
            "movies": list[dict],
        }
    """
    language_label = WORLD_LANGUAGES.get(language) if language else None
    movies = await tmdb_service.get_international_cinema(
        language=language,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )
    return {
        "region": "World Cinema",
        "language": language,
        "language_label": language_label,
        "available_languages": WORLD_LANGUAGES,
        "movies": movies,
    }


async def get_genre_feed(
    genre: str,
    sort_by: str = "popularity.desc",
    page: int = 1,
    limit: int = 24,
) -> dict:
    """
    Returns movies filtered by genre slug (e.g. "action", "sci-fi", "horror").
    Args:
        genre:    Genre slug (lowercase, hyphenated). Must be in GENRE_MAP.
        sort_by:  TMDB sort order.
        page:     TMDB page.
        limit:    Number of movies.
    Returns:
        {
            "genre": str,
            "genre_label": str,
            "genre_id": int,
            "available_genres": dict[slug -> genre_id],
            "movies": list[dict],
        }
    Raises:
        ValueError if genre slug is not in GENRE_MAP.
    """
    genre_lower = genre.strip().lower()
    genre_id = GENRE_MAP.get(genre_lower)
    if genre_id is None:
        raise ValueError(
            f"Unknown genre '{genre}'. Valid genres: {', '.join(GENRE_MAP.keys())}"
        )

    movies = await tmdb_service.discover_movies(
        genre_id=genre_id,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )
    return {
        "genre": genre_lower,
        "genre_label": genre_lower.replace("-", " ").title(),
        "genre_id": genre_id,
        "available_genres": {slug: gid for slug, gid in GENRE_MAP.items()},
        "movies": movies,
    }


async def get_discovery_metadata() -> dict:
    """
    Returns all available discovery categories, languages, and genres.
    Useful for building navigation menus in the frontend.
    """
    return {
        "home_categories": HOME_CATEGORIES,
        "indian_languages": INDIAN_LANGUAGES,
        "world_languages": WORLD_LANGUAGES,
        "genres": {slug: {"id": gid, "label": slug.replace("-", " ").title()} for slug, gid in GENRE_MAP.items()},
    }
