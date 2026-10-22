# Version log

Change record for the **governed files**: the docs and the contracts. Every change to one of them
gets an entry here, in the same commit. A `pre-commit` hook enforces it.

Why: three people work with separate Claude Code sessions that cannot see each other. This file is
how a session finds out that a design or contract moved since it last looked.

**Doc set version: `v0.1.0`**
**Design status:** HLD draft · Match Simulation LLD approved

---

## Governed files

| File | Why it's governed |
|---|---|
| `README.md` | Team plan: scope, lanes, schedule |
| `CLAUDE.md` | The hub every session loads |
| `COMPETITION.md` | Rules, judging, prizes |
| `docs/design/*.md` | Designs others build against |
| `contracts/*` | Shared schemas (event and frame, cue, MCP tools) |

## Version types

- **MAJOR:** contract change, or architecture change after a design is approved
- **MINOR:** new doc, new requirement, scope change
- **PATCH:** clarification that changes nothing anyone is building against

## Enforcement

Enable once per clone: `git config core.hooksPath .githooks`. Emergency bypass:
`git commit --no-verify`, then log it in the next commit.

---

## Log

## v0.1.0 · 2026-10-21 · Prachit
**Files:** README.md, CLAUDE.md, COMPETITION.md, docs/design/hld.md, docs/design/lld-match-simulation.md
**Type:** MINOR
- Repo created. Team plan, hub, competition summary, high-level design (draft) and the Match
  Simulation low-level design (approved v1.0) with its architecture diagram.
- **Action required:** enable the hook (`git config core.hooksPath .githooks`) and read
  CLAUDE.md before your first session.
