# Audit Sécurité — agent-context-bridge v0.3.0

Date : 2026-11-16. Auditeur : security (Hermes). Périmètre : `src/agent_context_bridge/` (core, cli, mcp, hooks, adapters, utils), tag v0.3.0.
Méthode : relecture code + probes d'exécution (stores temporaires, faux secrets uniquement).
État suite : `pytest tests/ -q` → **70 passed, 3 failed, tous 3 environnementaux** (binaire `acb` installé = 0.2.0 vs source 0.3.0 : `test_version_coherent…`, `test_search_json_structure`, `test_prune_json_roundtrip_coherence` — assertions `payload["version"] == "0.3.0"`). Non liés à la sécurité, mais la CI release doit tester le build v0.3.0, sinon les garde-fous ne sont pas validés. Note packaging : le `.venv` local n'expose pas le entry-point `acb-mcp` (install 0.2.0 antérieure au module `mcp.py`).

## Verdict

2 findings High (bloquants pour release), 2 Medium, 1 Low. Recommandation : ne pas tagger/releaser v0.3.0 en l'état ; corriger H1+H2 ou accepter formellement le risque (fondateur).

## H1 — Le serveur MCP expose une suppression destructive, contrairement au design readonly

DESIGN.md §4 : "READONLY strict — le serveur expose exactement 2 tools, aucun `prune` ni écriture. `prune` reste CLI-only."
Réalité (`src/agent_context_bridge/mcp.py`) : 3 tools exposés, dont `acb_prune` avec `dry_run` défaut true mais `dry_run=false` accepté et exécuté. Le test `test_mcp_tools_list_exposes_search_status_prune` fige même cette déviation.
Preuve (probe) : `tools/call acb_prune {"keep_last":0,"dry_run":false}` → `{"pruned":1,"kept":0,"dry_run":false}`, `records.jsonl` passe de 1 ligne à 0. N'importe quel client MCP (Claude) peut donc vider le store, sans confirmation interactive (garde-fou CLI contourné).
De plus, le paramètre `dir` accepte tout chemin local (`acb_status {"dir":"/etc"}` répond avec le diagnostic du store) : lecture/suppression hors workspace, sans sandbox.
Impact : perte de données pilotable par le modèle/outil connecté.
Remédiation (au choix, dans l'ordre de préférence) : (a) retirer `acb_prune` de `_tool_defs`/`handle_message` et revenir à 2 tools readonly ; (b) à défaut, forcer `dry_run=true` côté serveur (ignorer la valeur client) ; (c) restreindre `dir` au workspace du serveur (refuser `--dir`/`dir` client ou allowlist sous `default_dir`), à défaut documenter explicitement le risque. Mettre à jour DESIGN.md ou le code pour qu'ils concordent, et corriger le test.
Owner : dev. Re-test : `printf ...dry_run:false... | python -m agent_context_bridge.mcp` doit répondre `Method not found` (option a) ou `dry_run:true` avec store inchangé ; `pytest tests/test_mcp.py -q`.

## H2 — Aucune détection secrets/PII alors que le brief promet `acb audit`

PRODUCT_BRIEF C2 promet `acb audit` (détecte clés API, tokens, emails, exit ≠ 0, valeurs masquées). La commande n'existe pas : `acb audit` → `invalid choice`, aucun motif `audit|secret|redact` dans `src/`.
Preuve (probe) : record avec `--details` contenant fausse clé API + email stocké en clair dans `records.jsonl`, sans avertissement ; la valeur se propage ensuite dans `SHARED_CONTEXT.md` (vérifié : `grep` trouve le marqueur), `acb export`, `acb search --json`, et donc dans les prompts injectés (`inject`, hooks SessionStart) — soit une exfiltration vers le provider LLM à chaque session.
Atténuant : `inject`/`hooks run` (adapters) ne remontent que topic/summary, pas details — mais `export`/`search --json` exposent tout.
Remédiation : (a) implémenter `acb audit` (patterns stdlib : `sk-`, `ghp_`, `AKIA`, `xox[bap]`, emails, chemins `/home|Users`, clés privées `BEGIN PRIVATE KEY` ; rapport par type/compte/ligne, valeurs jamais imprimées, exit 1 si trouvaille) + test fixture ; (b) avertir à `record` quand le contenu matche (stderr, sans bloquer) ; (c) documenter que `records.jsonl`/`SHARED_CONTEXT.md` sont en clair et exclus du git (déjà dans `.gitignore` — bien). Retirer la promesse C2/SLSA de PRODUCT_BRIEF tant que non livré (fausse assurance).
Owner : dev. Re-test : fixture avec faux secret → `acb audit` exit 1 sans valeur en clair ; fixture saine → exit 0 ; `pytest`.

## M1 — Permissions `.agent_bridge` implicites, dossier lisible par tous

`MemoryStore.initialize` fait `mkdir(parents=True, exist_ok=True)` sans mode → `0700`−umask effectif constaté `755` sur le dossier (probe : `stat` → `755` dir, `600` fichiers — ce `600` n'est qu'un accident de `NamedTemporaryFile`, pas une politique).
Sur machine partagée, tout utilisateur peut lister le store ; les fichiers eux-mêmes héritent de l'umask sans `chmod` explicite, donc fragile.
Remédiation : `os.chmod(bridge_dir, 0o700)` à `initialize` (+ `exist_ok`, try/except OSError), `os.chmod(file, 0o600)` après `atomic_write` des 3 fichiers (records, md, `.claude/settings.json`), ou `os.umask(0o077)` scoped. Ajouter un test `stat` (mode & 0o777 == 0o700/0o600).
Owner : dev. Re-test : init frais → `stat -c %a` = `700` dir, `600` fichiers ; `pytest`.

## M2 — `hooks run` lit stdin sans limite de taille

`cli.py` (`hooks run`) fait `sys.stdin.read()` non borné avant d'ignorer le contenu. Probe : 10 Mo absorbés sans broncher (exit 0). Un payload SessionStart anormalement gros = pic mémoire du hook à chaque session (DoS locale bénigne mais réelle ; le hook s'exécute à chaque SessionStart).
Bon point : le contenu stdin est intégralement ignoré (pas d'injection via hook payload — rien n'est interpolé en shell, `hook_command` est une chaîne fixe `acb inject --target X`), et `install_claude_hook` merge sans `eval`.
Remédiation : caper la lecture (ex. 1 Mo : `sys.stdin.read(1_000_000)` + drain borné), commenter que le payload est intentionnellement ignoré.
Owner : dev. Re-test : payload > cap → exit 0, sortie identique ; `pytest tests/test_hooks.py -q`.

