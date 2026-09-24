# AGENTS.md

## Project skills

Load any skill below with the `skill` tool by name (e.g., `skill find-skills`), or read its `SKILL.md` directly (e.g., `read .agents/skills/find-skills/SKILL.md`). If `.agents/skills/` is empty, run `npx skills-manager install` to populate it (see [skills-manager docs](https://github.com/netbek/skills-manager)).

| Skill | Path | Description |
|-------|------|-------------|
| `clickhouse-best-practices` | `.agents/skills/clickhouse-best-practices` | MUST USE when reviewing ClickHouse schemas, queries, or configurations. Contains 31 rules that MUST be checked before providing recommendations. Always read relevant rule files and cite specific rules in responses. |
| `economist-style` | `.agents/skills/economist-style` | Apply The Economist style guide to written content. Use when editing markdown, HTML, documentation, or any written text that needs professional editing for clarity, precision, and brevity. Detects weasel words, fillers, passive voice, and style issues. |
| `fetching-dbt-docs` | `.agents/skills/fetching-dbt-docs` | Retrieves and searches dbt documentation pages in LLM-friendly markdown format. Use when fetching dbt documentation, looking up dbt features, or answering questions about dbt Cloud, dbt Core, or the dbt Semantic Layer. |
| `find-skills` | `.agents/skills/find-skills` | Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that can...", or express interest in extending capabilities. This skill should be used when the user is looking for functionality that might exist as an installable skill. |
| `using-dbt-for-analytics-engineering` | `.agents/skills/using-dbt-for-analytics-engineering` | Builds and modifies dbt models, writes SQL transformations using ref() and source(), creates tests, and validates results with dbt show. Use when doing any dbt work - building or modifying models, debugging errors, exploring unfamiliar data sources, writing tests, or evaluating impact of changes. |

## PeerDB dependency management

This library provides a Python class `src/dw_lib/peerdb.py` for interacting with the PeerDB REST API. It supports only one version of PeerDB at a time. It does not aim for backward compatibility. A local copy of the PeerDB source code is stored in `vendor/peerdb` for development reference.

Follow these steps when the user asks to upgrade PeerDB.

1. Ask the user to give the current and next version of PeerDB in this format: `vX.YY.Z`

2. Search and replace the current and next version tags in these files:

    - `examples/cli/.env`
    - `examples/cli/peerdb.yaml`
    - `infra/peerdb/.env`
    - `scripts/install-vendor.sh`
    - `src/dw_lib/peerdb.py`
    - `tests/conftest.py`

3. Run `scripts/install-vendor.sh` to checkout the next version of PeerDB `vendor/peerdb`.

4. Search `src/dw_lib/peerdb.py` for comments and docstrings that link to source code at `https://github.com/PeerDB-io/peerdb/blob/<vX.YY.Z>`. Verify that the line numbers are correct after upgrading to the next version of PeerDB. Either check the local copy `vendor/peerdb` or clone the remote repo to a temporary directory.
