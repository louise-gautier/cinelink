# 🎬 CinéLien

Un jeu qui consiste à relier deux films à travers une chaîne d'acteurs
(façon "six degrees of Kevin Bacon"), avec un mode "trouve le chemin le
plus court".

## Structure du projet

```
cine-lien/
├── api/
│   └── index.py        # Backend FastAPI (une seule fonction serverless)
├── public/
│   ├── index.html       # Page du jeu
│   ├── style.css
│   └── app.js
├── requirements.txt
├── vercel.json
├── .env.example
└── README.md
```

## 1. Obtenir une clé API TMDB (gratuit, 5 minutes)

1. Crée un compte sur https://www.themoviedb.org/signup
2. Une fois connecté, va dans **Paramètres du compte** (l'icône en haut à
   droite) → **API** (dans le menu de gauche).
3. Clique sur **Créer** / **Demander une clé API**, choisis le type
   **Développeur**, remplis le petit formulaire (tu peux mettre "usage
   personnel / projet perso" comme description).
4. Une fois validé, tu obtiens une section **Clés API (v3 auth)** →
   copie la valeur **API Key**. C'est cette chaîne qu'on utilise (pas
   besoin du "Jeton d'accès en lecture" v4, plus long).

## 2. Tester en local

```bash
cd cine-lien
python -m venv .venv
source .venv/bin/activate          # ou .venv\Scripts\activate sous Windows
pip install -r requirements.txt uvicorn

export TMDB_API_KEY="ta_cle_ici"   # sous Windows : set TMDB_API_KEY=ta_cle_ici

uvicorn api.index:app --reload --port 8000
```

Puis ouvre **http://localhost:8000/app/** dans ton navigateur (le
`/app/` sert les fichiers de `public/` directement via FastAPI, pratique
pour tester sans configuration supplémentaire).

Tu peux aussi vérifier que la clé est bien prise en compte via :
http://localhost:8000/api/health

## 3. Déployer sur Vercel

### Option A — via l'interface Vercel (le plus simple)

1. Mets ce dossier dans un dépôt GitHub (ou GitLab/Bitbucket).
2. Sur https://vercel.com, clique **Add New → Project**, importe ton
   dépôt.
3. Vercel détecte automatiquement `requirements.txt` → il déploiera
   `api/index.py` comme fonction Python, et servira `public/` comme site
   statique. Tu n'as rien à changer dans les paramètres de build.
4. Avant de cliquer sur "Deploy", ouvre **Environment Variables** et
   ajoute :
   - `TMDB_API_KEY` = ta clé TMDB
5. Clique **Deploy**. Au bout d'une minute, ton jeu est en ligne 🎉

### Option B — via la CLI Vercel

```bash
npm i -g vercel
cd cine-lien
vercel login
vercel env add TMDB_API_KEY     # colle ta clé quand demandé
vercel --prod
```

## Comment fonctionne le jeu

- Au clic sur **Nouvelle partie**, le serveur pioche deux films connus
  (assez populaires/notés sur TMDB pour avoir un casting riche) : un
  film de départ et un film d'arrivée.
- Le joueur clique sur un acteur du casting du film courant, puis sur un
  film où cet acteur a joué, et ainsi de suite jusqu'à atteindre le film
  d'arrivée.
- Comme chaque liste proposée vient directement du vrai casting /de la
  vraie filmographie TMDB, **toute chaîne construite dans le jeu est
  automatiquement valide** — pas besoin de vérification supplémentaire.
- Le score affiché est le nombre d'acteurs utilisés (nombre d'"étapes").
- Une fois la partie gagnée, le bouton **Voir le meilleur chemin
  possible** déclenche un calcul serveur (BFS bidirectionnel sur le
  graphe films/acteurs) pour comparer avec un chemin optimal ou
  quasi-optimal.

## Limites connues / pistes d'amélioration

- **`/api/shortest_path`** interroge TMDB en direct et est donc borné en
  profondeur et en nombre d'appels (`TOP_CAST`, `TOP_MOVIES_PER_ACTOR`,
  `MAX_CALLS` dans `api/index.py`) pour rester dans les limites de temps
  d'une fonction serverless (30 s configurées dans `vercel.json`, le
  plan Hobby peut plafonner plus bas). Pour des films très obscurs, il
  peut ne pas trouver de chemin ou renvoyer un chemin non strictement
  optimal — c'est un compromis performance/exactitude assumé.
- Pas de cache partagé entre requêtes (chaque appel interroge TMDB à
  nouveau). Pour améliorer les perfs et réduire les appels API, on
  pourrait brancher **Vercel KV** (Redis) ou une petite base (Postgres,
  SQLite via Turso) pour mettre en cache casting/filmographies.
- Idées de suite : mode "défi du jour" (deux films fixés par une seed
  basée sur la date), niveaux de difficulté (films plus ou moins connus),
  classement des meilleurs scores, mode multijoueur/duel.

## Attribution

Ce produit utilise l'API TMDB mais n'est ni approuvé ni certifié par
TMDB (mention obligatoire de leurs conditions d'utilisation).
