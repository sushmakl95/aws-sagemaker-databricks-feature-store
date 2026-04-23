"""Similarity-search API on top of the mirrored embedding index.

Enables:
  - "find me top-K similar customers to entity X" (RAG / recommendations)
  - "surface nearest-neighbour product for this query vector" (search)
  - "pull similar support tickets for LLM context" (RAG grounding)

The primary feature store remains source of truth; this serving path just
wraps the ANN index for low-latency nearest-neighbour queries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimilarityHit:
    entity_id: str
    entity_type: str
    score: float
    metadata: dict


def build_opensearch_knn_query(
    vector: list[float],
    *,
    entity_type: str | None = None,
    top_k: int = 10,
    min_score: float | None = None,
) -> dict:
    """Build a k-NN query body for OpenSearch with optional filtering."""
    query: dict = {
        "size": top_k,
        "query": {
            "knn": {
                "embedding": {
                    "vector": vector,
                    "k": top_k,
                }
            }
        },
    }
    if entity_type:
        query["query"] = {
            "bool": {
                "must": [query["query"]],
                "filter": [{"term": {"entity_type": entity_type}}],
            }
        }
    if min_score is not None:
        query["min_score"] = min_score
    return query


def build_pgvector_knn_sql(table: str = "entity_embeddings", distance: str = "cosine") -> str:
    op = {"cosine": "<=>", "l2": "<->", "ip": "<#>"}[distance]
    return (
        "SELECT entity_id, entity_type, feature_name, metadata, "
        f"       (embedding {op} :vector) AS distance "
        f"FROM {table} "
        "WHERE (:entity_type IS NULL OR entity_type = :entity_type) "
        f"ORDER BY embedding {op} :vector ASC "
        "LIMIT :top_k;"
    )
