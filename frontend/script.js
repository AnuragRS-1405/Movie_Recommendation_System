"use strict";

/* ================================================================
   CineMatch v5.0 — script.js
   Single Page Application (SPA) Controller:
   - Unified Home View & Movie Details View
   - Eager loading for above-fold posters + IntersectionObserver lazy-loading
   - Interactive Settings Popover, Theme Toggling, and Autocomplete Search
   - Personal Watchlist Engine with localStorage persistence
   - Carousel shelf smooth arrow navigation
   - Guaranteed multi-tier official trailer playback
   ================================================================ */

// ── Application Configuration & State ─────────────────────────────
const DEFAULT_API = "https://movie-recommendation-system-2ajd.onrender.com";

const STORAGE_KEYS = {
  theme: "cinematch_theme",
  api: "cinematch_api_base",
  watchlist: "cinematch_watchlist",
};

const APP = {
  apiBase: localStorage.getItem(STORAGE_KEYS.api) || DEFAULT_API,
  category: "popular",
  settingsOpen: false,
  currentView: "home", // "home" | "detail"
  lastFocus: null,
};

// ── DOM Helper Utilities ──────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const esc = (str) => {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
};

const formatYear = (dateStr) => {
  const year = String(dateStr || "").slice(0, 4);
  return /^\d{4}$/.test(year) ? year : "";
};

const debounce = (callback, delayMs) => {
  let timerId;
  return (...args) => {
    clearTimeout(timerId);
    timerId = setTimeout(() => callback(...args), delayMs);
  };
};

const LANG = {
  en: "EN",
  hi: "HI",
  te: "TE",
  ta: "TA",
  ml: "ML",
  kn: "KN",
  bn: "BN",
  mr: "MR",
  pa: "PA",
  gu: "GU",
  ko: "KO",
  ja: "JA",
  fr: "FR",
  es: "ES",
  de: "DE",
  it: "IT",
  zh: "ZH",
  pt: "PT",
  ru: "RU",
  ar: "AR",
  tr: "TR",
};

const CAT_LABELS = {
  popular: ["Popular right now", "Pick a poster to explore AI content recommendations."],
  top_rated: ["Top rated masterpieces", "The highest-scoring titles across cinema."],
  now_playing: ["Now playing in theaters", "Currently showing on the big screen."],
  upcoming: ["Upcoming releases", "Exciting movies arriving soon to screens."],
  trending: ["Trending today", "What viewers worldwide are watching right now."],
  watchlist: ["My Watchlist", "Your personal collection of saved movies."],
};

// ── API Communication ─────────────────────────────────────────────
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function apiGet(endpointPath) {
  let response;
  const baseUrl = APP.apiBase.replace(/\/+$/, "");

  try {
    response = await fetch(baseUrl + endpointPath);
  } catch {
    throw new ApiError(
      `Can't reach backend at ${APP.apiBase}. Is main.py running?`,
      0
    );
  }

  let responseBody = null;
  try {
    responseBody = await response.json();
  } catch {
    // Non-JSON response
  }

  if (!response.ok) {
    const detailMsg =
      (responseBody &&
        (responseBody.detail ||
          responseBody.error ||
          responseBody.message)) ||
      `HTTP ${response.status}`;
    throw new ApiError(
      typeof detailMsg === "string" ? detailMsg : JSON.stringify(detailMsg),
      response.status
    );
  }

  return responseBody;
}

// ── Toast Notification System ─────────────────────────────────────
let _toastTimer;

function toast(message, isError = false) {
  const toastEl = $("toast");
  if (!toastEl) return;

  toastEl.textContent = message;
  toastEl.classList.toggle("is-error", isError);
  toastEl.hidden = false;

  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    toastEl.hidden = true;
  }, 4200);
}

// ── Notification Banner System ────────────────────────────────────
function showBanner(htmlContent, bannerType = "") {
  const bannerEl = $("banner");
  if (!bannerEl) return;

  bannerEl.innerHTML = htmlContent;
  bannerEl.className = "banner" + (bannerType ? ` banner--${bannerType}` : "");
  bannerEl.hidden = false;
}

function hideBanner() {
  const bannerEl = $("banner");
  if (bannerEl) {
    bannerEl.hidden = true;
    bannerEl.className = "banner";
  }
}

function warnBanner(warnings) {
  if (warnings && warnings.length > 0) {
    showBanner("⚠️ " + warnings.map(esc).join(" · "), "warning");
  }
}

// ── Watchlist Engine (LocalStorage) ───────────────────────────────
function getWatchlist() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEYS.watchlist) || "[]");
  } catch {
    return [];
  }
}

function isWatchlisted(title, tmdbId = null) {
  const list = getWatchlist();
  return list.some(
    (item) =>
      (tmdbId && item.tmdb_id && item.tmdb_id === tmdbId) ||
      (item.title && title && item.title.toLowerCase() === title.toLowerCase())
  );
}

function toggleWatchlist(movie) {
  const list = getWatchlist();
  const title = movie.title || "Untitled";
  const tmdbId = movie.tmdb_id || null;

  const existingIndex = list.findIndex(
    (item) =>
      (tmdbId && item.tmdb_id && item.tmdb_id === tmdbId) ||
      (item.title && item.title.toLowerCase() === title.toLowerCase())
  );

  let isAdded = false;
  if (existingIndex >= 0) {
    list.splice(existingIndex, 1);
    toast(`Removed "${title}" from Watchlist`);
  } else {
    list.unshift({
      title: movie.title,
      poster_url: movie.poster_url || null,
      release_date: movie.release_date || null,
      vote_average: movie.vote_average || null,
      tmdb_id: movie.tmdb_id || null,
      original_language: movie.original_language || null,
      added_at: Date.now(),
    });
    isAdded = true;
    toast(`Added "${title}" to Watchlist`);
  }

  localStorage.setItem(STORAGE_KEYS.watchlist, JSON.stringify(list));
  updateWatchlistBadge();

  // If currently on watchlist view, refresh it
  if (APP.category === "watchlist" && APP.currentView === "home") {
    loadHomeFeed("watchlist");
  }

  return isAdded;
}

function updateWatchlistBadge() {
  const count = getWatchlist().length;
  const headerCountEl = $("header-watchlist-count");
  const pillCountEl = $("pill-watchlist-count");

  if (headerCountEl) headerCountEl.textContent = count;
  if (pillCountEl) pillCountEl.textContent = count;
}