## L1 — Divers durcissement déjà correct, à conserver

Limites `search --limit 1..100` (exit 2), `record` borné (64/200/2000/20000, 20 tags), adapters capés à 1000, `_load_all` tolérant aux lignes corrompues (comptées `skipped`), MCP `parse error -32700 / invalid params -32602` sans fuite de traceback (catch-all → `-32603 Internal error` sans détail), `--dir` inexistant → exit 1 sans création. Bien. Mineur : les messages d'erreur incluent le chemin absolu du workspace (empreinte système dans les logs MCP/CI) — acceptable en local, à masquer si les logs partent en CI publique.

## Détails envérifiés / limites

Probes avec faux secrets uniquement ; la sortie `records.jsonl` du probe initial a été masquée par la plateforme (`sk-liv...7890`) — la conclusion "stockage en clair" repose sur le code (`json.dumps(asdict(rec))` direct, aucune fonction de masquage dans `src/`), pas sur la sortie masquée.
Non testé : SLSA/provenance release (hors code), multi-utilisateurs réels, perf gros stores.

## Re-test global

~/ai_env/bin/python -m pytest tests/ -q  # attendu : tout vert + nouveaux tests audit/perms/MCP

## Addendum — re-vérification runtime 2026-11-16 (run 2)

Probes rejoués contre la source v0.3.0 (`PYTHONPATH=src`, `.venv` Python 3.12, umask 0022) :

- **H1 re-confirmé, avec précision** : `tools/call acb_prune {"keep_last":0,"dry_run":false,"dir":"/tmp/acb-perm-test"}` → `{"pruned":1,"kept":0,"dry_run":false}`, `records.jsonl` 1 ligne → 0. Suppression réelle, sans confirmation. **Trou de test identifié** : `tests/test_mcp.py::test_mcp_prune_is_dryrun_only_store_unchanged` n'exerce que le défaut (`dry_run` omis → true) ; aucun test ne couvre `dry_run:false` explicite — c'est pourquoi le garde-fou supposé n'est pas validé. Re-test fix : ajouter le cas `dry_run:false` (doit refuser ou rester sans effet).
- **H1/bis `dir` re-confirmé** : `acb_search {"query":"x","dir":"/etc"}` accepté et résolu (erreur métier `ACB not initialized in /etc`, pas `-32602`) ; `get_status` fait `rglob("*")+stat()` sur le workspace fourni → oracle existence/taille sur tout le FS local.
- **M1 re-confirmé** : `acb init` frais → dir `755`, fichiers `600` ; `grep -rn "chmod|0o600|0o700|umask|audit|secret|redact|pii" src/` = **0 hit**. Le `600` fichier n'est qu'un accident de `NamedTemporaryFile`, pas une politique ; aucun réparatif sur stores pré-existants.
- **Stores réels scannés propres** : regex secrets durs (`sk-live`, `AKIA…`, `ghp_`, `xox*`, `BEGIN … PRIVATE KEY`) sur `~/.agent_bridge/records.jsonl` et `/tmp/acb-demo/.agent_bridge/records.jsonl` → 0 hit. Le risque H2 reste structurel (aucun garde-fou à l'écriture), pas un incident constaté.
- Fichier test : `/tmp/acb-perm-test/.agent_bridge/` (store jetable du probe, hors repo).
