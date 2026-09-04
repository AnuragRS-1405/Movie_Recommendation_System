"""
tmdb_service.py — All TMDB HTTP interactions in one place.

Design rules:
  - Retry logic with exponential backoff (up to TMDB_RETRIES attempts)
  - All timeouts respect TMDB_TIMEOUT from config
  - Network errors -> controlled HTTPException (502/503), never raw stack traces
  - API key is NEVER exposed in responses or logs
  - Candidate pool capped at 50-100 movies max (never the full catalog)

v5.0 additions:
  - get_movie_credits()    — cast and crew with director extraction
  - get_movie_trailers()   — YouTube trailer video key and embed URL
  - discover_movies()      — flexible query builder (language, region, genre)
  - get_indian_cinema()    — curated Bollywood/South Indian/regional feed
  - get_international()    — curated world cinema feed (non-English)
"""
import asyncio
from typing import Any, Dict, List, Optional

import re
import urllib.parse
import httpx
from fastapi import HTTPException

from backend.config import (
    TMDB_API_KEY,
    TMDB_BASE_URL,
    TMDB_IMG_BASE,
    TMDB_POSTER_BASE,
    TMDB_BACKDROP_BASE,
    TMDB_RETRIES,
    TMDB_TIMEOUT,
)
from backend import cache_service

# Indian language codes for filtering
_INDIAN_LANG_CODES = {"hi", "te", "ta", "ml", "kn", "bn", "mr", "pa", "gu"}

# World cinema language codes (non-English, non-Indian)
_WORLD_CINEMA_LANGS = {"ko", "ja", "fr", "es", "de", "it", "zh", "pt", "ru", "ar", "tr", "sv"}

_LANG_ALIASES = {
    "tamil": "ta",
    "telugu": "te",
    "hindi": "hi",
    "malayalam": "ml",
    "kannada": "kn",
    "bengali": "bn",
    "marathi": "mr",
    "punjabi": "pa",
    "gujarati": "gu",
    "korean": "ko",
    "japanese": "ja",
    "french": "fr",
    "spanish": "es",
    "german": "de",
    "italian": "it",
    "russian": "ru",
    "chinese": "zh",
    "english": "en",
}


