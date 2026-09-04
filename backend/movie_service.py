"""
movie_service.py — Hybrid coordinator that unifies local ML recommendations
with live TMDB metadata.

This module is the single entry-point for the /recommend endpoint.
It encapsulates the 4-scenario hybrid decision tree:

  1. Local query  -> Local dataset    (pre-computed tfidf_matrix row)
  2. Local query  -> External cands  (cosine vs TMDB candidates)
  3. External query -> Local dataset  (transform query, cosine vs matrix)
  4. External query -> External cands (transform both, cosine similarity)

Returns a structured MovieRecommendationResult dict ready for JSON response.
"""
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from backend import config, recommender, tmdb_service, feature_builder
from backend import cache_service

# Semaphore to limit concurrent TMDB poster lookups
_POSTER_SEM = asyncio.Semaphore(16)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _rec_item(title: str, score: float, tmdb_card: Optional[dict] = None) -> dict:
    """Formats a single recommendation item for the API response."""
    base = {
        "title": title,
        "score": round(float(score), 4),
        "score_pct": min(100, max(0, round(float(score) * 100))),
    }
    if tmdb_card:
        base.update({
            "tmdb_id": tmdb_card.get("tmdb_id"),
            "poster_url": tmdb_card.get("poster_url"),
            "backdrop_url": tmdb_card.get("backdrop_url"),
            "release_date": tmdb_card.get("release_date"),
            "vote_average": tmdb_card.get("vote_average"),
            "overview": tmdb_card.get("overview"),
            "original_language": tmdb_card.get("original_language"),
        })
    return base


async def _attach_poster(title: str) -> Optional[dict]:
    """Best-effort TMDB poster lookup for a local-dataset title (rate-limited)."""
    async with _POSTER_SEM:
        try:
            m = await tmdb_service.search_movie_first(title)
            if m:
                return tmdb_service._card_from_result(m)
            return None
        except Exception:
            return None


async def _enrich_local_rec(title: str, score: float) -> dict:
    """Attach TMDB card data to a local recommendation."""
    card = await _attach_poster(title)
    return _rec_item(title, score, card)


# ─────────────────────────────────────────────────────────────────────────────
# Public: Hybrid Recommendation
# ─────────────────────────────────────────────────────────────────────────────

