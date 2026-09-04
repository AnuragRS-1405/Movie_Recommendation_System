"""
recommender.py — Loads all ML artifacts once at startup and exposes
clean recommendation functions.

v5.0 Changes:
  - All recommend_* functions now support offset + limit for pagination.
  - No arbitrary top-N cap: full similarity array is scored, then sliced.
  - suggest_titles supports TMDB-only fallback hint.
  - recommend_local_to_local, recommend_external_to_local, and
    recommend_from_candidates all return (title, score) or (dict, score)
    tuples — callers decide how many to show via offset/limit.

Supports all 4 hybrid scenarios:
  1. Local query  -> Local dataset    (tfidf_matrix row lookup)
  2. Local query  -> External cands  (transform candidates, cosine vs query vec)
  3. External query -> Local dataset (transform query, cosine vs tfidf_matrix)
  4. External query -> External cands (transform both, cosine similarity)
"""
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.config import DF_PATH, INDICES_PATH, TFIDF_PATH, TFIDF_MATRIX_PATH

# ── Module-level ML globals (loaded once at startup) ─────────────────────────
_df: Optional[pd.DataFrame] = None
_indices: Any = None                # pandas Series (title -> df index)
_tfidf_matrix: Any = None           # sparse CSR matrix (45447 x 50000)
_tfidf_obj: Any = None              # fitted TfidfVectorizer
_title_to_idx: Optional[Dict[str, int]] = None  # normalized lower-case map


# ── Initialization ────────────────────────────────────────────────────────────
def _resolve_pkl(path: Path) -> Path:
    """Case-insensitive pickle lookup (handles Df.pkl vs df.pkl on Linux)."""
    if path.is_file():
        return path
    parent = path.parent
    stem_lower = path.name.lower()
    for f in parent.iterdir():
        if f.name.lower() == stem_lower:
            return f
    raise FileNotFoundError(
        f"Pickle not found: {path}. "
        f"Ensure all .pkl files are inside the 'models/' folder."
    )


def load_models() -> None:
    """
    Load all 4 pickle files into module globals.
    Called once during FastAPI startup — subsequent requests use cached globals.
    """
    global _df, _indices, _tfidf_matrix, _tfidf_obj, _title_to_idx

    with open(_resolve_pkl(DF_PATH), "rb") as f:
        _df = pickle.load(f)

    with open(_resolve_pkl(INDICES_PATH), "rb") as f:
        _indices = pickle.load(f)

    with open(_resolve_pkl(TFIDF_MATRIX_PATH), "rb") as f:
        _tfidf_matrix = pickle.load(f)

    with open(_resolve_pkl(TFIDF_PATH), "rb") as f:
        _tfidf_obj = pickle.load(f)

    # Build normalized lookup map
    _title_to_idx = _build_title_map(_indices)

    if _df is None or "title" not in _df.columns:
        raise RuntimeError("Df.pkl must contain a DataFrame with a 'title' column.")

    print(
        f"[recommender] Loaded {len(_df)} movies "
        f"({len(_title_to_idx)} unique titles indexed)."
    )


def _build_title_map(indices: Any) -> Dict[str, int]:
    """Build a lower-cased title -> row-index map from Indices.pkl (Series or dict)."""
    result: Dict[str, int] = {}
    try:
        for k, v in indices.items():
            result[str(k).strip().lower()] = int(v)
    except Exception as exc:
        raise RuntimeError(
            "Indices.pkl must be a dict or pandas Series with .items()"
        ) from exc
    return result


# ── Accessors ─────────────────────────────────────────────────────────────────
def is_loaded() -> bool:
    return _df is not None and _tfidf_matrix is not None


def dataset_size() -> int:
    return len(_df) if _df is not None else 0


def local_titles() -> pd.Series:
    if _df is None:
        return pd.Series([], dtype=str)
    return _df["title"]


def title_exists(title: str) -> bool:
    if _title_to_idx is None:
        return False
    return title.strip().lower() in _title_to_idx


def suggest_titles(query: str, limit: int = 10) -> List[str]:
    if _df is None:
        return []
    pattern = re.escape(query.strip().lower())
    mask = _df["title"].str.lower().str.contains(pattern, na=False, regex=True)
    return _df.loc[mask, "title"].drop_duplicates().head(limit).tolist()


def get_local_row(title: str) -> Optional[pd.Series]:
    """Returns the df row for a local title, or None if not found."""
    if _df is None or _title_to_idx is None:
        return None
    key = title.strip().lower()
    idx = _title_to_idx.get(key)
    if idx is None:
        return None
    return _df.iloc[int(idx)]