// ── Dark / Light Theme Management ─────────────────────────────────
function initTheme() {
  const savedTheme = localStorage.getItem(STORAGE_KEYS.theme) || "dark";
  applyTheme(savedTheme);

  const toggleBtn = $("theme-toggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      const next = current === "dark" ? "light" : "dark";
      applyTheme(next);
    });
  }
}

function applyTheme(themeName) {
  const isDark = themeName !== "light";
  document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  const toggleBtn = $("theme-toggle");
  if (toggleBtn) {
    toggleBtn.setAttribute("aria-pressed", String(!isDark));
    toggleBtn.title = isDark ? "Switch to light theme" : "Switch to dark theme";
  }
  localStorage.setItem(STORAGE_KEYS.theme, isDark ? "dark" : "light");
}

// ── API Status & Health Check ─────────────────────────────────────
function setStatus(mode) {
  const dotEl = $("api-status-dot");
  const labelEl = $("api-status-label");
  if (!dotEl || !labelEl) return;

  dotEl.className =
    "api-status__dot" +
    (mode === "ok" ? " is-ok" : mode === "down" ? " is-down" : "");

  labelEl.textContent =
    mode === "ok"
      ? "connected"
      : mode === "down"
      ? "offline"
      : "connecting…";
}

async function checkHealth() {
  setStatus("connecting");

  try {
    const healthData = await apiGet("/health");
    setStatus("ok");
    hideBanner();

    if (!healthData.tmdb_configured) {
      showBanner(
        "TMDB_API_KEY not set in .env — posters and live catalogs are running on offline cache.",
        "warning"
      );
    }
    return healthData;
  } catch {
    setStatus("down");
    showBanner(
      `Can't reach backend at <strong>${esc(
        APP.apiBase
      )}</strong>. Run <strong>uvicorn main:app --reload</strong> or update URL via ⚙`,
      "error"
    );
    return null;
  }
}

// ── Settings Popover ──────────────────────────────────────────────
function initSettings() {
  const settingsBtn = $("settings-btn");
  const popover = $("settings-pop");
  const urlInput = $("api-base-input");
  const hintEl = $("settings-hint");
  const saveBtn = $("api-base-save");
  const testBtn = $("api-base-test");

  if (!settingsBtn || !popover) return;
  if (urlInput) urlInput.value = APP.apiBase;

  settingsBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    if (APP.settingsOpen) {
      closeSettings(popover, settingsBtn);
    } else {
      openSettings(popover, settingsBtn, urlInput);
    }
  });

  document.addEventListener("click", (event) => {
    if (
      APP.settingsOpen &&
      !popover.contains(event.target) &&
      event.target !== settingsBtn
    ) {
      closeSettings(popover, settingsBtn);
    }
  });

  saveBtn?.addEventListener("click", () => {
    const cleanedUrl = urlInput?.value.trim() || DEFAULT_API;
    APP.apiBase = cleanedUrl;
    localStorage.setItem(STORAGE_KEYS.api, cleanedUrl);

    if (hintEl) hintEl.textContent = "Saved. Checking connection…";
    checkHealth();
    loadHomeFeed(APP.category);
  });

  testBtn?.addEventListener("click", async () => {
    const cleanedUrl = urlInput?.value.trim() || DEFAULT_API;
    const previousUrl = APP.apiBase;
    APP.apiBase = cleanedUrl;

    if (hintEl) hintEl.textContent = "Testing connection…";
    try {
      await apiGet("/health");
      if (hintEl) hintEl.textContent = "Connected successfully ✓";
    } catch (err) {
      if (hintEl) hintEl.textContent = err.message;
      APP.apiBase = previousUrl;
    }
  });
}

function openSettings(popover, button, inputEl) {
  APP.settingsOpen = true;
  popover.classList.add("is-open");
  button.setAttribute("aria-expanded", "true");
  inputEl?.focus();
}

function closeSettings(popover, button) {
  APP.settingsOpen = false;
  popover.classList.remove("is-open");
  button.setAttribute("aria-expanded", "false");
}

// ── Optimized Image Loading (Eager + Lazy Observer) ───────────────
const _imgObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;

      const img = entry.target;
      const srcUrl = img.dataset.src;
      if (!srcUrl) return;

      _imgObserver.unobserve(img);
      img.src = srcUrl;

      img.onload = () => {
        img.classList.add("is-loaded");
        img.closest(".card__poster")?.classList.add("has-image");
      };

      img.onerror = () => {
        img.closest(".card__poster")?.classList.add("no-image");
      };
    });
  },
  {
    rootMargin: "250px 0px", // Pre-fetch 250px before entering viewport
  }
);

function attachImage(img, srcUrl, isEager = false) {
  if (!srcUrl) {
    img.closest?.(".card__poster")?.classList.add("no-image");
    return;
  }

  if (isEager) {
    img.src = srcUrl;
    img.onload = () => {
      img.classList.add("is-loaded");
      img.closest(".card__poster")?.classList.add("has-image");
    };
    img.onerror = () => {
      img.closest(".card__poster")?.classList.add("no-image");
    };
  } else {
    img.dataset.src = srcUrl;
    _imgObserver.observe(img);
  }
}

// ── Skeleton Loader ───────────────────────────────────────────────
function renderSkeletons(container, count = 12) {
  container.innerHTML = "";
  const skeletonTemplate = $("tpl-card-skeleton");

  for (let i = 0; i < count; i++) {
    container.appendChild(skeletonTemplate.content.cloneNode(true));
  }
}

// ── Poster Card Factory ───────────────────────────────────────────
let _cardCounter = 0;