async def get_recommendations(
    query: Optional[str] = None,
    tmdb_id: Optional[int] = None,
    language: Optional[str] = None,
    year: Optional[int] = None,
    local_top_n: int = 20,
    external_top_n: int = 20,
    genre_limit: int = 20,
    local_offset: int = 0,
    external_offset: int = 0,
) -> dict:
    """
    Unified hybrid recommendation pipeline.
    Accepts either text 'query', exact 'tmdb_id', or both.
    When 'tmdb_id' is provided, eliminates search ambiguity completely.
    """
    warnings: List[str] = []
    local_recs: List[dict] = []
    external_recs: List[dict] = []
    genre_recs: List[dict] = []
    movie_meta: Optional[dict] = None
    movie_source = "unknown"
    tmdb_details: Optional[dict] = None

    # ── Step 1: Resolve movie (direct TMDB ID first, else title search) ──────
    if tmdb_id:
        try:
            tmdb_details = await tmdb_service.get_movie_details(int(tmdb_id))
        except HTTPException:
            warnings.append("TMDB is temporarily unavailable — attempting title fallback.")
        except Exception:
            pass

    resolved_title = (tmdb_details.get("title") if tmdb_details else None) or (query.strip() if query else "")

    if not tmdb_details and resolved_title:
        try:
            tmdb_match = await tmdb_service.search_movie_first(
                resolved_title, year=year, language=language
            )
            if tmdb_match:
                tmdb_details = await tmdb_service.get_movie_details(int(tmdb_match["id"]))
        except HTTPException:
            warnings.append("TMDB is temporarily unavailable — showing local results only.")
        except Exception:
            warnings.append("Could not reach TMDB — showing local results only.")

    is_local = recommender.title_exists(resolved_title) if resolved_title else False
    local_row = recommender.get_local_row(resolved_title) if (is_local and not tmdb_id) else None

    if tmdb_details:
        movie_source = "local_dataset" if is_local else "tmdb_only"
        movie_meta = {
            "title": tmdb_details.get("title", resolved_title),
            "overview": tmdb_details.get("overview", "") or (str(local_row.get("overview", "")) if local_row else ""),
            "genres": " ".join(g["name"] for g in tmdb_details.get("genres", []) if g.get("name")),
            "genres_list": tmdb_details.get("genres", []),
            "tagline": tmdb_details.get("tagline", "") or (str(local_row.get("tagline", "")) if local_row else ""),
            "poster_url": tmdb_details.get("poster_url"),
            "backdrop_url": tmdb_details.get("backdrop_url"),
            "release_date": tmdb_details.get("release_date"),
            "vote_average": tmdb_details.get("vote_average"),
            "vote_count": tmdb_details.get("vote_count"),
            "runtime": tmdb_details.get("runtime"),
            "tmdb_id": tmdb_details.get("tmdb_id"),
            "original_language": tmdb_details.get("original_language"),
            "production_companies": tmdb_details.get("production_companies", []),
            "imdb_id": tmdb_details.get("imdb_id", ""),
            "source": movie_source,
        }
    elif local_row is not None:
        movie_source = "local_dataset"
        movie_meta = {
            "title": str(local_row["title"]),
            "overview": str(local_row.get("overview", "") or ""),
            "genres": str(local_row.get("genres", "") or ""),
            "tagline": str(local_row.get("tagline", "") or ""),
            "source": movie_source,
        }
    else:
        return {
            "status": "not_found",
            "detail": f"'{resolved_title or tmdb_id}' was not found in the local dataset or on TMDB.",
            "warnings": [],
            "movie": None,
            "recommendations": {
                "local_similarity": [],
                "external_similarity": [],
                "genre_recommendations": [],
            },
            "pagination": {
                "local_offset": local_offset,
                "local_top_n": local_top_n,
                "external_offset": external_offset,
                "external_top_n": external_top_n,
            },
        }

    # ── Step 2: Local similarity recommendations ──────────────────────────────
    if local_row is not None:
        # Scenario 1: Local -> Local
        raw_local = recommender.recommend_local_to_local(
            resolved_title, top_n=local_top_n, offset=local_offset
        )
    else:
        # Scenario 3: External -> Local
        feat_str = feature_builder.build_movie_features(
            overview=movie_meta.get("overview"),
            genres=tmdb_details.get("genres") if tmdb_details else None,
            tagline=movie_meta.get("tagline"),
        )
        raw_local = recommender.recommend_external_to_local(
            feat_str, top_n=local_top_n, offset=local_offset, exclude_title=resolved_title
        )

    # Attach TMDB posters in parallel
    if raw_local:
        enrich_tasks = [_enrich_local_rec(t, s) for t, s in raw_local]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*enrich_tasks, return_exceptions=True),
                timeout=18.0,
            )
            local_recs = []
            for i, res in enumerate(results):
                if isinstance(res, dict):
                    local_recs.append(res)
                else:
                    local_recs.append(_rec_item(raw_local[i][0], raw_local[i][1]))
        except asyncio.TimeoutError:
            local_recs = [_rec_item(t, s) for t, s in raw_local]
    else:
        warnings.append("No local content matches found for this title.")

    # ── Step 3: External (TMDB candidate) recommendations ────────────────────
    if tmdb_details and config.tmdb_configured():
        try:
            tmdb_id = tmdb_details["tmdb_id"]

            # Optionally fetch keywords for richer query vector
            keywords = []
            try:
                keywords = await tmdb_service.get_movie_keywords(tmdb_id)
            except Exception:
                pass

            query_feat = feature_builder.build_movie_features(
                overview=tmdb_details.get("overview"),
                genres=tmdb_details.get("genres"),
                tagline=tmdb_details.get("tagline"),
                keywords=keywords,
            )

            candidates = await tmdb_service.get_movie_candidates(tmdb_id, limit=60)

            enriched_candidates = []
            for c in candidates:
                c_feat = feature_builder.build_movie_features(
                    overview=c.get("overview"),
                    genres=None,
                    tagline=None,
                )
                c["feature_str"] = c_feat
                enriched_candidates.append(c)

            ranked = recommender.recommend_from_candidates(
                query_feature_str=query_feat,
                query_title=query if is_local else None,
                candidates=enriched_candidates,
                top_n=external_top_n,
                offset=external_offset,
            )

            external_recs = [
                _rec_item(candidate.get("title", ""), score, candidate)
                for candidate, score in ranked
            ]

        except HTTPException:
            warnings.append("TMDB external recommendations unavailable.")
        except Exception:
            warnings.append("External similarity search failed.")

    # ── Step 4: Genre recommendations ─────────────────────────────────────────
    if tmdb_details and config.tmdb_configured():
        try:
            genres_list = tmdb_details.get("genres", [])
            if genres_list:
                genre_id = genres_list[0]["id"]
                genre_recs = await tmdb_service.discover_by_genre(
                    genre_id=genre_id,
                    exclude_tmdb_id=tmdb_details.get("tmdb_id"),
                    limit=genre_limit,
                )
        except HTTPException:
            warnings.append("Genre recommendations unavailable.")
        except Exception:
            warnings.append("Genre discovery failed.")

    # ── Step 5: Build response ─────────────────────────────────────────────────
    status = "success"
    if warnings:
        status = "partial_success"
    if not local_recs and not external_recs and not genre_recs:
        status = "error"

    return {
        "status": status,
        "movie": movie_meta,
        "recommendations": {
            "local_similarity": local_recs,
            "external_similarity": external_recs,
            "genre_recommendations": genre_recs,
        },
        "pagination": {
            "local_offset": local_offset,
            "local_top_n": local_top_n,
            "external_offset": external_offset,
            "external_top_n": external_top_n,
        },
        "warnings": warnings,
    }


async def get_full_movie_details(tmdb_id: int) -> dict:
    """
    Fetches enriched movie details including credits and trailers in parallel.
    Returns a combined dict with: details + cast + director + trailers.
    """
    details_coro = tmdb_service.get_movie_details(tmdb_id)
    credits_coro = tmdb_service.get_movie_credits(tmdb_id)
    trailers_coro = tmdb_service.get_movie_trailers(tmdb_id)

    details, credits, trailers = await asyncio.gather(
        details_coro, credits_coro, trailers_coro, return_exceptions=True
    )

    result = {}
    if isinstance(details, dict):
        result.update(details)
    else:
        raise HTTPException(status_code=502, detail="Failed to fetch movie details.")

    if isinstance(credits, dict):
        result["cast"] = credits.get("cast", [])
        result["crew"] = credits.get("crew", [])
        result["director"] = credits.get("director")
        result["writers"] = credits.get("writers", [])
    else:
        result["cast"] = []
        result["crew"] = []
        result["director"] = None
        result["writers"] = []

    result["trailers"] = trailers if isinstance(trailers, list) else []

    return result