# ── Scenario 1: Local -> Local ─────────────────────────────────────────────────
def recommend_local_to_local(
    title: str,
    top_n: int = 20,
    offset: int = 0,
) -> List[Tuple[str, float]]:
    """
    Uses the pre-computed TFIDF_Matrix row for a local title.
    Returns list of (title, cosine_score) sorted descending, excluding query.

    Args:
        title:  Movie title to look up in the local dataset.
        top_n:  Maximum number of results to return (default 20, was 12).
        offset: Number of top results to skip — enables pagination.
    """
    if not is_loaded():
        return []

    key = title.strip().lower()
    idx = _title_to_idx.get(key) if _title_to_idx else None
    if idx is None:
        return []

    query_vec = _tfidf_matrix[int(idx)]
    scores = (_tfidf_matrix @ query_vec.T).toarray().ravel()
    order = np.argsort(-scores)

    results: List[Tuple[str, float]] = []
    skipped = 0
    for i in order:
        if int(i) == int(idx):
            continue
        try:
            t = str(_df.iloc[int(i)]["title"])
        except Exception:
            continue

        # Support offset-based pagination
        if skipped < offset:
            skipped += 1
            continue

        results.append((t, float(scores[int(i)])))
        if len(results) >= top_n:
            break
    return results


# ── Scenario 3: External -> Local ─────────────────────────────────────────────
def recommend_external_to_local(
    feature_str: str,
    top_n: int = 20,
    offset: int = 0,
    exclude_title: Optional[str] = None,
) -> List[Tuple[str, float]]:
    """
    Vectorizes a TMDB movie's features using tfidf_obj.transform(), then
    compares against the full local TFIDF_Matrix.
    Returns list of (title, cosine_score) sorted descending.

    Args:
        feature_str:    Preprocessed feature string from feature_builder.
        top_n:          Maximum number of results to return.
        offset:         Skip first N results for pagination.
        exclude_title:  Title to exclude from results (usually the query movie).
    """
    if not is_loaded():
        return []

    query_vec = _tfidf_obj.transform([feature_str])
    scores = (_tfidf_matrix @ query_vec.T).toarray().ravel()
    order = np.argsort(-scores)

    exclude_key = exclude_title.strip().lower() if exclude_title else None
    results: List[Tuple[str, float]] = []
    skipped = 0
    for i in order:
        try:
            t = str(_df.iloc[int(i)]["title"])
        except Exception:
            continue
        if exclude_key and t.strip().lower() == exclude_key:
            continue

        if skipped < offset:
            skipped += 1
            continue

        results.append((t, float(scores[int(i)])))
        if len(results) >= top_n:
            break
    return results


# ── Scenario 2 & 4: Vector -> Candidates ──────────────────────────────────────
def recommend_from_candidates(
    query_feature_str: Optional[str],
    query_title: Optional[str],
    candidates: List[Dict],
    top_n: int = 20,
    offset: int = 0,
) -> List[Tuple[Dict, float]]:
    """
    Ranks a pool of candidate TMDB movies against the query movie using
    the shared TF-IDF vectorizer. Candidates must contain 'feature_str' key.

    For Scenario 2 (local query -> external candidates):
      - Pass query_title (local) -> fetches its vector from tfidf_matrix
    For Scenario 4 (external query -> external candidates):
      - Pass query_feature_str -> transforms via tfidf_obj

    Args:
        query_feature_str:  Preprocessed feature string if query is external.
        query_title:        Local title if query is in the local dataset.
        candidates:         List of candidate dicts (must each have 'feature_str').
        top_n:              Maximum number of results to return.
        offset:             Skip first N results for pagination.

    Returns:
        List of (candidate_dict, cosine_score) sorted descending.
    """
    if not is_loaded() or not candidates:
        return []

    # Determine query vector
    if query_title is not None:
        key = query_title.strip().lower()
        idx = _title_to_idx.get(key) if _title_to_idx else None
        if idx is not None:
            query_vec = _tfidf_matrix[int(idx)]
        elif query_feature_str:
            query_vec = _tfidf_obj.transform([query_feature_str])
        else:
            return []
    elif query_feature_str is not None:
        query_vec = _tfidf_obj.transform([query_feature_str])
    else:
        return []

    # Vectorize all candidates that have a feature_str
    valid_candidates = [c for c in candidates if c.get("feature_str")]
    if not valid_candidates:
        return []

    candidate_features = [c["feature_str"] for c in valid_candidates]
    candidate_matrix = _tfidf_obj.transform(candidate_features)

    # Cosine similarity: query_vec (1xV) x candidate_matrix.T (VxN) -> (1xN)
    scores = (candidate_matrix @ query_vec.T).toarray().ravel()
    order = np.argsort(-scores)

    results: List[Tuple[Dict, float]] = []
    for rank, i in enumerate(order):
        if rank < offset:
            continue
        results.append((valid_candidates[int(i)], float(scores[int(i)])))
        if len(results) >= top_n:
            break
    return results


# ── Count helpers for pagination metadata ─────────────────────────────────────
def count_local_matches(title: str) -> int:
    """Returns total number of local similarity matches for a given title."""
    if not is_loaded():
        return 0
    key = title.strip().lower()
    idx = _title_to_idx.get(key) if _title_to_idx else None
    if idx is None:
        return 0
    # All movies except the query itself
    return max(0, len(_df) - 1)