function buildPosterCard(movie, { small = false, scorePct = null } = {}) {
  const template = $("tpl-poster-card");
  const cardNode = template.content.cloneNode(true);

  const card = cardNode.querySelector(".card");
  const img = cardNode.querySelector(".card__img");
  const posterWrap = cardNode.querySelector(".card__poster");
  const initial = cardNode.querySelector(".card__initial");
  const rating = cardNode.querySelector(".card__rating");
  const titleEl = cardNode.querySelector(".card__title");
  const yearEl = cardNode.querySelector(".card__year");
  const langTag = cardNode.querySelector(".card__lang-tag");
  const bookmarkBtn = cardNode.querySelector(".card__bookmark");

  if (small) {
    card.classList.add("rec-card");
  }

  const movieTitle = movie.title || "Untitled";
  titleEl.textContent = movieTitle;
  yearEl.textContent = formatYear(movie.release_date);

  // Eager load above-fold cards, lazy load below-fold
  _cardCounter++;
  if (movie.poster_url) {
    img.alt = `${movieTitle} poster`;
    attachImage(img, movie.poster_url, _cardCounter <= 8);
  } else {
    posterWrap.classList.add("no-image");
  }

  initial.textContent = movieTitle.trim().charAt(0).toUpperCase();

  // Rating badge
  if (typeof movie.vote_average === "number" && movie.vote_average > 0) {
    rating.textContent = `★ ${movie.vote_average.toFixed(1)}`;
  } else {
    rating.remove();
  }

  // Language tag
  const langCode = movie.original_language;
  if (langTag && langCode && langCode !== "en") {
    langTag.textContent = LANG[langCode] || langCode.toUpperCase();
    langTag.hidden = false;
  }

  // Watchlist toggle button
  const saved = isWatchlisted(movieTitle, movie.tmdb_id);
  if (saved) bookmarkBtn.classList.add("is-saved");

  bookmarkBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    const nowSaved = toggleWatchlist(movie);
    bookmarkBtn.classList.toggle("is-saved", nowSaved);
  });

  // AI Similarity Match Badge (Score Ring)
  if (scorePct !== null && scorePct > 0) {
    const pct = Math.min(100, Math.max(0, Math.round(scorePct)));
    const hue = Math.round(pct * 1.2);

    const scoreBadge = document.createElement("div");
    scoreBadge.className = "score-badge";
    scoreBadge.title = `${pct}% similarity match`;
    scoreBadge.style.setProperty("--h", hue);
    scoreBadge.style.setProperty("--p", pct);
    scoreBadge.textContent = `${pct}%`;
    posterWrap.appendChild(scoreBadge);

    const matchBar = document.createElement("div");
    matchBar.className = "match-bar";
    matchBar.innerHTML = `<div class="match-bar__fill" style="width: ${pct}%"></div>`;
    card.appendChild(matchBar);
  }

  // Card click / Enter key navigation
  const openDetails = () => {
    if (movie.tmdb_id) {
      openDetailById(movie.tmdb_id);
    } else if (movie.title) {
      openDetailByQuery(movie.title);
    }
  };

  card.addEventListener("click", openDetails);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openDetails();
    }
  });

  return card;
}

// ── Carousel Horizontal Scroll Navigation ─────────────────────────
function setupCarouselNav(trackId, prevBtnId, nextBtnId) {
  const track = $(trackId);
  const prevBtn = $(prevBtnId);
  const nextBtn = $(nextBtnId);

  if (!track || !prevBtn || !nextBtn) return;

  const updateButtons = () => {
    const maxScroll = track.scrollWidth - track.clientWidth;
    prevBtn.disabled = track.scrollLeft <= 5;
    nextBtn.disabled = track.scrollLeft >= maxScroll - 5;
  };

  prevBtn.addEventListener("click", () => {
    track.scrollBy({ left: -420, behavior: "smooth" });
  });

  nextBtn.addEventListener("click", () => {
    track.scrollBy({ left: 420, behavior: "smooth" });
  });

  track.addEventListener("scroll", debounce(updateButtons, 60));
  window.addEventListener("resize", debounce(updateButtons, 100));
  setTimeout(updateButtons, 300);
}

// ── Home View & Categories Navigation ─────────────────────────────
function initCategories() {
  const categoriesNav = $("categories");
  if (!categoriesNav) return;

  categoriesNav.addEventListener("click", (event) => {
    const pillBtn = event.target.closest(".pill");
    if (!pillBtn) return;

    categoriesNav
      .querySelectorAll(".pill")
      .forEach((p) => p.classList.remove("is-active"));
    pillBtn.classList.add("is-active");

    APP.category = pillBtn.dataset.category;
    const [title, sub] = CAT_LABELS[APP.category] || ["Movies", ""];

    if ($("feed-title")) $("feed-title").textContent = title;
    if ($("feed-sub")) $("feed-sub").textContent = sub;

    loadHomeFeed(APP.category);
  });

  // Header watchlist quick link
  $("header-watchlist-btn")?.addEventListener("click", () => {
    showHomeView();
    const watchlistPill = categoriesNav.querySelector(
      '.pill[data-category="watchlist"]'
    );
    if (watchlistPill) {
      watchlistPill.click();
      watchlistPill.scrollIntoView({ behavior: "smooth", inline: "center" });
    }
  });
}

async function loadHomeFeed(category = APP.category) {
  const feedEl = $("feed");
  if (!feedEl) return;

  feedEl.setAttribute("aria-busy", "true");
  _cardCounter = 0;
  const emptyEl = $("feed-empty");
  if (emptyEl) emptyEl.hidden = true;

  // Handle Watchlist Category
  if (category === "watchlist") {
    const watchlist = getWatchlist();
    feedEl.innerHTML = "";

    if (!watchlist.length) {
      if (emptyEl) {
        emptyEl.hidden = false;
        emptyEl.querySelector(".empty-state__title").textContent =
          "Your Watchlist is empty";
        emptyEl.querySelector(".empty-state__sub").textContent =
          "Click the heart icon on any movie card to save it here.";
      }
    } else {
      const fragment = document.createDocumentFragment();
      watchlist.forEach((movie) => {
        fragment.appendChild(buildPosterCard(movie));
      });
      feedEl.appendChild(fragment);
    }
    feedEl.setAttribute("aria-busy", "false");
    return;
  }

  renderSkeletons(feedEl, 12);

  try {
    const movies = await apiGet(
      `/home?category=${encodeURIComponent(category)}&limit=24`
    );
    feedEl.innerHTML = "";
    _cardCounter = 0;

    if (!movies || movies.length === 0) {
      if (emptyEl) {
        emptyEl.hidden = false;
        emptyEl.querySelector(".empty-state__title").textContent =
          "No movies found";
        emptyEl.querySelector(".empty-state__sub").textContent =
          "Try searching for another movie title.";
      }
    } else {
      const fragment = document.createDocumentFragment();
      movies.forEach((movie) => {
        fragment.appendChild(buildPosterCard(movie));
      });
      feedEl.appendChild(fragment);
    }
  } catch (err) {
    feedEl.innerHTML = "";
    if (emptyEl) {
      emptyEl.hidden = false;
      emptyEl.querySelector(".empty-state__title").textContent =
        "Could not load feed";
      emptyEl.querySelector(".empty-state__sub").textContent = err.message;
    }
    if (err.status !== 503) {
      toast(err.message, true);
    }
  } finally {
    feedEl.setAttribute("aria-busy", "false");
  }
}

