"""Core feature platform types.

These are the shared vocabulary across all backends (SageMaker FS, Databricks
FS, Feast). Any feature pipeline in this platform deals in these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class FeatureValueType(str, Enum):
    """Feature value types -- maps to both SageMaker FS and Feast."""
    STRING = "string"
    INT64 = "int64"
    FLOAT = "float"
    DOUBLE = "double"
    BOOL = "bool"
    BYTES = "bytes"
    STRING_LIST = "string_list"
    INT64_LIST = "int64_list"
    FLOAT_LIST = "float_list"  # for embeddings


class StoreType(str, Enum):
    """Which feature store backend."""
    SAGEMAKER = "sagemaker"
    DATABRICKS = "databricks"
    BOTH = "both"  # dual-write


@dataclass
class Entity:
    """An entity = the thing features are about (user, product, session)."""
    name: str
    join_keys: list[str]
    value_type: FeatureValueType = FeatureValueType.STRING
    description: str = ""


@dataclass
class Feature:
    """A single named feature."""
    name: str
    value_type: FeatureValueType
    description: str = ""


@dataclass
class FeatureView:
    """A logical group of features sharing entity + schema + freshness."""

    name: str
    entities: list[str]  # entity names this FV is keyed by
    features: list[Feature]
    ttl_seconds: int
    """How long after event_time the features remain valid (= freshness)."""
    online: bool = True
    """Whether to materialize to the online store."""
    offline_only: bool = False
    owner: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if self.offline_only and self.online:
            raise ValueError("offline_only is incompatible with online=True")


@dataclass
class FeatureValue:
    """A feature value at a specific point in time."""
    feature_name: str
    entity_id: str
    value: Any
    event_time: datetime
    ingestion_time: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FeatureRecord:
    """A row of features for a single entity at one point in time.

    This is the canonical record format for ingest into both SageMaker FS
    (PutRecord API) and Databricks FS (write_table).
    """
    feature_view: str
    entity_id: str
    event_time: datetime
    features: dict[str, Any]
    """Feature name -> value."""
    ingestion_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_sagemaker_record(self) -> list[dict[str, str]]:
        """Convert to the SageMaker Feature Store PutRecord format."""
        record = [
            {"FeatureName": "entity_id", "ValueAsString": self.entity_id},
            {"FeatureName": "event_time", "ValueAsString": self.event_time.isoformat()},
        ]
        for name, value in self.features.items():
            record.append({
                "FeatureName": name,
                "ValueAsString": str(value) if value is not None else "",
            })
        return record

    def to_dict(self) -> dict[str, Any]:
        """For Databricks Feature Store write_table."""
        return {
            "entity_id": self.entity_id,
            "event_time": self.event_time,
            "ingestion_time": self.ingestion_time,
            **self.features,
        }


@dataclass
class FeatureLookup:
    """A request for online features for one or more entities."""
    feature_view: str
    feature_names: list[str]
    entity_ids: list[str]


@dataclass
class FeatureLookupResult:
    """Result of an online lookup."""
    entity_id: str
    features: dict[str, Any]
    feature_view: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_stale: bool = False
    """True if the underlying record is older than the FV's TTL."""


@dataclass
class TrainingDatasetSpec:
    """Specification for assembling point-in-time correct training data."""
    label_table: str
    """The labels DataFrame source (table name or S3 path)."""
    entity_join_key: str
    """Column name for the entity join key in the label table."""
    event_time_column: str
    """Column name in the label table for the event timestamp."""
    feature_views: list[str]
    """Feature views to include in the join."""
    feature_names: list[str] | None = None
    """Specific features to include. If None, all features from the listed FVs."""
