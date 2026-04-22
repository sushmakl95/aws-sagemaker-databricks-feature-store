# Databricks notebook source
# MAGIC %md
# MAGIC # Drift Monitoring Dashboard
# MAGIC
# MAGIC Queries the SageMaker Model Monitor output (in S3, synced to a Delta
# MAGIC mirror) + the Databricks Lakehouse Monitoring output, and renders
# MAGIC drift trends as widgets.
# MAGIC
# MAGIC Publish as a Databricks SQL dashboard; refresh hourly.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Drift score trend (last 7 days)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   date_trunc('hour', monitoring_run_ts) AS hour,
# MAGIC   feature_name,
# MAGIC   psi,
# MAGIC   ks_stat
# MAGIC FROM main.monitoring.drift_reports
# MAGIC WHERE monitoring_run_ts > current_timestamp() - INTERVAL 7 DAYS
# MAGIC ORDER BY hour DESC, feature_name

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Top drifting features (last 24h)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   feature_name,
# MAGIC   COUNT_IF(drift_detected) AS drift_hours_last_24h,
# MAGIC   AVG(psi) AS avg_psi,
# MAGIC   MAX(psi) AS max_psi,
# MAGIC   MIN(ks_pvalue) AS min_ks_pvalue
# MAGIC FROM main.monitoring.drift_reports
# MAGIC WHERE monitoring_run_ts > current_timestamp() - INTERVAL 24 HOURS
# MAGIC GROUP BY feature_name
# MAGIC HAVING drift_hours_last_24h > 0
# MAGIC ORDER BY drift_hours_last_24h DESC, avg_psi DESC

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Endpoint performance next to drift

# COMMAND ----------

# MAGIC %sql
# MAGIC WITH drift_hourly AS (
# MAGIC   SELECT
# MAGIC     endpoint_name,
# MAGIC     date_trunc('hour', monitoring_run_ts) AS hour,
# MAGIC     COUNT_IF(drift_detected) AS drifted_features,
# MAGIC     AVG(psi) AS avg_psi
# MAGIC   FROM main.monitoring.drift_reports
# MAGIC   WHERE monitoring_run_ts > current_timestamp() - INTERVAL 7 DAYS
# MAGIC   GROUP BY endpoint_name, date_trunc('hour', monitoring_run_ts)
# MAGIC ),
# MAGIC perf_hourly AS (
# MAGIC   SELECT
# MAGIC     endpoint_name,
# MAGIC     date_trunc('hour', request_ts) AS hour,
# MAGIC     COUNT(*) AS invocation_count,
# MAGIC     percentile(latency_ms, 0.99) AS p99_latency_ms,
# MAGIC     AVG(prediction_score) AS avg_prediction_score
# MAGIC   FROM main.monitoring.inference_logs
# MAGIC   WHERE request_ts > current_timestamp() - INTERVAL 7 DAYS
# MAGIC   GROUP BY endpoint_name, date_trunc('hour', request_ts)
# MAGIC )
# MAGIC SELECT
# MAGIC   d.endpoint_name,
# MAGIC   d.hour,
# MAGIC   d.drifted_features,
# MAGIC   d.avg_psi,
# MAGIC   p.invocation_count,
# MAGIC   p.p99_latency_ms,
# MAGIC   p.avg_prediction_score
# MAGIC FROM drift_hourly d
# MAGIC JOIN perf_hourly p USING (endpoint_name, hour)
# MAGIC ORDER BY d.hour DESC, d.endpoint_name

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Feature freshness
# MAGIC
# MAGIC Stale features cause silent drift. Surface any FV whose most recent
# MAGIC ingestion is older than its TTL.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   feature_view,
# MAGIC   MAX(ingestion_time) AS latest_ingest,
# MAGIC   (unix_timestamp(current_timestamp()) - unix_timestamp(MAX(ingestion_time))) AS seconds_since_last_ingest,
# MAGIC   ttl_seconds,
# MAGIC   CASE
# MAGIC     WHEN (unix_timestamp(current_timestamp()) - unix_timestamp(MAX(ingestion_time))) > ttl_seconds
# MAGIC     THEN 'STALE'
# MAGIC     ELSE 'FRESH'
# MAGIC   END AS status
# MAGIC FROM main.feature_store.feature_freshness_registry
# MAGIC GROUP BY feature_view, ttl_seconds
# MAGIC ORDER BY seconds_since_last_ingest DESC