function buildLangNav(container, languages, onSelect) {
  if (!container) return;
  container.innerHTML = "";

  const allBtn = document.createElement("button");
  allBtn.className = "pill is-active";
  allBtn.textContent = "All";
  allBtn.addEventListener("click", () => {
    container
      .querySelectorAll(".pill")
      .forEach((p) => p.classList.remove("is-active"));
    allBtn.classList.add("is-active");
    onSelect(null);
  });
  container.appendChild(allBtn);

  Object.entries(languages).forEach(([code, label]) => {
    const langBtn = document.createElement("button");
    langBtn.className = "pill";
    langBtn.textContent = label;
    langBtn.dataset.code = code;

    langBtn.addEventListener("click", () => {
      container
        .querySelectorAll(".pill")
        .forEach((p) => p.classList.remove("is-active"));
      langBtn.classList.add("is-active");
      onSelect(code);
    });
    container.appendChild(langBtn);
  });
}

async function loadRegionalFeed(feedEl, endpoint) {
  if (!feedEl) return;

  _cardCounter = 0;
  renderSkeletons(feedEl, 8);

  try {
    const data = await apiGet(endpoint);
    const movies = data.movies || data || [];

    feedEl.innerHTML = "";
    _cardCounter = 0;

    if (!movies.length) {
      feedEl.innerHTML = `<p class="empty-state" style="padding: 24px">No films found.</p>`;
      return;
    }

    const fragment = document.createDocumentFragment();
    movies.forEach((movie) => {
      fragment.appendChild(buildPosterCard(movie));
    });
    feedEl.appendChild(fragment);
  } catch (err) {
    feedEl.innerHTML = `<p class="empty-state" style="padding: 24px">${esc(
      err.message
    )}</p>`;
  }
}

async function initDiscoverySections() {
  setupCarouselNav("indian-feed", "indian-feed-prev", "indian-feed-next");
  setupCarouselNav("world-feed", "world-feed-prev", "world-feed-next");

  try {
    const meta = await apiGet("/discover/metadata");

    if ($("indian-section") && meta.indian_languages) {
      buildLangNav($("indian-lang-nav"), meta.indian_languages, (lang) => {
        loadRegionalFeed(
          $("indian-feed"),
          `/discover/indian?limit=24${lang ? `&language=${lang}` : ""}`
        );
      });
      loadRegionalFeed($("indian-feed"), "/discover/indian?limit=24");
    }

    if ($("world-section") && meta.world_languages) {
      buildLangNav($("world-lang-nav"), meta.world_languages, (lang) => {
        loadRegionalFeed(
          $("world-feed"),
          `/discover/world?limit=24${lang ? `&language=${lang}` : ""}`
        );
      });
      loadRegionalFeed($("world-feed"), "/discover/world?limit=24");
    }
  } catch {
    if ($("indian-section")) $("indian-section").hidden = true;
    if ($("world-section")) $("world-section").hidden = true;
  }
}

// ── SPA View Transitions (Home <-> Details) ───────────────────────
function showHomeView() {
  APP.currentView = "home";

  const homeView = $("view-home");
  const detailView = $("view-detail");

  detailView.classList.add("is-hidden");
  homeView.classList.remove("is-hidden");

  document.title = "CineMatch — AI-Powered Movie Recommendations";
  window.scrollTo({ top: 0, behavior: "smooth" });

  APP.lastFocus?.focus();
}

function showDetailView() {
  APP.currentView = "detail";
  APP.lastFocus = document.activeElement;

  const homeView = $("view-home");
  const detailView = $("view-detail");

  homeView.classList.add("is-hidden");
  detailView.classList.remove("is-hidden");

  window.scrollTo({ top: 0, behavior: "instant" });
}

// ── Detail View Rendering ─────────────────────────────────────────
function showDetailLoading() {
  $("detail-view-content").innerHTML = `
    <div class="detail-loading">
      <div class="spinner"></div>
      <p>Consulting recommendation engine &amp; live catalogs…</p>
    </div>`;
  showDetailView();
}

function showDetailError(errorMessage) {
  $("detail-view-content").innerHTML = `
    <div class="detail-loading">
      <p style="color: var(--text-muted); margin-bottom: 16px; font-size: 0.95rem">${esc(
        errorMessage
      )}</p>
      <button class="btn btn--primary" id="detail-err-back">← Back to Discover</button>
    </div>`;
  $("detail-err-back")?.addEventListener("click", showHomeView);
}

async function openDetailById(tmdbId) {
  showDetailLoading();
  try {
    const data = await apiGet(
      `/recommend?tmdb_id=${encodeURIComponent(
        tmdbId
      )}&local_top_n=20&external_top_n=20&genre_limit=20`
    );

    if (data.status === "not_found") {
      showDetailError(`Movie details not found.`);
      return;
    }

    if (data.warnings?.length) {
      warnBanner(data.warnings);
    } else {
      hideBanner();
    }

    renderDetailView(data, data.movie?.title || "");
  } catch (err) {
    showHomeView();
    toast(err.message, true);
  }
}

async function openDetailByQuery(query) {
  showDetailLoading();
  try {
    const data = await apiGet(
      `/recommend?query=${encodeURIComponent(
        query
      )}&local_top_n=20&external_top_n=20&genre_limit=20`
    );

    if (data.status === "not_found") {
      showDetailError(`"${query}" was not found in dataset or live catalog.`);
      return;
    }

    if (data.warnings?.length) {
      warnBanner(data.warnings);
    } else {
      hideBanner();
    }

    renderDetailView(data, query);
  } catch (err) {
    showHomeView();
    toast(err.message, true);
  }
}

