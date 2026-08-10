"""Environment targeting for publish (UX_CHANGES audit CH-2, Iter 2).

Two hardcoded environments, ``dev`` and ``prod`` (audit Q6). Everything is
identical between them except:
  * OpenSearch indices — same cluster, ``-dev`` / ``-prod`` suffix (audit Q5).
  * git branch        — ``dev`` / ``prod`` (``main`` is the working definition).
  * target database   — separate connection per env (see ``db_targets`` /
    ask-sql-executor's resolver).

The OpenSearch index resolver is the Knowledge Graph package's canonical
``env_index`` (the KG package owns every ASK index name). This module re-exports
it + adds the git-branch promotion chain so the publish service has one place
to ask "where does env X live".
"""

from __future__ import annotations

from ask_knowledge_graph.infrastructure.env_index import (
    ALL_ENVIRONMENTS,
    Environment,
    env_index,
    is_valid_env,
    normalize_env,
)

# Re-export the canonical OpenSearch resolver under an admin-api-local name.
opensearch_index_for = env_index

# The git branch that mirrors each environment's OpenSearch state.
WORKING_BRANCH = "main"


def branch_for(env: str) -> str:
    """The git branch that mirrors ``env``'s published state (== the env name)."""
    norm = normalize_env(env)
    if norm is None:
        raise ValueError(f"branch_for requires a concrete environment, got {env!r}.")
    return norm


def source_branch_for(env: str) -> str:
    """The branch a publish promotes FROM (audit §3.2 promotion chain).

    dev  ← main  (cut the working definition)
    prod ← dev   (promote the dev version; never bypasses dev)
    """
    norm = normalize_env(env)
    if norm == "dev":
        return WORKING_BRANCH
    if norm == "prod":
        return "dev"
    raise ValueError(f"source_branch_for requires dev/prod, got {env!r}.")


__all__ = [
    "ALL_ENVIRONMENTS",
    "Environment",
    "WORKING_BRANCH",
    "branch_for",
    "is_valid_env",
    "normalize_env",
    "opensearch_index_for",
    "source_branch_for",
]
