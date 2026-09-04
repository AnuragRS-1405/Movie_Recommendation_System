"""
feature_builder.py — Replicates the EXACT preprocessing pipeline from
Movie_RecSys_ML_NLP.ipynb so that TMDB-sourced data can be vectorized
by the same TFIDF.pkl that was trained on the local dataset.

Notebook pipeline (cells 16–33):
  1. Columns: title, overview, genres, tagline, vote_average, popularity
  2. genres: parsed from JSON-like string -> space-joined names
  3. overview + tagline: NaN -> ''
  4. tags = overview + " " + genres + " " + tagline
  5. preprocess_text:
       - str().lower()
       - re.sub(r'[^a-zA-Z\\s]', '', text)
       - split() -> remove NLTK English stopwords
       - WordNetLemmatizer().lemmatize(word) for each word
       - " ".join(words)
  6. TfidfVectorizer(max_features=50000, ngram_range=(1,2), stop_words='english')

v5.0 additions (backward-compatible):
  - Optional keywords, cast names, director name, and original_language
    are appended to the tag string before preprocessing.
  - All new fields default to None/empty so old call sites are unaffected.
"""
import re
from typing import Dict, List, Optional, Union

import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

# ── NLTK resource bootstrap (downloads only if not already present) ─────────
def _ensure_nltk():
    for pkg, path in [("stopwords", "corpora/stopwords"), ("wordnet", "corpora/wordnet")]:
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(pkg, quiet=True)

_ensure_nltk()

_STOP_WORDS = set(stopwords.words("english"))
_LEMMATIZER = WordNetLemmatizer()


# ── Text preprocessing (exact mirror of notebook cell 32) ───────────────────
def preprocess_text(text: str) -> str:
    """
    Replicates the notebook's preprocess_text() function exactly:
      - lowercase
      - remove non-alpha characters (keep spaces)
      - remove NLTK English stopwords
      - lemmatize each remaining word
    """
    text = str(text).lower()
    text = re.sub(r"[^a-zA-Z\s]", "", text)
    words = text.split()
    words = [w for w in words if w not in _STOP_WORDS]
    words = [_LEMMATIZER.lemmatize(w) for w in words]
    return " ".join(words)


def _parse_genres(genres: Union[List[dict], str, None]) -> str:
    """
    Convert TMDB genres to the space-joined format used in training:
        [{"id": 16, "name": "Animation"}, ...] -> "Animation Comedy Family"

    Handles:
      - List of dicts (live TMDB response)
      - Stringified list (as stored in CSV: "[{'id':16,'name':'Animation'}]")
      - Empty list / None
    """
    if not genres:
        return ""

    if isinstance(genres, list):
        return " ".join(g.get("name", "") for g in genres if g.get("name"))

    if isinstance(genres, str):
        import ast
        try:
            parsed = ast.literal_eval(genres)
            if isinstance(parsed, list):
                return " ".join(g.get("name", "") for g in parsed if g.get("name"))
        except (ValueError, SyntaxError):
            pass

    return ""


def _parse_keywords(keywords: Union[List[dict], List[str], str, None]) -> str:
    """
    Convert TMDB keywords to a space-joined string.
    Handles:
      - List of dicts: [{"id": 1, "name": "space opera"}, ...]
      - List of strings: ["space opera", "hero"]
      - Stringified list
      - None / empty
    """
    if not keywords:
        return ""

    if isinstance(keywords, list):
        parts = []
        for k in keywords:
            if isinstance(k, dict):
                name = k.get("name", "")
            else:
                name = str(k)
            if name:
                parts.append(name)
        return " ".join(parts)

    if isinstance(keywords, str):
        import ast
        try:
            parsed = ast.literal_eval(keywords)
            if isinstance(parsed, list):
                return _parse_keywords(parsed)
        except (ValueError, SyntaxError):
            return keywords  # treat as raw string

    return ""


def _parse_cast(cast: Union[List[dict], List[str], None], max_cast: int = 5) -> str:
    """
    Extract top cast names (first max_cast entries) from a TMDB credits cast list.
    Each name is lowercased and space-stripped to improve TF-IDF matching.
    """
    if not cast:
        return ""

    names = []
    for c in cast[:max_cast]:
        if isinstance(c, dict):
            name = c.get("name", "")
        else:
            name = str(c)
        if name:
            # Remove spaces within names for TF-IDF (e.g. "LeonardoDiCaprio")
            names.append(name.replace(" ", ""))

    return " ".join(names)


def _parse_director(crew: Union[List[dict], str, None]) -> str:
    """
    Extract director name(s) from a TMDB credits crew list.
    Returns an empty string if crew is not provided.
    """
    if not crew:
        return ""

    if isinstance(crew, list):
        directors = [
            c.get("name", "").replace(" ", "")
            for c in crew
            if isinstance(c, dict) and c.get("job", "").lower() == "director" and c.get("name")
        ]
        return " ".join(directors)

    return ""


def build_movie_features(
    overview: Optional[str] = None,
    genres: Union[List[dict], str, None] = None,
    tagline: Optional[str] = None,
    # v5.0 optional expansions
    keywords: Union[List[dict], List[str], str, None] = None,
    cast: Union[List[dict], List[str], None] = None,
    crew: Union[List[dict], None] = None,
    original_language: Optional[str] = None,
) -> str:
    """
    Builds and preprocesses the 'tags' feature string for a movie — exactly
    matching the notebook's pipeline so it can be fed into TFIDF.pkl.transform().

    Args:
        overview:           Movie overview / plot synopsis (may be None or empty).
        genres:             List of genre dicts from TMDB, OR a stringified list from CSV.
        tagline:            Movie tagline (may be None or empty).
        keywords:           List of keyword dicts/strings from TMDB /movie/{id}/keywords.
        cast:               List of cast dicts from TMDB /movie/{id}/credits.
        crew:               List of crew dicts from TMDB /movie/{id}/credits.
        original_language:  ISO 639-1 language code (e.g. "en", "hi", "ko").

    Returns:
        Preprocessed feature string ready for tfidf.transform([result]).
    """
    overview_str = str(overview) if overview else ""
    genres_str = _parse_genres(genres)
    tagline_str = str(tagline) if tagline else ""

    # v5.0 optional additions
    keywords_str = _parse_keywords(keywords) if keywords else ""
    cast_str = _parse_cast(cast) if cast else ""
    director_str = _parse_director(crew) if crew else ""
    lang_str = str(original_language).strip() if original_language else ""

    # Base formula (notebook cell 26): tags = overview + genres + tagline
    # v5.0: also append keywords, cast, director, language when present
    parts = [overview_str, genres_str, tagline_str, keywords_str, cast_str, director_str, lang_str]
    raw_tags = " ".join(p for p in parts if p)

    return preprocess_text(raw_tags)
