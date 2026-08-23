const API = "/api";

const state = {
  movieA: null,
  movieB: null,
  chain: [], // liste de { type: 'movie'|'actor', id, label }
};

const el = (id) => document.getElementById(id);

async function api(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    let detail = `Erreur API (${res.status})`;
    try {
      const err = await res.json();
      detail = err.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function renderMovieCard(container, movie) {
  container.innerHTML = movie
    ? `
      <img src="${movie.poster || ""}" alt="${movie.title}" onerror="this.style.display='none'"/>
      <div class="movie-title">${movie.title}${movie.year ? ` (${movie.year})` : ""}</div>
    `
    : `<div class="placeholder">?</div>`;
}

function renderChain() {
  const chainEl = el("chain");
  chainEl.innerHTML = state.chain
    .map((step, i) => {
      const cls = step.type === "movie" ? "chain-movie" : "chain-actor";
      const sep = i < state.chain.length - 1 ? '<span class="chain-sep">→</span>' : "";
      return `<span class="chain-item ${cls}">${escapeHtml(step.label)}</span>${sep}`;
    })
    .join("");
  const hops = state.chain.filter((s) => s.type === "actor").length;
  el("hop-counter").textContent = `${hops} étape(s)`;
  el("btn-undo").disabled = state.chain.length <= 1;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function startNewGame() {
  el("result").classList.add("hidden");
  el("btn-new-game").disabled = true;
  el("picker-title").textContent = "Chargement d'une nouvelle partie…";
  el("picker-grid").innerHTML = "";
  try {
    const data = await api("/new_game");
    state.movieA = data.movie_a;
    state.movieB = data.movie_b;
    state.chain = [{ type: "movie", id: data.movie_a.id, label: data.movie_a.title }];
    renderMovieCard(el("movie-start"), data.movie_a);
    renderMovieCard(el("movie-end"), data.movie_b);
    renderChain();
    await loadCastStep();
  } catch (e) {
    el("picker-title").textContent = "Erreur : " + e.message;
  } finally {
    el("btn-new-game").disabled = false;
  }
}

async function loadCastStep() {
  const last = state.chain[state.chain.length - 1];
  el("picker-title").textContent = `Choisis un acteur ou une actrice du casting de « ${last.label} »`;
  el("picker-grid").innerHTML = "";
  const data = await api(`/movie_cast?id=${last.id}`);
  const grid = el("picker-grid");
  grid.innerHTML = data.cast
    .map(
      (c) => `
      <button class="pick-card" data-id="${c.id}" data-label="${escapeHtml(c.name)}">
        <img src="${c.photo || ""}" onerror="this.style.display='none'"/>
        <div>${escapeHtml(c.name)}</div>
        <div class="sub">${escapeHtml(c.character || "")}</div>
      </button>`
    )
    .join("");
  grid.querySelectorAll(".pick-card").forEach((btn) =>
    btn.addEventListener("click", () => onPickActor(Number(btn.dataset.id), btn.dataset.label))
  );
}

async function loadMoviesStep() {
  const last = state.chain[state.chain.length - 1];
  el("picker-title").textContent = `Choisis un film où a joué ${last.label}`;
  el("picker-grid").innerHTML = "";
  const data = await api(`/actor_movies?id=${last.id}`);
  const grid = el("picker-grid");
  grid.innerHTML = data.movies
    .map(
      (m) => `
      <button class="pick-card" data-id="${m.id}" data-label="${escapeHtml(m.title)}">
        <img src="${m.poster || ""}" onerror="this.style.display='none'"/>
        <div>${escapeHtml(m.title)}</div>
        <div class="sub">${m.year || ""}</div>
      </button>`
    )
    .join("");
  grid.querySelectorAll(".pick-card").forEach((btn) =>
    btn.addEventListener("click", () => onPickMovie(Number(btn.dataset.id), btn.dataset.label))
  );
}

function onPickActor(id, label) {
  state.chain.push({ type: "actor", id, label });
  renderChain();
  loadCastStep0();
}

function onPickMovie(id, label) {
  state.chain.push({ type: "movie", id, label });
  renderChain();
  if (id === state.movieB.id) {
    onWin();
  } else {
    loadCastStep0();
  }
}

// petit wrapper pour capturer les erreurs des fonctions async appelées sans await
function loadCastStep0() {
  loadMoviesStepOrCast().catch((e) => {
    el("picker-title").textContent = "Erreur : " + e.message;
  });
}

function loadMoviesStepOrCast() {
  const last = state.chain[state.chain.length - 1];
  return last.type === "movie" ? loadCastStep() : loadMoviesStep();
}

function onWin() {
  const hops = state.chain.filter((s) => s.type === "actor").length;
  el("picker-title").textContent = "🎉 Bravo, tu as relié les deux films !";
  el("picker-grid").innerHTML = "";
  el("result").classList.remove("hidden");
  el("result-title").textContent = `Chemin trouvé en ${hops} étape(s) (nombre d'acteurs utilisés).`;
  el("best-path").textContent = "";
}

async function undoLast() {
  if (state.chain.length <= 1) return;
  const last = state.chain[state.chain.length - 1];
  if (last.type === "actor") {
    state.chain.pop();
  } else {
    state.chain.pop(); // le film
    if (state.chain.length > 1) state.chain.pop(); // l'acteur qui y menait
  }
  renderChain();
  try {
    await loadCastStep();
  } catch (e) {
    el("picker-title").textContent = "Erreur : " + e.message;
  }
}

async function showBestPath() {
  el("btn-best-path").disabled = true;
  el("best-path").textContent = "Calcul en cours… (peut prendre jusqu'à 20-30 secondes)";
  try {
    const data = await api(`/shortest_path?start=${state.movieA.id}&end=${state.movieB.id}`);
    if (!data.found) {
      el("best-path").textContent =
        "Aucun chemin trouvé dans la limite de recherche (essaie avec des films plus connus).";
      return;
    }
    const yourHops = state.chain.filter((s) => s.type === "actor").length;
    const comparison =
      data.hops < yourHops
        ? `Le jeu a trouvé plus court (${data.hops} vs ${yourHops}) !`
        : data.hops === yourHops
        ? "Bravo, ton chemin est déjà optimal (ou aussi court) !"
        : `Ton chemin (${yourHops} étapes) était même meilleur que celui trouvé automatiquement (${data.hops}) !`;
    el("best-path").innerHTML =
      `<strong>${comparison}</strong><br/>` +
      data.path.map((p) => escapeHtml(p.label)).join(" → ");
  } catch (e) {
    el("best-path").textContent = "Erreur lors du calcul : " + e.message;
  } finally {
    el("btn-best-path").disabled = false;
  }
}

el("btn-new-game").addEventListener("click", () => startNewGame());
el("btn-undo").addEventListener("click", () => undoLast());
el("btn-best-path").addEventListener("click", () => showBestPath());
