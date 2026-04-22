# AWS SageMaker + Databricks Feature Store

> Production-grade feature platform with **SageMaker Feature Store** and **Databricks Feature Store** running side-by-side, unified by **Feast** as the abstraction layer. Streaming features (Kinesis → DynamoDB online + S3 offline), batch features (Spark on EMR/Databricks), training (SageMaker + Databricks ML), real-time serving (SageMaker endpoints + Databricks Model Serving), and continuous drift monitoring (SageMaker Model Monitor + Databricks Lakehouse Monitoring).

[![CI](https://github.com/sushmakl95/aws-sagemaker-databricks-feature-store/actions/workflows/ci.yml/badge.svg)](https://github.com/sushmakl95/aws-sagemaker-databricks-feature-store/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![PySpark 3.5](https://img.shields.io/badge/pyspark-3.5-E25A1C.svg)](https://spark.apache.org/)
[![SageMaker](https://img.shields.io/badge/aws-sagemaker_feature_store-FF9900.svg)](https://aws.amazon.com/sagemaker/feature-store/)
[![Databricks ML](https://img.shields.io/badge/databricks-feature_store_+_ml-FF3621.svg)](https://www.databricks.com/)
[![Feast](https://img.shields.io/badge/feast-0.36-2E7D32.svg)](https://feast.dev/)
[![MLflow](https://img.shields.io/badge/mlflow-2.12-0194E2.svg)](https://mlflow.org/)
[![Terraform](https://img.shields.io/badge/terraform-17_modules-7B42BC.svg)](https://www.terraform.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

---

## Author

**Sushma K L** — Senior Data Engineer
📍 Bengaluru, India
💼 [LinkedIn](https://www.linkedin.com/in/sushmakl1995/) • 🐙 [GitHub](https://github.com/sushmakl95) • ✉️ sushmakl95@gmail.com

---

## What this platform does

You're building ML models that need:

1. **Consistent features online + offline** — same logic for training and inference, no skew
2. **Streaming + batch features** — recent behavior (last 5 min) and historical (last 90 days), unified
3. **Sub-10ms online lookup** for real-time inference
4. **Drift detection** — alert when input distribution shifts from training data
5. **Cross-platform portability** — train on SageMaker, serve on Databricks, or vice versa

This repo delivers all five with two interchangeable backends (SageMaker Feature Store + Databricks Feature Store), one unified API (Feast), and full observability.

## Comparison at a glance

| Capability | SageMaker Feature Store | Databricks Feature Store | Feast (unified) |
|---|---|---|---|
| Online store | DynamoDB-backed (managed) | Online Tables on Delta + Lakehouse | Configurable: DynamoDB, Redis, etc. |
| Offline store | S3 + Glue catalog | Delta Lake + Unity Catalog | Configurable: S3, BigQuery, etc. |
| Point-in-time joins | ✅ via Athena | ✅ native | ✅ via configured offline store |
| Streaming ingest | ✅ via PutRecord API | ✅ via DLT + Online Tables | ✅ via push API |
| Batch ingest | ✅ via SageMaker Processing | ✅ via Spark MERGE | ✅ via materialize |
| Training integration | ✅ SageMaker Training | ✅ Databricks ML | ✅ via to_dataframe |
| Serving integration | ✅ SageMaker Endpoint | ✅ Model Serving | Manual lookup |
| Cost (baseline) | ~$300/month | ~$200/month (already on Databricks) | $0 (just abstraction) |

We expose all three so teams pick what fits.

---

## System Architecture

### High-level architecture

```mermaid
flowchart TB
    subgraph Sources["🟢 Sources"]
        Kinesis[("Kinesis<br/>app events")]
        S3Raw[("S3 raw zone<br/>(daily batch)")]
        Postgres[("Postgres<br/>OLTP via CDC")]
    end

    subgraph Pipelines["🟡 Feature Pipelines"]
        StreamLambda["Streaming Lambda<br/>(per-event features)"]
        BatchSpark["Spark / Databricks Job<br/>(daily aggregations)"]
        EmbedJob["Embedding Job<br/>(periodic, GPU)"]
    end

    subgraph FeastAPI["🟠 Feast Unified API"]
        FeastSDK["Feast SDK<br/>get_online_features()<br/>get_historical_features()"]
        FeastRepo["feast_repo/<br/>FeatureViews + Entities"]
    end

    subgraph SMFS["🔴 SageMaker Feature Store Track"]
        SMFSOnline[("FeatureStore Online<br/>(DynamoDB)")]
        SMFSOffline[("FeatureStore Offline<br/>(S3 + Glue)")]
    end

    subgraph DBFS["🔵 Databricks Feature Store Track"]
        DBFSOnline[("Online Tables<br/>(serverless)")]
        DBFSDelta[("Feature Delta tables<br/>(Unity Catalog)")]
    end

    subgraph Training["🟣 Training"]
        SMTrain["SageMaker Training Job<br/>(XGBoost / sklearn / pytorch)"]
        DBTrain["Databricks ML<br/>+ MLflow"]
        Registry["MLflow Model Registry<br/>(unified)"]
    end

    subgraph Serving["🟢 Real-Time Serving"]
        SMEndpoint["SageMaker Endpoint<br/>P99 < 50ms"]
        DBServing["Databricks Model Serving<br/>P99 < 80ms"]
    end

    subgraph Monitoring["📊 Drift Monitoring"]
        SMM["SageMaker Model Monitor<br/>(data + bias drift)"]
        DBLM["Databricks Lakehouse Monitoring<br/>(data + ML drift)"]
        AlertSink["SNS / Slack alerts"]
    end

    Kinesis --> StreamLambda
    S3Raw --> BatchSpark
    Postgres -.CDC.-> BatchSpark

    StreamLambda --> SMFSOnline
    StreamLambda --> SMFSOffline
    BatchSpark --> SMFSOffline
    BatchSpark --> DBFSDelta
    EmbedJob --> SMFSOffline
    EmbedJob --> DBFSDelta
    SMFSOffline -.materialize.-> SMFSOnline
    DBFSDelta -.materialize.-> DBFSOnline

    FeastRepo --> FeastSDK
    FeastSDK -.lookup.-> SMFSOnline
    FeastSDK -.lookup.-> DBFSOnline

    SMFSOffline --> SMTrain
    DBFSDelta --> DBTrain
    SMTrain --> Registry
    DBTrain --> Registry

    Registry --> SMEndpoint
    Registry --> DBServing
    SMFSOnline --> SMEndpoint
    DBFSOnline --> DBServing

    SMEndpoint -.predictions.-> SMM
    DBServing -.predictions.-> DBLM
    SMM --> AlertSink
    DBLM --> AlertSink

    classDef src fill:#22C55E,stroke:#166534,color:#fff
    classDef pipe fill:#fbbf24
    classDef feast fill:#FF9900,color:#000
    classDef smfs fill:#EF4444,color:#fff
    classDef dbfs fill:#3b82f6,color:#fff
    classDef train fill:#a855f7,color:#fff
    classDef serve fill:#10b981,color:#fff
    classDef obs fill:#0ea5e9,color:#fff
    class Kinesis,S3Raw,Postgres src
    class StreamLambda,BatchSpark,EmbedJob pipe
    class FeastSDK,FeastRepo feast
    class SMFSOnline,SMFSOffline smfs
    class DBFSOnline,DBFSDelta dbfs
    class SMTrain,DBTrain,Registry train
    class SMEndpoint,DBServing serve
    class SMM,DBLM,AlertSink obs
```

### Streaming feature ingest sequence

```mermaid
sequenceDiagram
    autonumber
    participant App as Application
    participant Kinesis as Kinesis Stream
    participant Lambda as Feature Lambda
    participant SMOnline as SageMaker FS<br/>Online (DDB)
    participant SMOffline as SageMaker FS<br/>Offline (S3)
    participant DBOnline as Databricks<br/>Online Table

    App->>Kinesis: put_record(user_event)

    Note over Kinesis: Triggers Lambda via<br/>event source mapping

    Kinesis->>Lambda: batch of records

    loop For each record
        Lambda->>Lambda: compute features<br/>(rolling window, ratios)
        Lambda->>SMOnline: PutRecord(feature_group, record)
        Note over SMOnline: < 10ms latency
        SMOnline-->>Lambda: ack

        Lambda->>SMOffline: async write to S3 buffer
        Note over SMOffline: Buffered, flushed<br/>every 15 min

        Lambda->>DBOnline: parallel write<br/>(if dual-track enabled)
    end

    Lambda-->>Kinesis: checkpoint offsets
```

### Point-in-time correct training data

```mermaid
flowchart LR
    subgraph Request["Training Data Request"]
        Labels["Label DataFrame<br/>(entity_id, event_ts, label)"]
    end

    subgraph Feast["Feast PIT Engine"]
        Plan["Build query plan<br/>per feature view"]
    end

    subgraph Storage["Offline Store"]
        FV1[("user_aggregates<br/>(timestamp-versioned)")]
        FV2[("product_features<br/>(timestamp-versioned)")]
        FV3[("user_embeddings<br/>(timestamp-versioned)")]
    end

    subgraph Output["Output"]
        Result["Joined DataFrame:<br/>(entity_id, event_ts, label,<br/> feat1_at_ts, feat2_at_ts, ...)"]
    end

    Labels --> Plan
    Plan -->|"AS OF entity_id<br/>WHERE feature_ts <= event_ts<br/>AND feature_ts > event_ts - ttl"| FV1
    Plan -->|same| FV2
    Plan -->|same| FV3
    FV1 --> Result
    FV2 --> Result
    FV3 --> Result

    Note1["Why PIT matters:<br/>training on future-looking<br/>features causes data leakage"]
    Result -.- Note1
```

### Real-time inference path

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client App
    participant API as API Gateway
    participant SMEndpoint as SageMaker Endpoint
    participant FeastSDK as Feast SDK<br/>(in container)
    participant DDB as DynamoDB<br/>(SMFS Online)
    participant Model as Model<br/>(in container)

    Client->>API: POST /predict<br/>{ user_id: "U123" }
    API->>SMEndpoint: invoke

    SMEndpoint->>FeastSDK: get_online_features(<br/>  features=[...],<br/>  entity_rows=[{user_id: "U123"}]<br/>)
    FeastSDK->>DDB: BatchGetItem on feature_groups
    Note over DDB: typical < 10ms
    DDB-->>FeastSDK: feature values

    FeastSDK-->>SMEndpoint: feature vector
    SMEndpoint->>Model: predict(features)
    Model-->>SMEndpoint: prediction + score
    SMEndpoint-->>API: {prediction: 0.87, ...}
    API-->>Client: 200 OK
```

### SageMaker vs Databricks training comparison

```mermaid
flowchart TB
    subgraph Common["Shared Inputs"]
        Features[("Feature Store<br/>training data")]
        Code["src/features/training/<br/>train.py"]
    end

    subgraph SMTrack["🔴 SageMaker Track"]
        SMJob["SageMaker Training Job<br/>(SPOT instances)"]
        SMOutput["Model artifact → S3"]
        SMRegistry["SageMaker Model Registry"]
    end

    subgraph DBTrack["🔵 Databricks Track"]
        DBJob["Databricks ML Job<br/>(MLflow autologging)"]
        DBOutput["Model → MLflow Run"]
        MLflowReg["MLflow Model Registry"]
    end

    subgraph Compare["Comparison Metrics"]
        M1["Time to first epoch"]
        M2["Cost per training run"]
        M3["Hyperparameter tuning"]
        M4["Reproducibility"]
        M5["Distributed training ease"]
    end

    Features --> SMJob
    Features --> DBJob
    Code --> SMJob
    Code --> DBJob

    SMJob --> SMOutput --> SMRegistry
    DBJob --> DBOutput --> MLflowReg

    SMJob -.measure.-> Compare
    DBJob -.measure.-> Compare

    classDef sm fill:#FF9900,color:#000
    classDef db fill:#FF3621,color:#fff
    classDef shared fill:#22C55E,color:#fff
    class SMJob,SMOutput,SMRegistry sm
    class DBJob,DBOutput,MLflowReg db
    class Features,Code shared
```

### Drift detection architecture

```mermaid
flowchart LR
    subgraph Live["Live Predictions"]
        Endpoint["SageMaker Endpoint"]
        DataCapture["Data Capture<br/>(S3 buffer)"]
    end

    subgraph Baseline["Baseline (training data)"]
        BaselineStats["Feature statistics<br/>computed once at training"]
        BaselineConstraints["Constraints JSON<br/>(distribution rules)"]
    end

    subgraph Monitor["Monitoring Job (hourly)"]
        SMM["SageMaker Model Monitor"]
        Compare["Compare current<br/>vs baseline"]
    end

    subgraph Outputs["Outputs"]
        Report["Constraint violation<br/>report"]
        CWMetric["CloudWatch metric<br/>'data_drift_score'"]
        Alert["SNS / Slack alert<br/>(if drift > threshold)"]
    end

    Endpoint --> DataCapture
    DataCapture --> SMM
    BaselineStats --> Compare
    BaselineConstraints --> Compare
    SMM --> Compare
    Compare --> Report
    Compare --> CWMetric
    CWMetric -.threshold breach.-> Alert

    classDef live fill:#22C55E,color:#fff
    classDef base fill:#a855f7,color:#fff
    classDef mon fill:#FF9900,color:#000
    classDef out fill:#3b82f6,color:#fff
    class Endpoint,DataCapture live
    class BaselineStats,BaselineConstraints base
    class SMM,Compare mon
    class Report,CWMetric,Alert out
```

### Feature lineage + governance

```mermaid
flowchart TB
    subgraph Source["Source"]
        Kinesis[("Kinesis events")]
        Postgres[("Postgres orders")]
    end

    subgraph FeatureViews["Feature Views (Feast)"]
        FV1["user_recency_features<br/>owner: ml-platform<br/>ttl: 1h"]
        FV2["user_lifetime_features<br/>owner: data-platform<br/>ttl: 30d"]
    end

    subgraph Models["Model Registry"]
        MR1["churn-predictor v3<br/>uses: FV1, FV2"]
        MR2["fraud-detector v7<br/>uses: FV1"]
    end

    subgraph Endpoints["Live Endpoints"]
        EP1["churn-prod"]
        EP2["fraud-prod"]
    end

    Kinesis --> FV1
    Postgres --> FV2

    FV1 --> MR1
    FV1 --> MR2
    FV2 --> MR1

    MR1 --> EP1
    MR2 --> EP2

    Note["Why this matters:<br/>1. Schema change in FV1?<br/>   → impacts MR1 + MR2 + EP1 + EP2<br/>2. Deprecate FV2?<br/>   → must retire MR1 first<br/>3. Audit: who uses Postgres data?<br/>   → query lineage graph"]

    classDef src fill:#22C55E,color:#fff
    classDef fv fill:#FF9900,color:#000
    classDef mr fill:#a855f7,color:#fff
    classDef ep fill:#10b981,color:#fff
    class Kinesis,Postgres src
    class FV1,FV2 fv
    class MR1,MR2 mr
    class EP1,EP2 ep
```

### Deployment + CI/CD

```mermaid
flowchart LR
    subgraph Dev["Developer"]
        FeastDef["feast_repo/<br/>feature_view.py"]
        TrainCode["src/features/training/"]
    end

    subgraph CI["GitHub Actions"]
        Lint["ruff + mypy + bandit"]
        FeastApply["feast apply --dry-run"]
        TFValidate["Terraform validate"]
        UnitTests["pytest"]
    end

    subgraph Deploy["Deploy"]
        FeastRegistry["feast apply<br/>(syncs registry)"]
        TFApply["terraform apply"]
        SMRetrain["SageMaker training job"]
        Register["Model Registry"]
        EndpointDeploy["SageMaker Endpoint update"]
    end

    FeastDef --> Lint
    TrainCode --> Lint
    Lint --> FeastApply
    Lint --> TFValidate
    Lint --> UnitTests

    FeastApply -->|on merge| FeastRegistry
    TFValidate -->|on tag| TFApply
    UnitTests -->|on tag| SMRetrain
    SMRetrain --> Register
    Register -->|approve| EndpointDeploy
```

---

## Repository Structure

```
aws-sagemaker-databricks-feature-store/
├── .github/workflows/          # CI: lint + TF validate + feast apply dry-run + tests
├── src/
│   ├── features/
│   │   ├── core/               # FeatureView, Entity, FeatureValue types
│   │   ├── sources/            # Kinesis, S3, Postgres source readers
│   │   ├── sinks/              # SageMaker FS + Databricks FS sinks
│   │   ├── transforms/         # Aggregation + embedding transforms
│   │   ├── registry/           # Feast registry sync helpers
│   │   ├── serving/            # Inference helpers
│   │   ├── training/           # Training script (sklearn/xgboost/pytorch)
│   │   ├── monitoring/         # Drift detection helpers
│   │   └── utils/              # Logging, secrets, Spark
│   ├── feast_repo/             # Feast feature_views + entities + data sources
│   └── lambdas/                # Streaming feature pipeline + monitoring
├── notebooks/                  # Databricks notebooks (training + DLT FE)
├── infra/terraform/
│   ├── modules/                # 17 modules
│   └── envs/                   # dev/staging/prod
├── dashboards/                 # Grafana + CloudWatch JSON
├── scripts/                    # feast apply, deploy endpoint, drift check
├── tests/                      # Unit + integration
├── config/                     # Feature view definitions, monitor configs
└── docs/
    ├── ARCHITECTURE.md
    ├── FEATURE_AUTHORING.md
    ├── POINT_IN_TIME_JOINS.md
    ├── ONLINE_OFFLINE_PARITY.md
    ├── MODEL_MONITORING.md
    ├── LOCAL_DEVELOPMENT.md
    ├── COST_ANALYSIS.md
    ├── RUNBOOK.md
    └── SAGEMAKER_VS_DATABRICKS.md
```

## Quick Start

```bash
git clone https://github.com/sushmakl95/aws-sagemaker-databricks-feature-store.git
cd aws-sagemaker-databricks-feature-store
make install-dev
make compose-up               # Local stack: Kinesis (LocalStack) + Postgres + Redis
make demo-streaming-features  # Computes streaming features locally
make demo-training            # Trains a model on synthetic features
```

## ⚠️ Cloud Cost Warning

Production deployment costs approximately **$1,200/month** at moderate inference throughput (1K predictions/sec). See [docs/COST_ANALYSIS.md](docs/COST_ANALYSIS.md). For evaluation, use the local Docker stack.

## Resume Alignment

- **Current (JLP)**: "PDP Sell team — feature engineering for clickstream models"
- **Equal Experts**: "Designed and operationalized ML feature pipelines on GCP"
- **Publicis Sapient / Goldman Sachs**: "Databricks lakehouse with MLflow model registry"

## License

MIT — see [LICENSE](LICENSE).
