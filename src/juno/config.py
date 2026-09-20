"""Single source of truth for names Juno uses in the workspace.

Values come from the environment (set by job parameters or the app), with defaults that match
databricks.yml. Import this rather than hardcoding a table name anywhere else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    catalog: str = os.environ.get("JUNO_CATALOG", "juno")
    schema: str = os.environ.get("JUNO_SCHEMA", "restaurant")
    volume: str = os.environ.get("JUNO_VOLUME", "raw")

    vs_endpoint: str = os.environ.get("JUNO_VS_ENDPOINT", "juno-vs")
    tagging_model: str = os.environ.get("JUNO_TAGGING_MODEL", "databricks-gpt-oss-120b")
    agent_model: str = os.environ.get("JUNO_AGENT_MODEL", "databricks-claude-sonnet-5")
    judge_model: str = os.environ.get("JUNO_JUDGE_MODEL", "databricks-claude-opus-5")
    embedding_model: str = os.environ.get("JUNO_EMBEDDING_MODEL", "databricks-gte-large-en")

    @property
    def prefix(self) -> str:
        return f"{self.catalog}.{self.schema}"

    # Tables, in the order the pipeline builds them.
    @property
    def raw_sentences(self) -> str:
        return f"{self.prefix}.raw_sentences"

    @property
    def sentences(self) -> str:
        return f"{self.prefix}.sentences"

    @property
    def human_labels(self) -> str:
        return f"{self.prefix}.human_labels"

    @property
    def review_facts(self) -> str:
        return f"{self.prefix}.review_facts"

    @property
    def eval_questions(self) -> str:
        return f"{self.prefix}.eval_questions"

    @property
    def index(self) -> str:
        return f"{self.prefix}.sentences_index"

    @property
    def volume_path(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/{self.volume}"


CONFIG = Config()
