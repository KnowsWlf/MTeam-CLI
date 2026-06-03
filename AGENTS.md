# AGENTS.md

This repository was refactored from a single-file script into the layered
`mteam_cli` package. The authoritative guidance for working here lives in
[`CLAUDE.md`](CLAUDE.md) — read it for commands, architecture, the env scheme,
and the critical constraints (e.g. keep-alive must stay browser-login).

Quick orientation:

- Source: `src/mteam_cli/` (`core/ api/ automation/ notify/ scheduler/ cli/`).
- Install: `pip install -e .` then `playwright install chromium`.
- Entry point: `mteam-cli` (= `python -m mteam_cli`).
