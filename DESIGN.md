# DESIGN.md — ACB v0.3.0 : search / status / prune + MCP stdio

Version cible : 0.3.0 (suit 0.2.0 : init, record, list, inject, export, hooks).
Perimetre : 3 nouvelles commandes CLI, 2 formats de sortie, schema d'interaction MCP stdio.
Pas de code d'implementation dans ce document.

## 1. Principes UX

- 3 commandes, 1 verbe chacune, options memorisables : `--dir`, `--json`, `-n/--limit`.
- Meme contrat partout : stdout = resultat, stderr = humain/diag, exit codes stables.
- JSON = meme information que l'humain, jamais un sous-ensemble.
- Lecture seule par defaut : seul `prune` mute le store, et il demande confirmation.
- Offline-first conserve : aucune commande ne fait de reseau.

## 2. CLI : signatures

Toutes acceptent le flag global `--dir <path>` (defaut : cwd).

### 2.1 `acb search <query>`

Recherche plein-texte sur topic + summary + details + tags, insensible a la casse.

```
acb search <query> [--dir PATH] [-n/--limit N=10] [--tag TAG]... [--agent NAME] [--json]
```

- `<query>` : 1+ mots, OU implicite. Chaine vide ou absente -> exit 2 + usage sur stderr.
- `--tag` repetable : filtre ET sur les tags. `--agent` : filtre exact, insensible a la casse.
- Tri : plus recents d'abord. `--limit` : 1..100, defaut 10, hors borne -> exit 2.

### 2.2 `acb status`

Diagnostic lecture seule du workspace, pour humains et CI.

```
acb status [--dir PATH] [--json]
```

Champs : `version` (package), `workspace` (absolu), `initialized` (bool),
`records` (compte), `store_bytes` (taille `.agent_bridge/` en octets, 0 si non initialisé),
`last_updated` (ISO-8601 UTC ou null), `targets` (["hermes","claude","opencode","codex"]).
Ne cree jamais le store : non initialise -> `initialized: false`, `records: 0`.

### 2.3 `acb prune`

Suppression des entrees anciennes. SEULE commande destructive du lot.

```
acb prune [--dir PATH] [--older-than DAYS] [--keep-last N] [--tag TAG]... [--dry-run] [--yes] [--json]
```

