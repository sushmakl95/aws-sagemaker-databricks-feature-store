-- Create databases used by local services.
-- feast_registry already exists (POSTGRES_DB); add mlflow.
CREATE DATABASE mlflow;
GRANT ALL PRIVILEGES ON DATABASE mlflow TO feast;
