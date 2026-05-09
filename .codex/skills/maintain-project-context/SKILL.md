---
name: maintain-project-context
description: Maintain the repository README as the primary project knowledge base. Use when project goals, tech stack choices, architecture boundaries, repo conventions, or LLM-agent operating rules are created, changed, clarified, or likely to drift from the codebase.
---

# Maintain Project Context

## Overview

Keep `README.md` current as the compact source of truth for ROP-Bert's project goal, tech stack, and LLM rules. Prefer factual updates that help future agents orient quickly.

## Workflow

1. Read `README.md`, especially `Project Knowledge Base`.
2. Inspect the changed files or user request to identify any project-level context changes.
3. Update `README.md` only when the goal, stack, architecture boundaries, repo conventions, or LLM rules have changed.
4. Keep the knowledge base short: use concise bullets, avoid implementation logs, and remove stale statements.
5. If `CODEX.md` and `README.md` disagree, update them so `README.md` remains the primary source of truth.

## README Contract

Maintain these headings in `README.md`:

- `## Project Knowledge Base`
- `### Goal`
- `### Tech Stack`
- `### LLM Rules`

The knowledge base should answer:

- What is this project trying to become?
- What technologies are currently used or intentionally planned?
- What rules should future LLM agents follow while editing this repo?

## Guardrails

- Do not add speculative roadmap details unless the user explicitly establishes them.
- Do not add package-level convenience imports, facade APIs, or generic abstractions just to make the scaffold look complete.
- Do not store secrets, credentials, private data, or real patient information in context files.
- Do not duplicate detailed design docs in the knowledge base; link to them if they are added later.