- `--older-than DAYS` (int >= 1) OU `--keep-last N` (int >= 0), exactement un des deux requis.
- `--tag` repetable : restreint la suppression aux records portant TOUS les tags (combine avec le critere d'age/rang).
- Sans `--yes` : mode interactif = demande `Prune <k> record(s)? [y/N]`, defaut Non.
- `--dry-run` : ne supprime rien, liste ce qui serait supprime. Combine avec `--json` pour la CI.
- Non-TTY sans `--yes` ni `--dry-run` -> exit 2 + message "refusing without --yes in non-interactive mode".
- Apres suppression reussie : regenere SHARED_CONTEXT.md (meme invariant que `record`).

## 3. Formats de sortie

### 3.1 Humain (defaut)

- `search` : une ligne resume par resultat `* [agent] topic — summary (id court)`, puis details du premier resultat si `-n 1`-like. Zero resultat -> `No matches for "<query>".` sur stdout, exit 0.
- `status` : bloc cle: valeur aligne, ex. `Records:     12`.
- `prune` : `Pruned 3 record(s), kept 9.` ou `Dry run: would prune 3 record(s).`

### 3.2 JSON (`--json`)

- Toujours un objet racine avec `{"version": "0.3.0", "command": "<nom>", ...}`.
- `search` -> `{"results": [{"id","agent","topic","summary","details","tags","created_at"}], "count": N, "query": "..."}`.
- `status` -> les champs du 2.2 tels quels.
- `prune` -> `{"pruned": K, "kept": M, "dry_run": bool, "ids": [...]}`.
- JSON invalide a ecrire = ne jamais arriver : serialisation via stdlib, `ensure_ascii=False`, une ligne finale `\n`.

## 4. Interaction MCP stdio + UX plugin Claude Code

Transport : stdio JSON-RPC, binaire `acb-mcp` (meme package, zero dependance).
READONLY strict (brief C3) : le serveur expose exactement 2 tools, aucun `prune`
ni ecriture. `prune` reste CLI-only (garde-fou dossier Anthropic).
Le parametre client `dir` est confine sous la racine `--dir` du serveur :
toute valeur hors racine -> erreur `-32602`, sans acces filesystem.

| tool MCP     | mappe vers | params (JSON Schema)                              |
|--------------|------------|---------------------------------------------------|
| `acb_search` | search     | `query: string (req), limit: int 1..100 =10, tag: string[] =[], agent: string?` |
| `acb_status` | status     | `{}` (optionnel `dir: string?`)                   |

- Reponses : `content: [{type: "text", text: "<JSON stringifie du meme payload que --json>"}]`.
- Erreurs : JSON-RPC `error {code: -32602, message}` pour params invalides (meme regles que exit 2) ; `isError: true` + message lisible si store non initialise.
- Test ecriture : tout appel hors `acb_search`/`acb_status` -> `Method not found`, jamais de mutation.

### 4.1 UX plugin Claude Code (2 commandes, zero config manuelle)

```bash
acb hooks claude --install   # ecrit/fusionne .claude/settings.json (SessionStart) + .mcp.json (serveur acb)
echo '{}' | acb hooks run --target claude   # verification locale, exit 0
```

- `settings.json` : hook SessionStart `acb inject --target claude` (contexte auto a chaque session).
- `.mcp.json` : `{"mcpServers": {"acb": {"command": "acb-mcp"}}}` (portee projet, partageable via git).
- Verification : apres install, nouvelle session Claude retrouve un record test via `acb_search` (log/capture = preuve C3).
- Desinstall : suppression manuelle des 2 blocs (documente dans `--help`), jamais de suppression auto.

## 5. Exemples d'entrees / sorties

```
$ acb search "wal mode" --tag db
* [hermes-dev] Database Engine — Adopted SQLite WAL mode (a3f9c1)
  1 result.

$ acb search "wal mode" --json
{"version":"0.3.0","command":"search","query":"wal mode","count":1,"results":[{"id":"a3f9c1","agent":"hermes-dev","topic":"Database Engine","summary":"Adopted SQLite WAL mode","details":"...","tags":["db"],"created_at":"2026-11-10T08:00:00Z"}]}

$ acb status
ACB 0.3.0
Workspace:    /home/sh/demo
Initialized:  yes
Records:      12
Last updated: 2026-11-15T19:47:00Z

$ acb status --json
{"version":"0.3.0","command":"status","workspace":"/home/sh/demo","initialized":true,"records":12,"store_bytes":48210,"last_updated":"2026-11-15T19:47:00Z","targets":["hermes","claude","opencode","codex"]}

$ acb prune --older-than 90 --dry-run
Dry run: would prune 3 record(s).
$ acb prune --older-than 90 --yes
Pruned 3 record(s), kept 9.
```

MCP (Claude Code) :
```
-> {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"acb_search","arguments":{"query":"wal mode","limit":5}}}
<- {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"count\":1,\"results\":[...]}"}]}}
```

## 6. Erreurs et edge cases

| Cas | Comportement |
|-----|--------------|
| Store non initialise (`search`/`prune`) | stderr `ACB not initialized in <dir> (run 'acb init').`, exit 1. `status` -> exit 0 avec `initialized: false`. MCP -> `isError: true`. |
| `--limit 0` / negatif / >100 | exit 2, message `must be between 1 and 100`. MCP -> -32602. |
| `prune` sans `--older-than` ni `--keep-last`, ou les deux | exit 2, message `exactly one of --older-than / --keep-last is required`. |
| `prune` non-TTY sans `--yes`/`--dry-run` | exit 2, refus explicite (pas de suppression silencieuse). |
| `search` zero resultat | exit 0, message humain / `{"count":0,"results":[]}`. |
| `records.jsonl` corrompu (ligne invalide) | ignore la ligne, compteur `skipped` sur stderr (humain) / champ `skipped` (JSON) ; `status` reste exit 0. |
| `--dir` inexistant | exit 1, `no such directory`. Jamais de creation implicite hors `init`. |
| `--json` + erreur | stderr humain + exit != 0, RIEN de partiel sur stdout (stdout vide ou objet `{"error": "..."}` unique — a trancher en implementation, pas les deux). |

Exit codes : 0 ok · 1 erreur runtime (store, FS) · 2 usage/validation.

## 7. Responsive / accessibilite (sortie terminal)

- Largeur : pas de tableau a colonnes fixes ; listes a une entree par ligne, tronquees a 100 chars avec ellipse.
- Pas de couleur obligatoire : si couleur, doublee par un marqueur texte (`*`, `DRY-RUN:`).
- `--json` desactive toute decoration (sortie pipe-safe pour CI et hooks).

## 8. Criteres d'acceptation

1. `acb search --help`, `acb status --help`, `acb prune --help` documentent exactement les flags du §2.
2. Chaque commande produit les sorties du §5 au mot pres (hors IDs/dates).
3. Round-trip : `prune --dry-run --json` puis `prune --yes --json` coherence `pruned`/`kept`.
4. `status --json` parse par `json.load` sans erreur, cles exactes du §3.2.
5. Serveur MCP : les 2 tools listables via `tools/list`, aucun tool d'ecriture expose (test: appel hors search/status -> `Method not found`, store inchange ; `dir` hors racine -> `-32602`).
6. Tous les cas du §6 testes manuellement (humain + JSON + MCP).
7. Aucun appel reseau (test offline : `unshare -n` ou equiv.).