function renderDetailView(data, query) {
  const movie = data.movie || {};
  const recs = data.recommendations || {};
  const localRecs = recs.local_similarity || [];
  const externalRecs = recs.external_similarity || [];
  const genreRecs = recs.genre_recommendations || [];
  const genres = movie.genres_list || [];

  document.title = `${movie.title || query} — CineMatch`;

  const genreChipsHtml = genres
    .map((g) => `<span class="genre-chip">${esc(g.name || g)}</span>`)
    .join("");

  const sourceBadge =
    movie.source === "local_dataset"
      ? `<span class="source-badge source-badge--local">📚 In Library (45k)</span>`
      : `<span class="source-badge source-badge--tmdb">🌐 Live TMDB</span>`;

  const isSavedInWatchlist = isWatchlisted(movie.title, movie.tmdb_id);

  $("detail-view-content").innerHTML = `
    <!-- Hero Header with Ambient Backdrop & Integrated Controls -->
    <div class="page-hero" id="dv-hero">
      <div class="page-hero__bg" id="dv-hero-bg"></div>
      <button class="detail-back" id="dv-back" type="button" aria-label="Back to discover">
        ← Back to Discover
      </button>

      <div class="page-hero__content">
        <div class="page-hero__poster" id="dv-poster">
          <div class="page-hero__poster-ph">🎬</div>
        </div>

        <div class="page-hero__meta">
          <h1 class="page-hero__title">${esc(movie.title || "")}</h1>
          ${
            movie.tagline
              ? `<p class="page-hero__tagline">“${esc(movie.tagline)}”</p>`
              : ""
          }

          <div class="page-hero__subrow">
            ${
              movie.release_date
                ? `<span>${movie.release_date.slice(0, 4)}</span>`
                : ""
            }
            ${
              movie.vote_average
                ? `<span class="vote-lg">★ ${Number(
                    movie.vote_average
                  ).toFixed(1)}</span>`
                : ""
            }
            ${movie.runtime ? `<span>${movie.runtime} min</span>` : ""}
            ${
              movie.original_language && movie.original_language !== "en"
                ? `<span>${(
                    LANG[movie.original_language] || movie.original_language
                  ).toUpperCase()}</span>`
                : ""
            }
            ${sourceBadge}
          </div>

          <div class="genre-chips">${genreChipsHtml}</div>

          <!-- Quick Action Buttons -->
          <div class="page-hero__actions">
            <button class="hero-action-btn hero-action-btn--trailer" id="dv-watch-trailer-btn" type="button">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <polygon points="5,3 19,12 5,21"/>
              </svg>
              <span>Watch Trailer</span>
            </button>

            <button
              class="hero-action-btn hero-action-btn--watchlist ${
                isSavedInWatchlist ? "is-saved" : ""
              }"
              id="dv-watchlist-toggle-btn"
              type="button"
            >
              <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
              </svg>
              <span id="dv-watchlist-btn-text">${
                isSavedInWatchlist ? "In Watchlist" : "Add to Watchlist"
              }</span>
            </button>
          </div>

        </div>
      </div>
    </div>

    <!-- Main Detail Grid -->
    <div class="detail-body">
      <div class="detail-main">

        ${
          movie.overview
            ? `<div class="detail-card">
                 <h2 class="detail-card__title">Storyline</h2>
                 <div class="detail-card__overview">${esc(movie.overview)}</div>
               </div>`
            : ""
        }

        <!-- Trailers Section -->
        <div class="detail-card" id="dv-trailer-card">
          <h2 class="detail-card__title">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="var(--accent)">
              <polygon points="5,3 19,12 5,21"/>
            </svg>
            Official Trailers &amp; Clips
          </h2>
          <div id="dv-trailer-list"></div>
        </div>

        <!-- Cast Carousel -->
        <div class="detail-card" id="dv-cast-card" hidden>
          <div class="section-head" style="margin-bottom: 8px">
            <h2 class="detail-card__title" style="margin-bottom: 0">Featured Cast</h2>
          </div>
          <div class="carousel-container">
            <button class="carousel-nav-btn carousel-nav-btn--prev" id="dv-cast-prev" aria-label="Scroll left" type="button">‹</button>
            <div class="carousel-track cast-scroll" id="dv-cast-list"></div>
            <button class="carousel-nav-btn carousel-nav-btn--next" id="dv-cast-next" aria-label="Scroll right" type="button">›</button>
          </div>
        </div>

        <!-- Local Content-Based Recommendations -->
        <div class="detail-card">
          <div class="section-head" style="margin-bottom: 8px">
            <div>
              <h2 class="detail-card__title" style="margin-bottom: 2px">
                Similar in Our Library
              </h2>
              <p style="font-size: 0.78rem; color: var(--text-muted)">TF-IDF Cosine Similarity from 45k-movie corpus</p>
            </div>
            <span class="section-tag section-tag--local">45k Model</span>
          </div>
          <div class="carousel-container">
            <button class="carousel-nav-btn carousel-nav-btn--prev" id="dv-rec-local-prev" aria-label="Scroll left" type="button">‹</button>
            <div class="carousel-track rec-row" id="dv-rec-local"></div>
            <button class="carousel-nav-btn carousel-nav-btn--next" id="dv-rec-local-next" aria-label="Scroll right" type="button">›</button>
          </div>
        </div>

        <!-- External ML-Matched Recommendations -->
        <div class="detail-card">
          <div class="section-head" style="margin-bottom: 8px">
            <div>
              <h2 class="detail-card__title" style="margin-bottom: 2px">
                ML-Matched Across TMDB
              </h2>
              <p style="font-size: 0.78rem; color: var(--text-muted)">External candidate pool re-ranked by recommendation engine</p>
            </div>
            <span class="section-tag section-tag--external">TMDB Pool</span>
          </div>
          <div class="carousel-container">
            <button class="carousel-nav-btn carousel-nav-btn--prev" id="dv-rec-external-prev" aria-label="Scroll left" type="button">‹</button>
            <div class="carousel-track rec-row" id="dv-rec-external"></div>
            <button class="carousel-nav-btn carousel-nav-btn--next" id="dv-rec-external-next" aria-label="Scroll right" type="button">›</button>
          </div>
        </div>

        <!-- Genre-Based Recommendations -->
        <div class="detail-card">
          <div class="section-head" style="margin-bottom: 8px">
            <div>
              <h2 class="detail-card__title" id="dv-genre-title" style="margin-bottom: 2px">
                ${
                  genres[0]
                    ? `Because you enjoy ${esc(genres[0].name || genres[0])}`
                    : "You might also like"
                }
              </h2>
              <p style="font-size: 0.78rem; color: var(--text-muted)">Genre affinity discovery</p>
            </div>
            <span class="section-tag section-tag--genre">Genre</span>
          </div>
          <div class="carousel-container">
            <button class="carousel-nav-btn carousel-nav-btn--prev" id="dv-rec-genre-prev" aria-label="Scroll left" type="button">‹</button>
            <div class="carousel-track rec-row" id="dv-rec-genre"></div>
            <button class="carousel-nav-btn carousel-nav-btn--next" id="dv-rec-genre-next" aria-label="Scroll right" type="button">›</button>
          </div>
        </div>

      </div>

      <!-- Detail Sidebar / Facts -->
      <aside class="detail-aside">
        <div class="detail-card">
          <h2 class="detail-card__title">Film Facts</h2>
          <div class="meta-grid" id="dv-facts"></div>
        </div>
        <div class="detail-card" id="dv-crew-card" hidden>
          <h2 class="detail-card__title">Key Crew</h2>
          <div id="dv-crew-list" class="meta-grid"></div>
        </div>
        <div class="detail-card" id="dv-companies-card" hidden>
          <h2 class="detail-card__title">Production</h2>
          <p id="dv-companies" style="font-size: 0.92rem; color: var(--text-secondary); line-height: 1.6"></p>
        </div>
      </aside>
    </div>
  `;

  // Ambient backdrop hero background
  const heroBg = $("dv-hero-bg");
  if (heroBg) {
    if (movie.backdrop_url) {
      heroBg.style.backgroundImage = `url('${movie.backdrop_url}')`;
    } else if (movie.poster_url) {
      heroBg.style.backgroundImage = `url('${movie.poster_url}')`;
    }
  }

  // Poster image (eagerly loaded above fold)
  const posterContainer = $("dv-poster");
  if (movie.poster_url) {
    const posterImg = document.createElement("img");
    posterImg.alt = `${movie.title} poster`;
    posterImg.style.width = "100%";
    posterImg.style.height = "100%";
    posterImg.style.objectFit = "cover";
    posterImg.src = movie.poster_url;
    posterContainer.innerHTML = "";
    posterContainer.appendChild(posterImg);
  }

  // Back button handler
  $("dv-back")?.addEventListener("click", showHomeView);

  // Watchlist toggle in detail view
  const detailWatchlistBtn = $("dv-watchlist-toggle-btn");
  detailWatchlistBtn?.addEventListener("click", () => {
    const isNowSaved = toggleWatchlist(movie);
    detailWatchlistBtn.classList.toggle("is-saved", isNowSaved);
    const label = $("dv-watchlist-btn-text");
    if (label) label.textContent = isNowSaved ? "In Watchlist" : "Add to Watchlist";
  });

  // Facts sidebar population
  const factsContainer = $("dv-facts");
  const makeFactRow = (label, val) =>
    val
      ? `<div><p class="meta-item__label">${label}</p><p class="meta-item__value">${esc(
          String(val)
        )}</p></div>`
      : "";

  factsContainer.innerHTML =
    [
      makeFactRow("Release Date", movie.release_date),
      makeFactRow("Runtime", movie.runtime ? `${movie.runtime} min` : null),
      makeFactRow(
        "Language",
        movie.original_language
          ? (LANG[movie.original_language] || "") +
              " / " +
              movie.original_language.toUpperCase()
          : null
      ),
      makeFactRow("Rating", movie.vote_average ? `★ ${Number(movie.vote_average).toFixed(1)}` : null),
      makeFactRow("TMDB ID", movie.tmdb_id),
      makeFactRow("Status", movie.status),
      makeFactRow("IMDB", movie.imdb_id),
    ].join("") ||
    `<p style="color: var(--text-muted); font-size: 0.88rem">No facts available.</p>`;

  // Production companies
  const companies = movie.production_companies || [];
  if (companies.length > 0) {
    $("dv-companies-card").hidden = false;
    $("dv-companies").textContent = companies
      .map((c) => c.name || c)
      .join(", ");
  }

  // Populate recommendation rows
  fillRecRow("dv-rec-local", localRecs, true);
  fillRecRow("dv-rec-external", externalRecs, true);
  fillRecRow("dv-rec-genre", genreRecs, false);

  // Setup carousel navigation arrows for all recommendation rows
  setupCarouselNav("dv-rec-local", "dv-rec-local-prev", "dv-rec-local-next");
  setupCarouselNav("dv-rec-external", "dv-rec-external-prev", "dv-rec-external-next");
  setupCarouselNav("dv-rec-genre", "dv-rec-genre-prev", "dv-rec-genre-next");


  // Always fetch trailers for ANY movie (present in database or TMDB API)
  loadTrailers(movie.title || query, movie.tmdb_id);

  // Quick action trailer scroll/trigger
  $("dv-watch-trailer-btn")?.addEventListener("click", () => {
    const firstTrailerBtn = $("dv-trailer-list")?.querySelector(".trailer-btn");
    if (firstTrailerBtn) {
      firstTrailerBtn.click();
    } else {
      $("dv-trailer-card")?.scrollIntoView({ behavior: "smooth" });
    }
  });

  // Fetch cast if tmdb_id is present
  if (movie.tmdb_id) {
    loadCast(movie.tmdb_id);
  }
}

