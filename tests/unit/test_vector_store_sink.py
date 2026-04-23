from __future__ import annotations

from features.sinks.vector_store_sink import (
    PgVectorSinkConfig,
    VectorRecord,
    build_opensearch_knn_mapping,
    build_pgvector_upsert_sql,
    record_to_opensearch_bulk_action,
)


def test_pgvector_upsert_sql_has_conflict_clause():
    sql = build_pgvector_upsert_sql(PgVectorSinkConfig())
    assert "INSERT INTO entity_embeddings" in sql
    assert "ON CONFLICT (entity_id, feature_name) DO UPDATE" in sql


def test_opensearch_mapping_uses_hnsw():
    m = build_opensearch_knn_mapping(dim=768)
    prop = m["mappings"]["properties"]["embedding"]
    assert prop["type"] == "knn_vector"
    assert prop["dimension"] == 768
    assert prop["method"]["name"] == "hnsw"
    assert prop["method"]["space_type"] == "cosinesimil"


def test_bulk_action_shape():
    rec = VectorRecord(
        entity_id="c-1",
        entity_type="customer",
        feature_name="embedding_v1",
        vector=[0.1, 0.2],
        metadata={"tenant": "acme"},
    )
    actions = record_to_opensearch_bulk_action(rec, index="features")
    assert len(actions) == 2
    assert actions[0]["index"]["_id"] == "customer:c-1:embedding_v1"
    assert actions[1]["embedding"] == [0.1, 0.2]
    assert actions[1]["metadata"] == {"tenant": "acme"}
