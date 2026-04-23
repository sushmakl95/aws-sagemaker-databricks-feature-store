from __future__ import annotations

from features.serving.similarity_search import (
    build_opensearch_knn_query,
    build_pgvector_knn_sql,
)


def test_opensearch_knn_basic():
    q = build_opensearch_knn_query([0.1, 0.2, 0.3], top_k=5)
    assert q["size"] == 5
    assert q["query"]["knn"]["embedding"]["k"] == 5
    assert q["query"]["knn"]["embedding"]["vector"] == [0.1, 0.2, 0.3]


def test_opensearch_knn_with_entity_filter():
    q = build_opensearch_knn_query([0.0, 0.0], entity_type="customer")
    # The knn query is nested under bool.must when filtering
    assert "bool" in q["query"]
    assert q["query"]["bool"]["filter"][0]["term"]["entity_type"] == "customer"


def test_opensearch_knn_min_score():
    q = build_opensearch_knn_query([0.0], min_score=0.7)
    assert q["min_score"] == 0.7


def test_pgvector_sql_uses_cosine_by_default():
    sql = build_pgvector_knn_sql()
    assert "embedding <=> :vector" in sql
    assert "ORDER BY embedding <=>" in sql


def test_pgvector_sql_l2():
    sql = build_pgvector_knn_sql(distance="l2")
    assert "embedding <-> :vector" in sql
