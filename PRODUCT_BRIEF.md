# PRODUCT_BRIEF — ACB v0.3.0

Objectif: 100 installs PyPI + dossier OSS Anthropic accepté au 28 janv 2027.
État de départ: v0.2.0 (record/list/inject, store `.agent_bridge/`, zéro-dépendance, offline).

## 1. Problème & audience

Les devs multi-agents (Hermes, Claude Code, OpenCode, Codex) perdent le contexte à chaque switch: décisions oubliées, tokens gaspillés en re-lecture, pas d'audit trail. ACB existe mais reste inutilisable au quotidien: pas de recherche, pas de nettoyage, pas de statut lisible, pas de garde-fous confiance, pas d'intégration Claude native (MCP).

Audience: d'abord dogfooders Hermes, puis soumissionnaires OSS Claude (dossier Anthropic).

## 2. Outcome utilisateur

En 10 s, un dev retrouve le bon contexte (`acb search`), nettoie sans peur (`acb prune`), vérifie l'état (`acb status`), injecte dans Claude via MCP stdio, et prouve qu'aucun secret ne fuit (`acb audit`).

## 3. Scope v0.3.0 (3 chantiers)

C1 — Usage friction-zéro + dogfood Hermes: `search` (plein-texte local, <200 ms sur 1000 records), `prune` (suppression par âge/tag avec `--dry-run` par défaut), `status` (compte records, taille store, santé). Hook Hermes réel documenté et utilisé en dogfood.

C2 — Audit confiance: `acb audit` détecte PII/secrets courants (clés API, tokens, emails, chemins privés), rapporte sans jamais afficher les valeurs, exit code ≠ 0 si trouvaille. + attestations SLSA/provenance sur la release (pas de promesse non vérifiable).

C3 — Serveur MCP stdio readonly: `acb-mcp` expose `search` + `status` en lecture seule via stdio, testé avec Claude Code réel. Aucune écriture exposée.

## 4. Non-objectifs (explicites)

Réseau/sync, embeddings/recherche sémantique, daemon/background process, écriture via MCP, nouvelle dépendance runtime.

## 5. Parcours clé

`pip install agent-context-bridge` → `acb init` → `acb record "choix archi X"` → `acb search archi` → `acb status` → `acb audit` → `acb prune --dry-run` → config Claude MCP (`acb-mcp`) → contexte injecté dans Claude.

## 6. Critères d'acceptation testables

C1: (a) sur fixture 1000 records, `acb search <mot>` retourne le record attendu en <200 ms mesuré en test; (b) `acb prune --dry-run` liste sans supprimer, `acb prune --apply` supprime et met à jour `records.jsonl` + `SHARED_CONTEXT.md`; (c) `acb status` affiche comptes + taille, exit 0 sur store sain, ≠ 0 sur store corrompu; (d) preuve dogfood: log Hermes montrant usage réel search/prune/status.

C2: (a) `acb audit` sur fixture contenant fausse clé API + email détecte les 2 types sans imprimer les valeurs (valeurs masquées `***`), exit 1; sur fixture saine exit 0; (b) zéro nouvelle dépendance runtime (`pip install agent-context-bridge` n'installe rien d'autre, vérifié en venv vierge); (c) release v0.3.0 avec provenance SLSA vérifiable (attestation présente).

C3: (a) `acb-mcp` démarre en stdio, répond à `search`/`status`, refuse toute écriture (test: appel write → erreur); (b) session Claude Code réelle utilisant le MCP pour retrouver un record enregistré (capture/log); (c) `pip install` compte 100 installs cumulées (stat PyPI) + dossier OSS soumis avant le 28/01/2027.

## 7. Contraintes & hypothèses

Python ≥3.10, stdlib seule (hors dev). 100% offline sauf `pip install`. Fixtures de test avec faux secrets uniquement. Hypothèse: le dossier Anthropic valorise readonly + audit + preuve d'usage; si critères dossier changent, C2/C3 priment sur le compteur d'installs.

## 8. Signal de succès

v0.3.0 taggée, CI verte, `pip install agent-context-bridge==0.3.0` OK en venv vierge, 100 installs PyPI, dossier OSS soumis avec demo + audit + MCP.
