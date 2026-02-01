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
- `MOTORS_DIR` (optional; default `backend/resources/motors`)
- `MOTOR_UPLOAD_DIR` (optional; default `backend/resources/motors/uploads`)
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
curl http://localhost:8000/api/v1/motors

curl -X POST http://localhost:8000/api/v1/motors/upload \
  -F "file=@/path/to/motor.eng"

curl -X POST http://localhost:8000/api/v1/motors/import \
  -F "file=@/path/to/motor.rse"

curl -X POST http://localhost:8000/api/v1/simulate \
  -H "Content-Type: application/json" \
  -d '{"rocket_path":"/abs/path/rocket.ork","motor_source":"bundled","motor_id":"motor.eng","material_mode":"custom","use_all_stages":true,"params":{"chamber_pressure":3000000,"burn_time":2.2}}'

curl http://localhost:8000/api/v1/simulate/<job_id>

curl -X POST http://localhost:8000/api/v1/simulate/openrocket-like \
  -H "Content-Type: application/json" \
  -d '{
    "stage0":{
      "stage_id":"S0",
      "grain_geometry":{"type":"BATES","params":{"diameter_m":0.15,"core_diameter_m":0.07,"length_m":0.3,"grain_count":3}},
      "nozzle":{"throat_diameter_m":0.05,"exit_diameter_m":0.1},
      "propellant_label":{"name":"KNSB"}
    },
    "stage1":{
      "stage_id":"S1",
      "grain_geometry":{"type":"BATES","params":{"diameter_m":0.15,"core_diameter_m":0.07,"length_m":0.3,"grain_count":3}},
      "nozzle":{"throat_diameter_m":0.05,"exit_diameter_m":0.1},
      "propellant_label":{"name":"KNSB"}
    },
    "rkt_path":"/abs/rocket.rkt",
    "constraints":{"max_pressure_psi":750,"max_kn":500,"max_vehicle_length_in":300},
    "cd_max":0.6,
    "mach_max":2.5,
    "cd_ramp":true
  }'

Notes for `/simulate/openrocket-like`:
- `propellant_label` is treated as metadata; physics comes from `propellant_physics` or preset library match.
- `.eng` artifacts include a `propellant` comment line when a label is provided.
- Response includes `inputs_hash` and `engine_versions` for reproducibility.

curl -X POST http://localhost:8000/api/v1/optimize/mission-target \
  -H "Content-Type: application/json" \
  -d '{
    "mode":"guided",
    "objectives":[{"name":"apogee_ft","target":60000,"units":"ft"}],
    "constraints":{"max_pressure_psi":750,"max_kn":300,"max_vehicle_length_in":223,"max_stage_length_ratio":1.15},
    "vehicle":{"base_ric_path":"/abs/base.ric","rkt_path":"/abs/rocket.rkt"},
    "solver_config":{
      "split_ratios":[0.5],
      "design_space":{
        "diameter_scales":[1.0],
        "length_scales":[1.0],
        "core_scales":[1.0],
        "throat_scales":[1.0],
        "exit_scales":[1.0]
      }
    }
  }'

curl -X POST http://localhost:8000/api/v1/optimize/mission-target/target-only \
  -H "Content-Type: application/json" \
  -d '{
    "objectives":[{"name":"apogee_ft","target":60000,"units":"ft"}],
    "constraints":{"max_pressure_psi":750,"max_kn":500,"max_vehicle_length_in":300,"max_stage_length_ratio":1.15},
    "vehicle":{"ref_diameter_in":8.0,"rocket_length_in":200,"total_mass_lb":132.3},
    "solver_config":{"split_ratios":[0.5],"design_space":{"diameter_scales":[0.8,1.0,1.2],"length_scales":[0.8,1.0,1.2],"core_scales":[0.9,1.0,1.1],"throat_scales":[0.8,1.0,1.2],"exit_scales":[1.0,1.2]}},
    "allowed_propellants":{"names":["APCP","AP/HTPB"]}
  }'

To use separate stage templates:
```json
{
  "vehicle":{
    "stage0_ric_path":"/abs/stage0.ric",
    "stage1_ric_path":"/abs/stage1.ric",
    "rkt_path":"/abs/rocket.rkt"
  }
}
```

curl http://localhost:8000/api/v1/optimize/mission-target/<job_id>/manual-report

### API response notes (v1)
- `/simulate` returns `internal_ballistics_estimate` (simple estimate) and a deprecated alias under `deprecated_aliases.openmotor`.
- `/optimize/mission-target` returns `openmotor_motorlib_result` (authoritative motorlib output).
- All v1 job responses include `api_version`, `job_kind`, `inputs_hash`, and `engine_versions`.
- Trajectory engine is reported as `trajectory_engine.id = "internal_v1"`.
```