// ── Recommendation Helpers ────────────────────────────────────────
function buildRecCard(rec) {
  _cardCounter = 99;
  return buildPosterCard(
    {
      title: rec.title || "Untitled",
      poster_url: rec.poster_url || null,
      release_date: rec.release_date || null,
      vote_average: rec.vote_average || null,
      tmdb_id: rec.tmdb_id || null,
      original_language: rec.original_language || null,
    },
    {
      small: true,
      scorePct: rec.score_pct ?? null,
    }
  );
}

function fillRecRow(rowId, recs, showScore = false) {
  const rowEl = $(rowId);
  if (!rowEl) return;

  if (!recs || recs.length === 0) {
    rowEl.innerHTML = `<p class="rec-empty">No similar titles found.</p>`;
    return;
  }

  _cardCounter = 99;
  recs.forEach((rec) => {
    rowEl.appendChild(
      buildPosterCard(
        {
          title: rec.title,
          poster_url: rec.poster_url || null,
          release_date: rec.release_date || null,
          vote_average: rec.vote_average || null,
          tmdb_id: rec.tmdb_id || null,
          original_language: rec.original_language || null,
        },
        {
          small: true,
          scorePct: showScore ? rec.score_pct : null,
        }
      )
    );
  });
}

function fillRecGrid(gridId, recs) {
  const gridEl = $(gridId);
  if (!gridEl) return;

  if (!recs || recs.length === 0) {
    gridEl.innerHTML = `<p class="rec-empty">No genre recommendations.</p>`;
    return;
  }

  _cardCounter = 99;
  recs.forEach((movie) => {
    gridEl.appendChild(buildPosterCard(movie, { small: true }));
  });
}

