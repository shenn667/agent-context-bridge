# QA Report — agent-context-bridge v0.3.0

Date: 2026-11-16 · Reviewer: qa (Hermes) · Task: t_e263e9ff · Scope: v0.3.0 (search, status, prune + acb-mcp stdio)

## Verdict: PASS — ship v0.3.0

## 1. Test suite: 73/73 vert (100%)

`~/ai_env/bin/python -m pytest tests/ -q` → `73 passed in 21.73s`. Fichiers couverts:
test_adapters, test_cli, test_core, test_e2e_multiagent, test_hardening,
test_hooks, test_mcp, test_search_status_prune, test_v030_search_status_prune.
Note: le venv local `.venv/` du projet ne contient pas pytest ; la suite passe
via `~/ai_env` (Python 3.12). CI repo: workflows `ci.yml` + `release.yml` présents.

## 2. E2E live CLI (workspace scratch /tmp/acb-qa-e2e, 3 records)

- `init` → OK (`.agent_bridge/` + SHARED_CONTEXT.md créés)
- `record` × 3 (hermes-dev, claude-code, opencode) → OK (23–32 tokens/record)
- `search "SQLite auth"` → 2 résultats, ordre newest-first OK
- `status` / `status --json` → 3 records, 1642 bytes, targets hermes/claude/opencode/codex OK
- `inject --target hermes|claude|opencode|codex` → OK, format natif par agent
- `prune --keep-last 2 --dry-run` → "would prune 1 record" (495ff8), store intact OK

## 3. E2E live serveur MCP acb-mcp (stdio JSON-RPC, session réelle)

- `initialize` → protocolVersion + serverInfo acb-mcp OK
- `tools/list` → 3 outils: acb_search, acb_status, acb_prune OK
- `tools/call acb_status {dir}` → records=3, isError=false OK
- `tools/call acb_search {query:"SQLite auth", limit:5}` → count=2, premier "Auth Flow" OK
- `tools/call acb_prune {keep_last:2}` (dry_run défaut) → pruned=1, kept=2, dry_run=true, store non muté OK
- Outil inconnu → `-32601 Method not found`, jamais de mutation OK

## 4. Benchmark chiffré — réduction de tokens au switch d'agent

Méthode: tokens ≈ chars/4, mesurés réellement (pas estimés). Baseline "naïf" =
ce qu'un agent aveugle relit au switch. ACB = `inject` (borné aux 5 derniers,
`--limit` réglable) ou `search` ciblé.

| Scénario | Chars | ~Tokens |
|---|---|---|
| Baseline A: relecture sources (7 .py, 60 768 chars) | 60 768 | 15 192 |
| Baseline B: relecture docs décision (DESIGN+BRIEF+README) | 18 220 | 4 555 |
| Baseline C: SHARED_CONTEXT.md complet à 30 records | 8 313 | 2 078 |
| ACB inject hermes, 3 records | 370 | 92 |
| ACB inject hermes, 30 records (5 derniers, borné) | 793 | 198 |
| ACB search ciblé (store 30 records, 1 hit) | 1 024 | 256 |

Économies à 30 records (cas réaliste):
- vs relecture sources: (15 192 − 198) / 15 192 = **98,7 %**
- vs relecture docs: (4 555 − 198) / 4 555 = **95,7 %**
- vs contexte complet: (2 078 − 198) / 2 078 = **90,5 %**

Point clé: `inject` est borné (5 entrées par défaut) donc le coût reste
constant quand le store grandit, là où le coût naïf croît linéairement.
`search` ne renvoie que les hits pertinents au lieu de tout le contexte.

## 5. Limitations connues

- Benchmark sur tokenisation approximative (chars/4) ; l'écart réel varie selon le tokenizer.
- pytest dépend de `~/ai_env`, pas du `.venv` projet (pas de pytest installé dedans).
- Workspaces de test en /tmp (acb-qa-e2e, acb-qa-scale), hors repo, aucun résidu dans le projet.

## Repro

cd /home/sh/ai_env/labs/agent-context-bridge && ~/ai_env/bin/python -m pytest tests/ -q
