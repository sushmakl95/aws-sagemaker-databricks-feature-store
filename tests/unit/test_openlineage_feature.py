from __future__ import annotations

from features.lineage.openlineage import FeatureLineageConfig, build_run_event


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("OPENLINEAGE_URL", raising=False)
    monkeypatch.delenv("OPENLINEAGE_NAMESPACE", raising=False)
    monkeypatch.delenv("OPENLINEAGE_API_KEY", raising=False)
    cfg = FeatureLineageConfig.from_env()
    assert cfg.namespace == "feature-platform"
    assert cfg.api_key is None


def test_run_event_shape():
    evt = build_run_event(
        job_name="customer_embeddings_batch",
        run_id="run-123",
        inputs=["raw.events"],
        outputs=["features.customer.embedding_v1"],
    )
    assert evt["job"]["name"] == "customer_embeddings_batch"
    assert evt["run"]["runId"] == "run-123"
    assert evt["inputs"][0]["name"] == "raw.events"
    assert evt["outputs"][0]["name"] == "features.customer.embedding_v1"
    assert evt["eventType"] == "COMPLETE"
