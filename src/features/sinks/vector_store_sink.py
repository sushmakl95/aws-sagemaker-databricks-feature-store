"""Vector-store sink for embedding features — enables vector/LLM feature serving.

A classic feature store holds scalar + list-valued features keyed by entity_id.
When the feature is a dense embedding, downstream LLM / RAG / similarity-search
consumers also want an ANN index. This sink keeps the primary source of truth
in Feast (online + offline) AND projects the same embedding into an ANN index
(pgvector / OpenSearch k-NN) for semantic-search queries.

Why not replace Feast with a vector DB? Because feature stores already solve:
- Training/serving parity (PIT joins)
- Feature lineage + registry
- Governance (feature owner, PII flag, retention)

A vector DB solves the one extra thing a feature store doesn't: top-K ANN.
We mirror embeddings into it rather than replace Feast.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VectorRecord:
    entity_id: str
    entity_type: str  # e.g. "customer", "product"
    feature_name: str
    vector: list[float]
    metadata: dict


@dataclass
class PgVectorSinkConfig:
    table: str = "entity_embeddings"
    dim: int = 384
    distance: str = "cosine"


def build_pgvector_upsert_sql(config: PgVectorSinkConfig) -> str:
    return (
        f"INSERT INTO {config.table} (entity_id, entity_type, feature_name, embedding, metadata) "
        "VALUES (:entity_id, :entity_type, :feature_name, :embedding, CAST(:metadata AS JSONB)) "
        "ON CONFLICT (entity_id, feature_name) DO UPDATE SET "
        "  embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata;"
    )


def build_opensearch_knn_mapping(dim: int) -> dict:
    """Build OpenSearch k-NN index mapping for entity embeddings."""
    return {
        "settings": {"index": {"knn": True, "knn.algo_param.ef_search": 100}},
        "mappings": {
            "properties": {
                "entity_id": {"type": "keyword"},
                "entity_type": {"type": "keyword"},
                "feature_name": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dim,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "faiss",
                        "parameters": {"m": 16, "ef_construction": 100},
                    },
                },
                "metadata": {"type": "object", "enabled": True},
            }
        },
    }


def record_to_opensearch_bulk_action(record: VectorRecord, index: str) -> list[dict]:
    doc_id = f"{record.entity_type}:{record.entity_id}:{record.feature_name}"
    return [
        {"index": {"_index": index, "_id": doc_id}},
        {
            "entity_id": record.entity_id,
            "entity_type": record.entity_type,
            "feature_name": record.feature_name,
            "embedding": record.vector,
            "metadata": record.metadata,
        },
    ]
