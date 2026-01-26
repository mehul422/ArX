<!-- Har Har Mahadev -->
# ArX
Rockets go boom boom 🚀 

## Tech Stack
<!-- Har Har Mahadev -->
See `docs/tech-stack.md` for the canonical stack used across this project.

## Backend runbook (local)

### Prerequisites
- Python 3.11+
- Redis
- PostgreSQL

### Environment variables
- `POSTGRES_DSN` (required)
- `REDIS_URL` (optional; default `redis://localhost:6379/0`)
- `JAR_DIR` (optional; default `backend/resources/jars`)
- `OPENROCKET_JAR` (required for OpenRocket integration)
- `CORS_ORIGINS` (optional; comma-separated)
- `CELERY_TASK_SOFT_TIME_LIMIT` (optional; seconds)
- `CELERY_TASK_TIME_LIMIT` (optional; seconds)

### Run API
```bash
export POSTGRES_DSN="postgresql://user:password@localhost:5432/arx"
export REDIS_URL="redis://localhost:6379/0"
uvicorn app.main:app --reload --port 8000
```

### Run worker
```bash
export POSTGRES_DSN="postgresql://user:password@localhost:5432/arx"
export REDIS_URL="redis://localhost:6379/0"
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

### Example requests
```bash
curl -X POST http://localhost:8000/api/v1/simulate \
  -H "Content-Type: application/json" \
  -d '{"params":{"chamber_pressure":3000000,"burn_time":2.2}}'

curl http://localhost:8000/api/v1/simulate/<job_id>
```