// ── Cast Loader ───────────────────────────────────────────────────
async function loadCast(tmdbId) {
  try {
    const credits = await apiGet(`/movie/id/${tmdbId}/credits`);
    const castMembers = credits.cast || [];
    if (!castMembers.length) return;

    const castCard = $("dv-cast-card");
    const castList = $("dv-cast-list");
    if (!castCard || !castList) return;

    castCard.hidden = false;
    castList.innerHTML = "";

    castMembers.slice(0, 15).forEach((actor) => {
      const cardDiv = document.createElement("div");
      cardDiv.className = "cast-card";
      cardDiv.innerHTML = `
        <div class="cast-card__avatar">
          ${
            actor.profile_url
              ? `<img src="${esc(actor.profile_url)}" alt="${esc(
                  actor.name
                )}" loading="lazy"/>`
              : `<div style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 1.4rem">👤</div>`
          }
        </div>
        <p class="cast-card__name">${esc(actor.name)}</p>
        <p class="cast-card__char">${esc(actor.character || "")}</p>
      `;
      castList.appendChild(cardDiv);
    });

    setupCarouselNav("dv-cast-list", "dv-cast-prev", "dv-cast-next");

    // Crew sidebar (Director & Writers)
    const director = credits.director;
    const writers = credits.writers || [];

    if (director || writers.length > 0) {
      const crewCard = $("dv-crew-card");
      const crewList = $("dv-crew-list");

      if (crewCard && crewList) {
        crewCard.hidden = false;
        let crewHtml = "";
        if (director) {
          crewHtml += `<div><p class="meta-item__label">Director</p><p class="meta-item__value">${esc(
            director
          )}</p></div>`;
        }
        if (writers.length > 0) {
          crewHtml += `<div><p class="meta-item__label">Writers</p><p class="meta-item__value">${esc(
            writers.slice(0, 3).join(", ")
          )}</p></div>`;
        }
        crewList.innerHTML = crewHtml;
      }
    }
  } catch {
    // Graceful fallback
  }
}

// ── Trailer Loader & Modal (3-Tier Guaranteed Availability) ──────
async function loadTrailers(title, tmdbId) {
  const trailerCard = $("dv-trailer-card");
  const trailerList = $("dv-trailer-list");
  if (!trailerCard || !trailerList) return;

  trailerCard.hidden = false;
  trailerList.innerHTML = `<div class="spinner" style="width: 22px; height: 22px; margin: 8px auto"></div>`;

  let trailers = [];

  // 1. Try TMDB videos endpoint if tmdbId is present
  if (tmdbId) {
    try {
      const data = await apiGet(`/movie/id/${tmdbId}/trailer`);
      trailers = data.trailers || [];
    } catch {
      trailers = [];
    }
  }

  // 2. Fallback to general trailer endpoint with title
  if (!trailers.length && title) {
    try {
      const data = await apiGet(
        `/movie/trailer?title=${encodeURIComponent(title)}${
          tmdbId ? `&tmdb_id=${tmdbId}` : ""
        }`
      );
      trailers = data.trailers || [];
    } catch {
      trailers = [];
    }
  }

  // 3. Guaranteed client-side YouTube search player fallback
  if (!trailers.length && title) {
    const encoded = encodeURIComponent(`${title} official trailer`);
    trailers = [
      {
        key: null,
        name: `${title} — Official Trailer`,
        type: "Trailer",
        site: "YouTube",
        embed_url: `https://www.youtube.com/embed?listType=search&list=${encoded}&autoplay=1`,
        watch_url: `https://www.youtube.com/results?search_query=${encoded}`,
        official: true,
      },
    ];
  }

  trailerList.innerHTML = "";

  if (!trailers.length) {
    trailerCard.hidden = true;
    return;
  }

  trailers.forEach((trailer) => {
    const btn = document.createElement("button");
    btn.className = "trailer-btn";
    btn.innerHTML = `
      <span class="trailer-btn__icon">
        <svg viewBox="0 0 24 24" width="13" height="13" fill="white">
          <polygon points="6,3 20,12 6,21"/>
        </svg>
      </span>
      <span style="font-weight: 600; text-align: left">${esc(
        trailer.name || "Watch Trailer"
      )}</span>
      <span style="font-size: 0.7rem; color: var(--text-muted); margin-left: auto; flex-shrink: 0">
        ${trailer.type || "YouTube"}
      </span>
    `;
    btn.addEventListener("click", () => openTrailerModal(trailer));
    trailerList.appendChild(btn);
  });
}

function openTrailerModal(trailer) {
  const modal = document.createElement("div");
  modal.className = "trailer-modal";

  const watchButtonHtml = trailer.watch_url
    ? `<a href="${esc(
        trailer.watch_url
      )}" target="_blank" rel="noopener noreferrer" class="btn btn--primary btn--sm" style="position: absolute; bottom: 18px; right: 24px; z-index: 10">Open in YouTube ↗</a>`
    : "";

  modal.innerHTML = `
    <button class="trailer-modal__close" id="tm-close" aria-label="Close modal">✕</button>
    <iframe
      class="trailer-embed"
      src="${esc(trailer.embed_url)}"
      title="${esc(trailer.name || "Trailer")}"
      allowfullscreen
      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
    ></iframe>
    ${watchButtonHtml}
  `;

  document.body.appendChild(modal);

  modal.querySelector("#tm-close")?.addEventListener("click", () => {
    modal.remove();
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      modal.remove();
    }
  });
}