# ── Low-level HTTP helper ─────────────────────────────────────────────────────
async def _tmdb_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safe TMDB GET with retry + timeout.
    - Missing API key -> 503
    - Network error -> 502
    - Non-200 TMDB response -> 502
    """
    if not TMDB_API_KEY:
        raise HTTPException(
            status_code=503,
            detail=(
                "TMDB_API_KEY is not configured on the server. "
                "Add it to your .env file to enable TMDB-powered features."
            ),
        )

    full_params = dict(params)
    full_params["api_key"] = TMDB_API_KEY

    last_exc: Optional[Exception] = None
    for attempt in range(max(1, TMDB_RETRIES)):
        try:
            async with httpx.AsyncClient(timeout=TMDB_TIMEOUT) as client:
                r = await client.get(f"{TMDB_BASE_URL}{path}", params=full_params)

            if r.status_code == 200:
                return r.json()

            # Non-retryable client errors (4xx)
            if 400 <= r.status_code < 500:
                raise HTTPException(
                    status_code=502,
                    detail=f"TMDB returned {r.status_code} for {path}",
                )

            # Server errors (5xx) — retry
            last_exc = HTTPException(
                status_code=502,
                detail=f"TMDB server error {r.status_code}",
            )

        except HTTPException:
            raise
        except httpx.TimeoutException:
            last_exc = HTTPException(status_code=502, detail="TMDB request timed out")
        except httpx.RequestError as exc:
            last_exc = HTTPException(
                status_code=502,
                detail=f"TMDB connection error: {type(exc).__name__}",
            )

        if attempt < TMDB_RETRIES - 1:
            await asyncio.sleep(0.5 * (attempt + 1))  # 0.5s, 1s, 1.5s ...

    raise last_exc or HTTPException(status_code=502, detail="TMDB request failed")


def _poster_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"{TMDB_POSTER_BASE}{path}"


def _backdrop_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"{TMDB_BACKDROP_BASE}{path}"


def _img_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"{TMDB_IMG_BASE}{path}"


def _card_from_result(m: dict) -> dict:
    return {
        "tmdb_id": int(m["id"]),
        "title": m.get("title") or m.get("name") or "",
        "poster_url": _poster_url(m.get("poster_path")),
        "backdrop_url": _backdrop_url(m.get("backdrop_path")),
        "release_date": m.get("release_date") or m.get("first_air_date"),
        "vote_average": m.get("vote_average"),
        "overview": m.get("overview") or "",
        "original_language": m.get("original_language") or "",
    }


# ── Public service functions ───────────────────────────────────────────────────

async def search_movies(query: str, page: int = 1) -> Dict[str, Any]:
    """Raw TMDB search response (with 'results' list)."""
    cache_key = f"search:{query.lower()}:{page}"
    cached = await cache_service.tmdb_search_cache.get(cache_key)
    if cached is not None:
        return cached

    data = await _tmdb_get(
        "/search/movie",
        {"query": query, "include_adult": "false", "language": "en-US", "page": page},
    )
    await cache_service.tmdb_search_cache.set(cache_key, data)
    return data


async def search_movie_first(
    query: str,
    year: Optional[int] = None,
    language: Optional[str] = None,
) -> Optional[dict]:
    """
    Returns the best TMDB match for a text query, or None.
    Supports language and release year disambiguation (e.g. 'Leo Tamil', 'Leo 2023').
    """
    clean_query = query.strip()
    detected_lang = language
    detected_year = year

    # 1. Extract trailing or parenthesized 4-digit year (e.g. "Leo (2023)" or "Leo 2023")
    year_match = re.search(r"\(?(\b(?:19|20)\d{2}\b)\)?", clean_query)
    if year_match and not detected_year:
        try:
            detected_year = int(year_match.group(1))
            clean_query = clean_query.replace(year_match.group(0), "").strip()
        except Exception:
            pass

    # 2. Extract language word (e.g. "Leo Tamil" or "Leo ta")
    words = clean_query.split()
    if len(words) > 1 and not detected_lang:
        last_word = words[-1].lower()
        if last_word in _LANG_ALIASES:
            detected_lang = _LANG_ALIASES[last_word]
            clean_query = " ".join(words[:-1]).strip()
        elif last_word in _INDIAN_LANG_CODES or last_word in _WORLD_CINEMA_LANGS:
            detected_lang = last_word
            clean_query = " ".join(words[:-1]).strip()

    search_term = clean_query or query
    data = await search_movies(search_term, page=1)
    results = data.get("results", [])
    if not results:
        # Fallback to searching original string if cleaned query had no results
        if search_term != query:
            data = await search_movies(query, page=1)
            results = data.get("results", [])
        if not results:
            return None

    # If language or year was specified/detected, pick the best matching result
    if detected_lang or detected_year:
        for r in results:
            match_lang = not detected_lang or (r.get("original_language") == detected_lang)
            r_year = (r.get("release_date") or "")[:4]
            match_year = not detected_year or (r_year == str(detected_year))
            if match_lang and match_year:
                return r

        # Secondary match: match language only if year failed
        if detected_lang:
            for r in results:
                if r.get("original_language") == detected_lang:
                    return r

    return results[0]


async def get_movie_details(tmdb_id: int) -> dict:
    """Full movie detail dict including genres list, runtime, budget."""
    cache_key = f"details:{tmdb_id}"
    cached = await cache_service.tmdb_details_cache.get(cache_key)
    if cached is not None:
        return cached

    data = await _tmdb_get(f"/movie/{tmdb_id}", {"language": "en-US"})
    result = {
        "tmdb_id": int(data["id"]),
        "title": data.get("title") or "",
        "overview": data.get("overview") or "",
        "tagline": data.get("tagline") or "",
        "release_date": data.get("release_date") or "",
        "poster_url": _poster_url(data.get("poster_path")),
        "backdrop_url": _backdrop_url(data.get("backdrop_path")),
        "genres": data.get("genres") or [],      # [{"id": 28, "name": "Action"}, ...]
        "vote_average": data.get("vote_average"),
        "vote_count": data.get("vote_count"),
        "runtime": data.get("runtime"),          # v5.0 — runtime in minutes
        "original_language": data.get("original_language") or "",
        "production_countries": data.get("production_countries") or [],
        "production_companies": data.get("production_companies") or [],
        "budget": data.get("budget"),
        "revenue": data.get("revenue"),
        "homepage": data.get("homepage") or "",
        "imdb_id": data.get("imdb_id") or "",
        "status": data.get("status") or "",
    }
    await cache_service.tmdb_details_cache.set(cache_key, result)
    return result


async def get_movie_keywords(tmdb_id: int) -> List[dict]:
    """
    Fetch keyword list for a movie.
    Returns list of {"id": ..., "name": ...} dicts.
    """
    cache_key = f"keywords:{tmdb_id}"
    cached = await cache_service.tmdb_details_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = await _tmdb_get(f"/movie/{tmdb_id}/keywords", {})
        result = data.get("keywords", [])
        await cache_service.tmdb_details_cache.set(cache_key, result)
        return result
    except HTTPException:
        return []


async def get_movie_credits(tmdb_id: int) -> dict:
    """
    Fetch cast and crew for a movie.
    Returns:
        {
            "cast": [ {"id", "name", "character", "profile_url", "order"}, ... ],
            "crew": [ {"id", "name", "job", "department", "profile_url"}, ... ],
            "director": str | None,
            "writers": [str, ...]
        }
    """
    cache_key = f"credits:{tmdb_id}"
    cached = await cache_service.credits_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = await _tmdb_get(f"/movie/{tmdb_id}/credits", {"language": "en-US"})

        cast_raw = data.get("cast", [])
        crew_raw = data.get("crew", [])

        cast = [
            {
                "id": int(c.get("id", 0)),
                "name": c.get("name", ""),
                "character": c.get("character", ""),
                "profile_url": _img_url(c.get("profile_path")),
                "order": c.get("order", 99),
            }
            for c in cast_raw[:20]  # Top 20 cast members
        ]

        crew = [
            {
                "id": int(c.get("id", 0)),
                "name": c.get("name", ""),
                "job": c.get("job", ""),
                "department": c.get("department", ""),
                "profile_url": _img_url(c.get("profile_path")),
            }
            for c in crew_raw
            if c.get("job") in {"Director", "Screenplay", "Writer", "Story", "Producer"}
        ]

        # Extract director name for quick access
        director = next(
            (c["name"] for c in crew if c["job"] == "Director"),
            None
        )
        writers = [c["name"] for c in crew if c["job"] in {"Screenplay", "Writer", "Story"}]

        result = {
            "cast": cast,
            "crew": crew,
            "director": director,
            "writers": writers,
        }
        await cache_service.credits_cache.set(cache_key, result)
        return result
    except HTTPException:
        return {"cast": [], "crew": [], "director": None, "writers": []}


async def get_movie_trailers(tmdb_id: int) -> List[dict]:
    """
    Fetch official trailers and teasers from TMDB /movie/{id}/videos.
    Returns list of:
        {
            "key":        YouTube video key (use to build embed URL),
            "name":       Video title,
            "type":       "Trailer" | "Teaser" | "Clip" etc.,
            "site":       "YouTube" | "Vimeo" etc.,
            "embed_url":  Full YouTube embed URL,
            "watch_url":  Full YouTube watch URL,
            "official":   bool,
        }
    Only returns YouTube videos (most reliable for embedding).
    """
    cache_key = f"videos:{tmdb_id}"
    cached = await cache_service.videos_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = await _tmdb_get(f"/movie/{tmdb_id}/videos", {"language": "en-US"})
        all_videos = data.get("results", [])

        # Fallback to query without language restriction so Indian/world cinema videos are retrieved
        if not all_videos:
            try:
                raw_data = await _tmdb_get(f"/movie/{tmdb_id}/videos", {})
                all_videos = raw_data.get("results", [])
            except Exception:
                pass

        # Prefer official trailers, then teasers, then clips, then any YouTube video
        priority_types = ["Trailer", "Teaser", "Clip", "Behind the Scenes", "Featurette"]
        youtube_videos = [v for v in all_videos if v.get("site") == "YouTube"]

        trailers = []
        for vtype in priority_types:
            for v in youtube_videos:
                if v.get("type") == vtype:
                    key = v.get("key", "")
                    trailers.append({
                        "key": key,
                        "name": v.get("name", ""),
                        "type": vtype,
                        "site": "YouTube",
                        "embed_url": f"https://www.youtube.com/embed/{key}?autoplay=1",
                        "watch_url": f"https://www.youtube.com/watch?v={key}",
                        "official": v.get("official", False),
                    })

        # Also add any other YouTube videos not matched by priority types
        for v in youtube_videos:
            key = v.get("key", "")
            if key and not any(t["key"] == key for t in trailers):
                trailers.append({
                    "key": key,
                    "name": v.get("name", "Trailer"),
                    "type": v.get("type", "Trailer"),
                    "site": "YouTube",
                    "embed_url": f"https://www.youtube.com/embed/{key}?autoplay=1",
                    "watch_url": f"https://www.youtube.com/watch?v={key}",
                    "official": v.get("official", False),
                })

        # Deduplicate by key and limit to 5
        seen = set()
        unique_trailers = []
        for t in trailers:
            if t["key"] not in seen:
                seen.add(t["key"])
                unique_trailers.append(t)
                if len(unique_trailers) >= 5:
                    break

        # If no video in TMDB, create a guaranteed official YouTube trailer search fallback
        if not unique_trailers:
            try:
                m_details = await _tmdb_get(f"/movie/{tmdb_id}", {})
                title = m_details.get("title") or "Movie"
                encoded = urllib.parse.quote_plus(f"{title} official trailer")
                unique_trailers.append({
                    "key": None,
                    "name": f"{title} — Official Trailer",
                    "type": "Trailer",
                    "site": "YouTube",
                    "embed_url": f"https://www.youtube.com/embed?listType=search&list={encoded}&autoplay=1",
                    "watch_url": f"https://www.youtube.com/results?search_query={encoded}",
                    "official": True,
                })
            except Exception:
                pass

        await cache_service.videos_cache.set(cache_key, unique_trailers)
        return unique_trailers
    except HTTPException:
        return []


async def get_movie_candidates(tmdb_id: int, limit: int = 50) -> List[dict]:
    """
    Fetches 30-100 candidate movies for the given TMDB ID by combining
    /movie/{id}/recommendations and /movie/{id}/similar.
    Each candidate is a card dict. Never returns the full catalog.
    """
    cache_key = f"candidates:{tmdb_id}:{limit}"
    cached = await cache_service.tmdb_details_cache.get(cache_key)
    if cached is not None:
        return cached

    results: List[dict] = []
    seen_ids: set = {tmdb_id}

    for endpoint in [f"/movie/{tmdb_id}/recommendations", f"/movie/{tmdb_id}/similar"]:
        try:
            data = await _tmdb_get(endpoint, {"language": "en-US", "page": 1})
            for m in data.get("results", []):
                mid = int(m.get("id", 0))
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    results.append(_card_from_result(m))
        except HTTPException:
            pass  # If one endpoint fails, continue with the other

        if len(results) >= limit:
            break

    results = results[:limit]
    await cache_service.tmdb_details_cache.set(cache_key, results, ttl=300.0)
    return results


async def discover_movies(
    genre_id: Optional[int] = None,
    original_language: Optional[str] = None,
    region: Optional[str] = None,
    sort_by: str = "popularity.desc",
    exclude_tmdb_id: Optional[int] = None,
    page: int = 1,
    limit: int = 24,
) -> List[dict]:
    """
    Flexible TMDB /discover/movie wrapper.
    Args:
        genre_id:           TMDB genre ID to filter by.
        original_language:  ISO 639-1 code (e.g. "hi" for Hindi, "ko" for Korean).
        region:             ISO 3166-1 code (e.g. "IN" for India, "US" for US).
        sort_by:            Sort order (popularity.desc, vote_average.desc, etc.).
        exclude_tmdb_id:    Movie TMDB ID to remove from results.
        page:               TMDB page number (1–500).
        limit:              Maximum number of results to return.
    Returns:
        List of card dicts.
    """
    cache_key = f"discover:{genre_id}:{original_language}:{region}:{sort_by}:{page}:{limit}"
    cached = await cache_service.discovery_cache.get(cache_key)
    if cached is not None:
        cards = cached
    else:
        params: Dict[str, Any] = {
            "language": "en-US",
            "sort_by": sort_by,
            "page": page,
            "include_adult": "false",
            "vote_count.gte": 20,  # Minimum votes to avoid low-quality titles
        }
        if genre_id:
            params["with_genres"] = genre_id
        if original_language:
            params["with_original_language"] = original_language
        if region:
            params["region"] = region

        data = await _tmdb_get("/discover/movie", params)
        cards = [_card_from_result(m) for m in data.get("results", [])]
        await cache_service.discovery_cache.set(cache_key, cards)

    if exclude_tmdb_id:
        cards = [c for c in cards if c["tmdb_id"] != exclude_tmdb_id]
    return cards[:limit]


async def discover_by_genre(
    genre_id: int, exclude_tmdb_id: Optional[int] = None, limit: int = 18
) -> List[dict]:
    """Discover popular movies in a given genre."""
    return await discover_movies(
        genre_id=genre_id,
        sort_by="popularity.desc",
        exclude_tmdb_id=exclude_tmdb_id,
        limit=limit,
    )


async def get_indian_cinema(
    language: Optional[str] = None,
    sort_by: str = "popularity.desc",
    page: int = 1,
    limit: int = 24,
) -> List[dict]:
    """
    Curated Indian cinema feed.
    If language is provided (e.g. "hi", "te", "ta"), filters by that language.
    Otherwise fetches most popular across all Indian languages.

    Args:
        language:  ISO 639-1 code — "hi" (Hindi), "te" (Telugu), "ta" (Tamil),
                   "ml" (Malayalam), "kn" (Kannada), "bn" (Bengali), etc.
        sort_by:   Sort order.
        page:      TMDB page number.
        limit:     Max results.
    """
    if language and language in _INDIAN_LANG_CODES:
        return await discover_movies(
            original_language=language,
            sort_by=sort_by,
            page=page,
            limit=limit,
        )

    # No specific language — fetch across all Indian languages in parallel
    tasks = [
        discover_movies(original_language=lang, sort_by=sort_by, page=page, limit=10)
        for lang in ["hi", "te", "ta", "ml", "kn"]
    ]
    results_per_lang = await asyncio.gather(*tasks, return_exceptions=True)

    seen_ids: set = set()
    combined = []
    for result in results_per_lang:
        if isinstance(result, Exception):
            continue
        for card in result:
            if card["tmdb_id"] not in seen_ids:
                seen_ids.add(card["tmdb_id"])
                combined.append(card)

    # Sort combined by vote_average or popularity (popularity not in card, sort by vote_average desc)
    combined.sort(key=lambda x: x.get("vote_average") or 0, reverse=True)
    return combined[:limit]


async def get_international_cinema(
    language: Optional[str] = None,
    sort_by: str = "popularity.desc",
    page: int = 1,
    limit: int = 24,
) -> List[dict]:
    """
    Curated world / international cinema feed (non-English, non-Indian).
    If language is specified (e.g. "ko", "fr"), filters by that language.
    Otherwise samples from popular world cinema languages.
    """
    if language and language in _WORLD_CINEMA_LANGS:
        return await discover_movies(
            original_language=language,
            sort_by=sort_by,
            page=page,
            limit=limit,
        )

    # Sample from key world cinema languages
    sample_langs = ["ko", "ja", "fr", "es", "de"]
    tasks = [
        discover_movies(original_language=lang, sort_by=sort_by, page=page, limit=8)
        for lang in sample_langs
    ]
    results_per_lang = await asyncio.gather(*tasks, return_exceptions=True)

    seen_ids: set = set()
    combined = []
    for result in results_per_lang:
        if isinstance(result, Exception):
            continue
        for card in result:
            if card["tmdb_id"] not in seen_ids:
                seen_ids.add(card["tmdb_id"])
                combined.append(card)

    combined.sort(key=lambda x: x.get("vote_average") or 0, reverse=True)
    return combined[:limit]


async def get_home_feed(category: str = "popular", limit: int = 24) -> List[dict]:
    """Home feed: trending, popular, top_rated, upcoming, now_playing."""
    cache_key = f"home:{category}:{limit}"
    cached = await cache_service.home_feed_cache.get(cache_key)
    if cached is not None:
        return cached

    if category == "trending":
        data = await _tmdb_get("/trending/movie/day", {"language": "en-US"})
    elif category in {"popular", "top_rated", "upcoming", "now_playing"}:
        data = await _tmdb_get(f"/movie/{category}", {"language": "en-US", "page": 1})
    else:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    cards = [_card_from_result(m) for m in data.get("results", [])[:limit]]
    await cache_service.home_feed_cache.set(cache_key, cards)
    return cards
