# Databricks notebook source
# MAGIC %md
# MAGIC # Databricks ML Training: Churn Model
# MAGIC
# MAGIC Trains an XGBoost churn model using feature tables from the Databricks
# MAGIC Feature Store. MLflow autologging captures params + metrics + model
# MAGIC artifact. After training, registers to Unity Catalog model registry
# MAGIC and optionally deploys to Model Serving.
# MAGIC
# MAGIC Parameters:
# MAGIC - training_label_table
# MAGIC - model_name (UC 3-part name)
# MAGIC - run_name

# COMMAND ----------

dbutils.widgets.text("training_label_table", "main.ml.churn_labels_train")
dbutils.widgets.text("model_name", "main.ml.churn_predictor")
dbutils.widgets.text("run_name", "churn-train")

training_label_table = dbutils.widgets.get("training_label_table")
model_name = dbutils.widgets.get("model_name")
run_name = dbutils.widgets.get("run_name")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build point-in-time correct training set via Feature Store

# COMMAND ----------

from databricks.feature_engineering import FeatureEngineeringClient, FeatureLookup

fe = FeatureEngineeringClient()

feature_lookups = [
    FeatureLookup(
        table_name="main.feature_store.user_lifetime",
        lookup_key="user_id",
        feature_names=[
            "account_age_days",
            "total_orders",
            "total_spend",
            "avg_order_value",
            "distinct_products_purchased",
            "churn_risk_score",
        ],
        timestamp_lookup_key="event_time",
    ),
    FeatureLookup(
        table_name="main.feature_store.user_recency",
        lookup_key="user_id",
        feature_names=[
            "events_last_5min",
            "events_last_1h",
            "distinct_products_last_1h",
            "avg_order_value_last_1h",
            "seconds_since_last_event",
        ],
        timestamp_lookup_key="event_time",
    ),
]

label_df = spark.read.table(training_label_table)

training_set = fe.create_training_set(
    df=label_df,
    feature_lookups=feature_lookups,
    label="churned",
    exclude_columns=["user_id", "event_time"],
)

train_pd = training_set.load_df().toPandas()
print(f"Training rows: {len(train_pd):,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train XGBoost with MLflow autolog

# COMMAND ----------

import mlflow
import xgboost as xgb
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

mlflow.xgboost.autolog(log_input_examples=False, log_model_signatures=True)

X = train_pd.drop(columns=["churned"])
y = train_pd["churned"].astype(int)

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y,
)

with mlflow.start_run(run_name=run_name) as run:
    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.08,
        eval_metric="logloss",
        random_state=42,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=50)

    y_proba = model.predict_proba(X_test)[:, 1]
    y_pred = (y_proba > 0.5).astype(int)

    auc = roc_auc_score(y_test, y_proba)
    f1 = f1_score(y_test, y_pred)
    mlflow.log_metric("test_roc_auc", auc)
    mlflow.log_metric("test_f1", f1)

    print(f"Test ROC-AUC: {auc:.4f}")
    print(f"Test F1:      {f1:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log as Feature-Store-backed model (enables online features at serving)

# COMMAND ----------

fe.log_model(
    model=model,
    artifact_path="churn-model",
    flavor=mlflow.xgboost,
    training_set=training_set,
    registered_model_name=model_name,
)

print(f"Registered to UC: {model_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## (Optional) Promote + deploy to Model Serving
# MAGIC
# MAGIC Uncomment below after review + approval. This bumps the model to
# MAGIC `@Production` alias and updates the serving endpoint.

# COMMAND ----------

# from mlflow.tracking import MlflowClient
# client = MlflowClient()
# latest_version = client.get_latest_versions(model_name, stages=["None"])[0].version
# client.set_registered_model_alias(model_name, "Production", latest_version)
# print(f"Promoted {model_name} v{latest_version} to @Production")
