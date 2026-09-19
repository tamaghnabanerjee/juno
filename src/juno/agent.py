"""Approach B: the Juno agent.

A LangGraph loop where the LLM picks tools rather than following a fixed path:

    question -> agent LLM -> count_sql (juno.counting) and/or find_examples (juno.retrieval)
             -> check every number against the SQL result (one retry) -> answer + cited IDs

Wrapped as an MLflow ResponsesAgent so it can be registered in Unity Catalog and deployed to Model
Serving. Built in step 7.
"""

from __future__ import annotations

MAX_RETRIES = 1


def build_agent():
    """Return the compiled LangGraph agent."""
    raise NotImplementedError("step 7: build the graph, tools, check node and retry edge")