// ── Search Input & Autocomplete System ────────────────────────────
function initSearch() {
  const searchForm = $("search-form");
  const searchInput = $("search-input");
  const suggestionsEl = $("suggestions");

  if (!searchForm || !searchInput || !suggestionsEl) return;

  function hideSuggestions() {
    suggestionsEl.hidden = true;
    suggestionsEl.innerHTML = "";
    searchInput.setAttribute("aria-expanded", "false");
  }

  function showSuggestions(items, query) {
    suggestionsEl.innerHTML = "";

    if (!items || items.length === 0) {
      const emptyLi = document.createElement("li");
      emptyLi.className = "suggestion__empty";
      emptyLi.textContent = `No matches found for "${query}"`;
      suggestionsEl.appendChild(emptyLi);
    } else {
      items.forEach((item) => {
        const itemLi = document.createElement("li");
        itemLi.dataset.title = item.title;
        if (item.tmdb_id) {
          itemLi.dataset.tmdbId = item.tmdb_id;
        }
        itemLi.setAttribute("role", "option");

        const infoDiv = document.createElement("div");
        infoDiv.className = "suggestion__info";

        const titleSpan = document.createElement("span");
        titleSpan.className = "suggestion__title";
        titleSpan.textContent = item.title;
        infoDiv.appendChild(titleSpan);

        if (item.year || item.language) {
          const metaSpan = document.createElement("span");
          metaSpan.className = "suggestion__meta";
          const metaParts = [];
          if (item.year) metaParts.push(item.year);
          if (item.language) metaParts.push(LANG[item.language] || item.language.toUpperCase());
          metaSpan.textContent = metaParts.join(" • ");
          infoDiv.appendChild(metaSpan);
        }

        itemLi.appendChild(infoDiv);

        const badge = document.createElement("span");
        if (item.language && item.language !== "en") {
          badge.className = "suggestion__badge suggestion__badge--lang";
          badge.textContent = (LANG[item.language] || item.language).toUpperCase();
        } else if (item.is_local) {
          badge.className = "suggestion__badge";
          badge.textContent = "in library";
        } else {
          badge.className = "suggestion__badge suggestion__badge--tmdb";
          badge.textContent = "TMDB";
        }
        itemLi.appendChild(badge);

        itemLi.addEventListener("click", () => {
          searchInput.value = item.title;
          hideSuggestions();
          if (item.tmdb_id) {
            openDetailById(item.tmdb_id);
          } else {
            openDetailByQuery(item.title);
          }
        });

        suggestionsEl.appendChild(itemLi);
      });
    }

    suggestionsEl.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
  }

  const runAutocomplete = debounce(async (query) => {
    const trimmed = query.trim();
    if (!trimmed) {
      hideSuggestions();
      return;
    }

    try {
      const [localRes, tmdbRes] = await Promise.allSettled([
        apiGet(`/titles/suggest?query=${encodeURIComponent(trimmed)}&limit=5`),
        apiGet(`/tmdb/search?query=${encodeURIComponent(trimmed)}&page=1`),
      ]);

      const suggestionsList = [];
      const seenTitles = new Set();

      // 1. Process TMDB live catalog results (with year & language)
      if (tmdbRes.status === "fulfilled" && tmdbRes.value?.results) {
        const rawResults = tmdbRes.value.results.slice(0, 6);
        rawResults.forEach((m) => {
          const title = m.title || m.name || "";
          if (!title) return;
          const yr = formatYear(m.release_date || m.first_air_date);
          const lang = m.original_language || "";
          seenTitles.add(`${title.toLowerCase()}::${lang.toLowerCase()}::${yr}`);
          suggestionsList.push({
            title: title,
            tmdb_id: m.id,
            year: yr,
            language: lang,
            is_local: false,
          });
        });
      }

      // 2. Process local library titles
      if (localRes.status === "fulfilled" && Array.isArray(localRes.value)) {
        localRes.value.forEach((title) => {
          const key = `${title.toLowerCase()}::::`;
          if (!seenTitles.has(key)) {
            suggestionsList.push({
              title: title,
              tmdb_id: null,
              year: "",
              language: "",
              is_local: true,
            });
          }
        });
      }

      showSuggestions(suggestionsList, trimmed);
    } catch {
      hideSuggestions();
    }
  }, 200);

  searchInput.addEventListener("input", (event) => {
    runAutocomplete(event.target.value);
  });

  searchInput.addEventListener("keydown", (event) => {
    const items = [...suggestionsEl.querySelectorAll("li[data-title]")];
    const currentIndex = items.findIndex((item) =>
      item.classList.contains("is-active")
    );

    if (event.key === "ArrowDown" && items.length > 0) {
      event.preventDefault();
      items.forEach((item) => item.classList.remove("is-active"));
      const nextItem = items[Math.min(currentIndex + 1, items.length - 1)];
      nextItem.classList.add("is-active");
      nextItem.scrollIntoView({ block: "nearest" });
    } else if (event.key === "ArrowUp" && items.length > 0) {
      event.preventDefault();
      items.forEach((item) => item.classList.remove("is-active"));
      const prevItem = items[Math.max(currentIndex - 1, 0)];
      prevItem.classList.add("is-active");
      prevItem.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Escape") {
      hideSuggestions();
    }
  });

  document.addEventListener("click", (event) => {
    if (!searchForm.contains(event.target)) {
      hideSuggestions();
    }
  });

  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const activeItem = suggestionsEl.querySelector("li.is-active[data-title]");
    if (activeItem) {
      hideSuggestions();
      if (activeItem.dataset.tmdbId) {
        openDetailById(activeItem.dataset.tmdbId);
      } else {
        openDetailByQuery(activeItem.dataset.title);
      }
      return;
    }

    const searchQuery = searchInput.value.trim();
    if (!searchQuery) return;

    // Disambiguation check: if multiple visible suggestions share this title with different versions
    const matchingSuggestions = [
      ...suggestionsEl.querySelectorAll("li[data-title]"),
    ].filter(
      (li) =>
        li.dataset.title.toLowerCase() === searchQuery.toLowerCase() &&
        li.dataset.tmdbId
    );

    if (matchingSuggestions.length > 1) {
      toast(
        `Multiple versions found for "${searchQuery}". Please select your preferred movie from the dropdown list.`,
        false
      );
      suggestionsEl.hidden = false;
      return;
    }

    if (matchingSuggestions.length === 1) {
      hideSuggestions();
      openDetailById(matchingSuggestions[0].dataset.tmdbId);
      return;
    }

    hideSuggestions();
    openDetailByQuery(searchQuery);
  });
}

// ── Global Keyboard Shortcuts ─────────────────────────────────────
function initKeyboardShortcuts() {
  document.addEventListener("keydown", (event) => {
    // '/' key focuses search bar
    if (
      event.key === "/" &&
      document.activeElement?.tagName !== "INPUT" &&
      document.activeElement?.tagName !== "TEXTAREA"
    ) {
      event.preventDefault();
      $("search-input")?.focus();
    }

    // 'Escape' key closes modal, popover, or returns to home
    if (event.key === "Escape") {
      const modal = document.querySelector(".trailer-modal");
      if (modal) {
        modal.remove();
        return;
      }

      if (APP.settingsOpen) {
        closeSettings($("settings-pop"), $("settings-btn"));
        return;
      }

      if (APP.currentView === "detail") {
        showHomeView();
      }
    }
  });

  // Brand click returns to Home view
  $("brand-home-link")?.addEventListener("click", (e) => {
    e.preventDefault();
    showHomeView();
  });
}

// ── Application Entry Point ───────────────────────────────────────
async function init() {
  initTheme();
  initSettings();
  initCategories();
  initSearch();
  initKeyboardShortcuts();
  updateWatchlistBadge();
  await checkHealth();
  loadHomeFeed("popular");
  initDiscoverySections();
}

document.addEventListener("DOMContentLoaded", init);
