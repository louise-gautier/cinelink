import os
import random
import asyncio
import pathlib
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w200"
LANG = "fr-FR"

app = FastAPI(title="CinéLien API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pratique pour tester tout en local avec `uvicorn api.index:app --reload`
# -> l'app complète (front + back) est alors dispo sur http://localhost:8000/app/
PUBLIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "public"
if PUBLIC_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")


def _check_key():
    if not TMDB_API_KEY:
        raise HTTPException(
            500,
            "TMDB_API_KEY manquante côté serveur. Configure la variable d'environnement "
            "(voir README.md).",
        )


def poster_url(path: Optional[str]) -> Optional[str]:
    return f"{IMAGE_BASE}{path}" if path else None


async def tmdb_get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    params = {**params, "api_key": TMDB_API_KEY, "language": LANG}
    r = await client.get(f"{TMDB_BASE}{path}", params=params, timeout=15)
    if r.status_code == 401:
        raise HTTPException(500, "Clé TMDB invalide ou manquante.")
    r.raise_for_status()
    return r.json()


@app.get("/api/health")
async def health():
    return {"ok": True, "tmdb_key_configured": bool(TMDB_API_KEY)}


@app.get("/api/search_movie")
async def search_movie(q: str = Query(..., min_length=1)):
    _check_key()
    async with httpx.AsyncClient() as client:
        data = await tmdb_get(client, "/search/movie", {"query": q})
    results = []
    for m in data.get("results", [])[:10]:
        results.append(
            {
                "id": m["id"],
                "title": m.get("title") or m.get("original_title"),
                "year": (m.get("release_date") or "")[:4],
                "poster": poster_url(m.get("poster_path")),
            }
        )
    return {"results": results}


@app.get("/api/movie_cast")
async def movie_cast(id: int):
    _check_key()
    async with httpx.AsyncClient() as client:
        movie, credits = await asyncio.gather(
            tmdb_get(client, f"/movie/{id}", {}),
            tmdb_get(client, f"/movie/{id}/credits", {}),
        )
    cast = []
    for c in credits.get("cast", []):
        cast.append(
            {
                "id": c["id"],
                "name": c.get("name"),
                "character": c.get("character"),
                "photo": poster_url(c.get("profile_path")),
                "order": c.get("order", 999),
            }
        )
    cast.sort(key=lambda x: x["order"])
    return {
        "movie": {
            "id": movie["id"],
            "title": movie.get("title"),
            "year": (movie.get("release_date") or "")[:4],
            "poster": poster_url(movie.get("poster_path")),
        },
        "cast": cast[:24],
    }


@app.get("/api/actor_movies")
async def actor_movies(id: int):
    _check_key()
    async with httpx.AsyncClient() as client:
        person, credits = await asyncio.gather(
            tmdb_get(client, f"/person/{id}", {}),
            tmdb_get(client, f"/person/{id}/movie_credits", {}),
        )
    movies = []
    seen = set()
    cast_credits = sorted(
        credits.get("cast", []), key=lambda m: m.get("popularity", 0), reverse=True
    )
    for m in cast_credits:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        movies.append(
            {
                "id": m["id"],
                "title": m.get("title") or m.get("original_title"),
                "year": (m.get("release_date") or "")[:4],
                "poster": poster_url(m.get("poster_path")),
            }
        )
    return {
        "actor": {
            "id": person["id"],
            "name": person.get("name"),
            "photo": poster_url(person.get("profile_path")),
        },
        "movies": movies[:30],
    }


POPULAR_POOL_PAGES = 6
MIN_VOTE_COUNT = 800


@app.get("/api/new_game")
async def new_game():
    _check_key()
    async with httpx.AsyncClient() as client:
        pages = await asyncio.gather(
            *[
                tmdb_get(client, "/movie/top_rated", {"page": p})
                for p in range(1, POPULAR_POOL_PAGES + 1)
            ]
        )
    pool = []
    for page in pages:
        for m in page.get("results", []):
            if m.get("vote_count", 0) >= MIN_VOTE_COUNT:
                pool.append(m)
    if len(pool) < 2:
        raise HTTPException(502, "Impossible de récupérer un pool de films depuis TMDB.")
    a, b = random.sample(pool, 2)

    def fmt(m):
        return {
            "id": m["id"],
            "title": m.get("title") or m.get("original_title"),
            "year": (m.get("release_date") or "")[:4],
            "poster": poster_url(m.get("poster_path")),
        }

    return {"movie_a": fmt(a), "movie_b": fmt(b)}


class PathStep(BaseModel):
    type: str  # "movie" ou "actor"
    id: int


class ValidatePathBody(BaseModel):
    steps: List[PathStep]


@app.post("/api/validate_path")
async def validate_path(body: ValidatePathBody):
    """Validation optionnelle côté serveur (anti-triche), pas utilisée par le
    front actuel puisque celui-ci ne propose déjà que des coups valides."""
    _check_key()
    steps = body.steps
    if len(steps) < 3 or len(steps) % 2 == 0:
        raise HTTPException(
            400,
            "Chemin mal formé : il doit alterner film / acteur / film / ... "
            "et commencer et finir par un film.",
        )
    for i, s in enumerate(steps):
        expected = "movie" if i % 2 == 0 else "actor"
        if s.type != expected:
            raise HTTPException(400, f"Étape {i} devrait être de type '{expected}'.")

    errors = []
    async with httpx.AsyncClient() as client:
        cast_cache: Dict[int, set] = {}

        async def get_cast_ids(movie_id: int) -> set:
            if movie_id not in cast_cache:
                data = await tmdb_get(client, f"/movie/{movie_id}/credits", {})
                cast_cache[movie_id] = {c["id"] for c in data.get("cast", [])}
            return cast_cache[movie_id]

        for i in range(1, len(steps), 2):
            actor_id = steps[i].id
            movie_before = steps[i - 1].id
            movie_after = steps[i + 1].id
            cast_before, cast_after = await asyncio.gather(
                get_cast_ids(movie_before), get_cast_ids(movie_after)
            )
            if actor_id not in cast_before:
                errors.append(f"L'acteur {actor_id} n'apparaît pas au casting du film {movie_before}.")
            if actor_id not in cast_after:
                errors.append(f"L'acteur {actor_id} n'apparaît pas au casting du film {movie_after}.")

    valid = len(errors) == 0
    hops = (len(steps) - 1) // 2
    return {"valid": valid, "hops": hops, "errors": errors}


# ---------------------------------------------------------------------------
# Recherche du chemin le plus court : BFS bidirectionnel sur le graphe
# film <-> acteur, interrogé à la volée sur TMDB (avec cache mémoire local
# à la requête + parallélisation des appels).
#
# NB : pour rester dans les limites de temps d'une fonction serverless, on
# borne volontairement le facteur de branchement (top N acteurs par film,
# top N films par acteur) et le nombre d'appels API. Le résultat est donc
# un TRÈS BON chemin, mais pas mathématiquement garanti optimal à 100% dans
# tous les cas extrêmes.
# ---------------------------------------------------------------------------

TOP_CAST = 8
TOP_MOVIES_PER_ACTOR = 8
MAX_ROUNDS = 6  # nombre total d'expansions (3 de chaque côté environ)
MAX_CALLS = 500


def K(kind: str, _id: int) -> str:
    return f"{kind}:{_id}"


@app.get("/api/shortest_path")
async def shortest_path(start: int, end: int):
    _check_key()
    if start == end:
        return {"found": True, "path": [], "hops": 0}

    call_count = {"n": 0}
    # id -> {"title"/"name": str, "poster"/"photo": Optional[str]}
    movie_titles: Dict[int, dict] = {}
    actor_names: Dict[int, dict] = {}

    async with httpx.AsyncClient() as client:
        movie_cast_cache: Dict[int, List[int]] = {}
        actor_movies_cache: Dict[int, List[int]] = {}

        async def cast_of(movie_id: int) -> List[int]:
            if movie_id in movie_cast_cache:
                return movie_cast_cache[movie_id]
            call_count["n"] += 1
            data = await tmdb_get(client, f"/movie/{movie_id}/credits", {})
            cast = sorted(data.get("cast", []), key=lambda c: c.get("order", 999))[:TOP_CAST]
            for c in cast:
                actor_names.setdefault(
                    c["id"],
                    {"name": c.get("name"), "photo": poster_url(c.get("profile_path"))},
                )
            result = [c["id"] for c in cast]
            movie_cast_cache[movie_id] = result
            return result

        async def movies_of(actor_id: int) -> List[int]:
            if actor_id in actor_movies_cache:
                return actor_movies_cache[actor_id]
            call_count["n"] += 1
            data = await tmdb_get(client, f"/person/{actor_id}/movie_credits", {})
            films = sorted(
                data.get("cast", []), key=lambda m: m.get("popularity", 0), reverse=True
            )[:TOP_MOVIES_PER_ACTOR]
            for f in films:
                movie_titles.setdefault(
                    f["id"],
                    {
                        "title": f.get("title") or f.get("original_title"),
                        "poster": poster_url(f.get("poster_path")),
                    },
                )
            result = [f["id"] for f in films]
            actor_movies_cache[actor_id] = result
            return result

        async def expand(frontier: set, visited: Dict[str, Optional[str]], current_type: str):
            ids = [int(k.split(":", 1)[1]) for k in frontier]
            if current_type == "movie":
                results = await asyncio.gather(*[cast_of(i) for i in ids])
                next_type, prefix = "actor", "actor"
            else:
                results = await asyncio.gather(*[movies_of(i) for i in ids])
                next_type, prefix = "movie", "movie"

            new_frontier = set()
            for parent_id, neighbors in zip(ids, results):
                parent_k = K(current_type, parent_id)
                for n in neighbors:
                    k = K(prefix, n)
                    if k not in visited:
                        visited[k] = parent_k
                        new_frontier.add(k)
            return new_frontier, next_type

        start_k, end_k = K("movie", start), K("movie", end)
        visited_fwd: Dict[str, Optional[str]] = {start_k: None}
        visited_bwd: Dict[str, Optional[str]] = {end_k: None}
        frontier_fwd, type_fwd = {start_k}, "movie"
        frontier_bwd, type_bwd = {end_k}, "movie"

        meet = None
        for _ in range(MAX_ROUNDS):
            if call_count["n"] > MAX_CALLS:
                break
            if not frontier_fwd and not frontier_bwd:
                break
            if frontier_fwd and (len(frontier_fwd) <= len(frontier_bwd) or not frontier_bwd):
                frontier_fwd, type_fwd = await expand(frontier_fwd, visited_fwd, type_fwd)
            elif frontier_bwd:
                frontier_bwd, type_bwd = await expand(frontier_bwd, visited_bwd, type_bwd)
            common = set(visited_fwd) & set(visited_bwd)
            if common:
                meet = next(iter(common))
                break

        if not meet:
            return {"found": False, "calls": call_count["n"]}

        def chain_from(visited, node):
            chain = [node]
            k = visited[node]
            while k is not None:
                chain.append(k)
                k = visited[k]
            chain.reverse()
            return chain

        fwd_chain = chain_from(visited_fwd, meet)
        bwd_chain = chain_from(visited_bwd, meet)
        full_keys = fwd_chain + list(reversed(bwd_chain))[1:]

        need_movie_ids = {
            int(k.split(":", 1)[1])
            for k in full_keys
            if k.startswith("movie:") and movie_titles.get(int(k.split(":", 1)[1])) is None
        }
        need_actor_ids = {
            int(k.split(":", 1)[1])
            for k in full_keys
            if k.startswith("actor:") and int(k.split(":", 1)[1]) not in actor_names
        }

        async def fetch_movie_title(mid):
            data = await tmdb_get(client, f"/movie/{mid}", {})
            movie_titles[mid] = {
                "title": data.get("title"),
                "poster": poster_url(data.get("poster_path")),
            }

        async def fetch_actor_name(aid):
            data = await tmdb_get(client, f"/person/{aid}", {})
            actor_names[aid] = {
                "name": data.get("name"),
                "photo": poster_url(data.get("profile_path")),
            }

        await asyncio.gather(
            *[fetch_movie_title(m) for m in need_movie_ids],
            *[fetch_actor_name(a) for a in need_actor_ids],
        )

        path = []
        for k in full_keys:
            kind, raw_id = k.split(":", 1)
            _id = int(raw_id)
            if kind == "movie":
                info = movie_titles.get(_id) or {}
                path.append(
                    {
                        "type": "movie",
                        "id": _id,
                        "label": info.get("title") or f"Film {_id}",
                        "image": info.get("poster"),
                    }
                )
            else:
                info = actor_names.get(_id) or {}
                path.append(
                    {
                        "type": "actor",
                        "id": _id,
                        "label": info.get("name") or f"Acteur {_id}",
                        "image": info.get("photo"),
                    }
                )

        hops = sum(1 for p in path if p["type"] == "actor")
        return {"found": True, "path": path, "hops": hops, "calls": call_count["n"]}
