# Data Pipeline - TempleDB Example Project

A data processing pipeline demonstrating TempleDB's file tracking, versioning, and environment management.

## Overview

This project implements a data pipeline that:
1. Extracts data from multiple sources (CSV, JSON, APIs)
2. Transforms data using Python/Pandas
3. Loads data into a SQLite data warehouse
4. Generates reports and analytics

## Project Structure

```
data-pipeline/
├── src/
│   ├── extract/          # Data extraction
│   │   ├── csv_reader.py
│   │   ├── json_reader.py
│   │   └── api_client.py
│   ├── transform/        # Data transformation
│   │   ├── cleaner.py
│   │   ├── validator.py
│   │   └── enricher.py
│   ├── load/             # Data loading
│   │   └── warehouse.py
│   ├── pipeline.py       # Main pipeline orchestrator
│   └── config.py
├── sql/
│   ├── schema.sql        # Warehouse schema
│   └── queries/          # Analytics queries
│       ├── daily_report.sql
│       └── user_stats.sql
├── data/
│   ├── input/            # Source data (gitignored)
│   └── output/           # Generated reports (gitignored)
├── tests/
│   ├── test_extract.py
│   ├── test_transform.py
│   └── test_load.py
├── requirements.txt
├── Makefile
└── README.md
```

## Pipeline Stages

### 1. Extract
Pull data from various sources:
- CSV files
- JSON APIs
- Database exports

### 2. Transform
Clean and process data:
- Data validation
- Type conversion
- Duplicate removal
- Enrichment from external sources

### 3. Load
Store processed data:
- Create warehouse tables
- Bulk insert operations
- Update incremental data

## TempleDB Integration

### File Tracking

TempleDB automatically tracks:
```sql
-- Python pipeline scripts
SELECT file_path, lines_of_code
FROM files_with_types_view
WHERE project_slug = 'data-pipeline'
  AND type_name = 'python';

-- SQL queries and schemas
SELECT file_path, lines_of_code
FROM files_with_types_view
WHERE project_slug = 'data-pipeline'
  AND type_name = 'sql_file';
```

### Version Control

Track pipeline changes:
```bash
# Check pipeline status
templedb vcs status data-pipeline

# Commit pipeline changes
templedb vcs commit -p data-pipeline \
  -m "Add user enrichment transformer" \
  -a "Data Engineer"

# View pipeline history
templedb vcs log data-pipeline -n 10
```

### Environment Management

Create isolated environments:
```bash
# Auto-detect dependencies
templedb env detect data-pipeline

# Create environment
templedb env new data-pipeline dev

# Enter environment
templedb env enter data-pipeline dev

# Inside environment:
pip install -r requirements.txt
python src/pipeline.py
```

### Secrets Management

Store API keys and credentials:
```bash
# Initialize secrets
templedb secret init data-pipeline --age-recipient <key>

# Add secrets interactively
./prompt_missing_vars.sh data-pipeline production

# Export to environment
eval "$(templedb secret export data-pipeline --format shell)"
```

## Running the Pipeline

```bash
# Full pipeline
python src/pipeline.py

# Extract only
python src/pipeline.py --stage extract

# Transform and load
python src/pipeline.py --stage transform,load

# With config
python src/pipeline.py --config config/production.yaml
```

## Environment Variables

Required variables:
- `DATA_SOURCE_URL` - Source database/API URL
- `API_KEY` - Authentication key
- `WAREHOUSE_PATH` - Output SQLite database
- `LOG_LEVEL` - Logging verbosity

## Makefile Targets

```bash
# Run pipeline
make run

# Run tests
make test

# Check code quality
make lint

# Generate documentation
make docs

# Clean generated files
make clean
```

## Analytics Queries

Example queries in `sql/queries/`:

```sql
-- daily_report.sql
SELECT
  DATE(created_at) as date,
  COUNT(*) as records_processed,
  COUNT(DISTINCT user_id) as unique_users,
  AVG(processing_time_ms) as avg_processing_time
FROM pipeline_runs
GROUP BY DATE(created_at)
ORDER BY date DESC
LIMIT 30;
```

Run with:
```bash
sqlite3 data/warehouse.db < sql/queries/daily_report.sql
```

## TempleDB Workflow

```bash
# 1. Import project
templedb project import /path/to/data-pipeline

# 2. Setup environment
templedb env detect data-pipeline
templedb env new data-pipeline dev
templedb env enter data-pipeline dev

# 3. Configure secrets
./prompt_missing_vars.sh data-pipeline dev

# 4. Run pipeline
python src/pipeline.py

# 5. Commit results
templedb vcs commit -p data-pipeline \
  -m "Pipeline run: $(date +%Y-%m-%d)" \
  -a "Pipeline Bot"

# 6. Query history
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT commit_message, created_at
   FROM vcs_commit_history_view
   WHERE project_slug = 'data-pipeline'
   ORDER BY created_at DESC
   LIMIT 10"
```

## Deployment

```bash
# Create production environment
templedb env new data-pipeline prod

# Configure production secrets
templedb secret init data-pipeline --profile prod --age-recipient <key>
templedb secret edit data-pipeline --profile prod

# Deploy
templedb deploy data-pipeline prod

# Monitor
tail -f logs/pipeline-$(date +%Y-%m-%d).log
```

## Testing

```bash
# Run all tests
pytest

# Run specific test
pytest tests/test_transform.py

# With coverage
pytest --cov=src tests/
```

## Monitoring

Pipeline metrics tracked:
- Records processed per run
- Processing time
- Error rates
- Data quality scores

View metrics:
```sql
SELECT * FROM pipeline_metrics
WHERE run_date >= DATE('now', '-7 days')
ORDER BY run_date DESC;
```

## TempleDB Benefits

This pipeline demonstrates:
1. **File Tracking**: All scripts, SQL, and configs tracked
2. **Version Control**: Database-native commits and history
3. **Environment Isolation**: Reproducible Nix environments
4. **Secret Management**: Encrypted API keys and credentials
5. **SQL Queryability**: Query pipeline history with SQL
6. **Deployment**: Automated deployment with TempleDB

---

*Built with TempleDB - Database-native project management*
