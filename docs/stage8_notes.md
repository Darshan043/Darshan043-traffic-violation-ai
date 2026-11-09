# Stage 8 — MongoDB database

## Architecture and repository selection

The FastAPI routes use the existing repository interface. `JsonFileRepository` remains the default
(`REPO_BACKEND=json`); `MongoRepository` is selected only with `REPO_BACKEND=mongo`. Mongo access
uses PyMongo's `AsyncMongoClient` on a repository-owned event-loop thread. Mongo datetimes are
stored as UTC-aware values and returned as ISO UTC strings. Do not treat this implementation as
live-verified until the isolated Mongo integration tests and E2E run have passed.

## Private configuration and startup

Set these names in a private `.env` file or inject them through a secret manager. Do not put values
in source control, command output, screenshots, or chat.

- `MONGO_URL` — MongoDB connection URI.
- `MONGO_DB` — database name; the application default is `traffic_ai`.
- `REPO_BACKEND` — `json` (default) or `mongo`.
- `MONGO_OPERATION_TIMEOUT_SECONDS` — positive operation wait timeout; default 30 seconds.
- `MONGO_TEST_URL` — explicitly supplied URI for the isolated Mongo integration tests and E2E writer.
- `MONGO_TEST_DB` — must be `traffic_ai_test`; tests append a random 10-character lowercase hex suffix.
- `MONGO_TEST_DATABASE` — optional exact `traffic_ai_test_<10 lowercase hexadecimal characters>` name pre-authorized for one E2E run. When unset, E2E generates a name; the preflight checker requires an explicit name.
- `MONGO_TEST_ISOLATED` — set to `1` only after confirming the test URI targets an isolated test deployment.
- `MONGO_E2E_ISOLATED` — set to `1` only after confirming the configured E2E database is isolated.
- `MONGO_READONLY_URL` — read-only credential used by migration dry-run and evidence cleanup tools.
- `MONGO_E2E_READONLY_URL` — Stage 8-only read credential scoped to `traffic_ai_e2e_audit` on the isolated test deployment. Stage 8 writes manifests to this database only through `MONGO_TEST_URL`.

Create an admin interactively and start the backend:

```powershell
.\.venv\Scripts\python.exe scripts\create_admin.py
.\scripts\run_backend.ps1
```

The admin script prompts for a password without echoing it and closes its repository on normal,
failure, and cancellation paths. Open `http://localhost:8000/docs` for the API documentation.

## Collections and indexes

Startup idempotently creates the five collections' required indexes:

- `users`: username, full name, password hash, role, active state, creation and last-login timestamps.
  Unique index: `username`.
- `cameras`: camera ID, name, location, source details, enabled/status fields, driver/camera/motorcycle
  views, checks, normalized zone, and creation/update timestamps. Unique index: `camera_id`.
- `vehicle_events`: one document for every finalized vehicle result, including compliant vehicles;
  event/camera/run/track IDs, vehicle type, result, confidence, frames used, reason code, UTC timestamp,
  and video time. Unique index: `event_id`; query index: `(camera_id, timestamp descending)`.
- `violations`: only `NO_HELMET`, `NO_SEATBELT`, and `NEEDS_REVIEW`; includes event/camera/track IDs,
  violation type, immutable AI result, confidence, reason, relative evidence paths, review status and
  history, reviewer fields, final decision, and creation time. Unique index: `event_id`; query indexes:
  `(camera_id, created_at descending)`, `review_status`, `violation_type`, and `track_id`.
- `system_settings`: key, value, updater, and update time. Unique index: `key`.

Unique event IDs include the processing run ID so repeated processing does not collide. Human review
changes review fields and final decision; it preserves the original AI result.

## Tests and live processing

Run the default suite, which excludes Mongo and real-model integration tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Mongo integration tests are destructive only to their temporary database. Before opting in, verify
`MONGO_TEST_URL` is for a dedicated, isolated test deployment, not merely a test-named database on a
production cluster. Set `MONGO_TEST_ISOLATED=1` only after confirming that isolation. The guard compares
its host endpoint with `MONGO_URL`, requires an explicit URI, and restricts teardown to the generated
`traffic_ai_test_<10 lowercase hexadecimal characters>` name.
The tests must never run against `traffic_ai` or any production deployment:

```powershell
.\.venv\Scripts\python.exe -m pytest -m mongo -q -p no:cacheprovider --tb=short
```

The connection preflight is test-only: `scripts/check_mongo.py` reads `MONGO_TEST_URL`, requires
`MONGO_TEST_DB=traffic_ai_test`, `MONGO_TEST_DATABASE` matching the randomized name pattern, and a
different deployment endpoint from `MONGO_URL`. It only pings and lists collections; it refuses a
non-empty database and never falls back to `MONGO_URL`. It does not import application settings or
require `SECRET_KEY`. Set `MONGO_TEST_DATABASE` to a fresh name that has already been authorized for
the test writer before running it.

The E2E helper is `scripts/s8_e2e.py`. It uses `data\videos\helmet_test.mp4`, performs two sequential
runs, and writes sanitized logs plus `test_manifest.json` under a new temporary evidence folder. Before
running it, configure the application to use an explicitly isolated, non-production Mongo deployment
and a randomized database named `traffic_ai_test_<10 lowercase hexadecimal characters>`, provide
`MONGO_E2E_READONLY_URL` with read access only to `traffic_ai_e2e_audit`, and set
`MONGO_E2E_ISOLATED=1` only after confirming the deployment is isolated. The existing `MONGO_TEST_URL`
writer must also be scoped to the isolated test deployment. Add a custom Atlas role on
`traffic_ai_e2e_audit.e2e_runs` with only the actions needed to find, insert, and update manifests, and
grant it to the test writer; keep its existing randomized test DB permissions unchanged. The
inspection user gets the built-in `read` role on `traffic_ai_e2e_audit`. The helper verifies the fresh
randomized database before use and does not drop databases or clean up prior records. Previous-run
inspection reads run manifests from `traffic_ai_e2e_audit` (one manifest is updated in place as its run
progresses; manifests are never deleted by the helper);
it verifies manifest contents only and does not verify that referenced records still exist in the prior
randomized databases. An unfinished `running` manifest indicates an incomplete run, not proof of its
database contents. The current project environment has not been verified as isolated; do not run E2E
until that is confirmed. `helmet_test.mp4` may contain only compliant helmet events, so it does
not validate a `NO_HELMET` case or seatbelt detection.

For least-privilege E2E runs, pre-authorize the exact randomized database name for the writer and set
`MONGO_TEST_DATABASE` to that name before launch. The helper validates the exact pattern and still
checks that the database is fresh before use. A name can be supplied by the run operator; when it is
unset, the helper generates a random name as before. Grant database-scoped `readWrite` only on that
one test database. The helper does not create, change, or revoke Atlas roles or permissions. Keep the
audit writer and read-only reader as separate database users with separate URIs. The test writer uses
`MONGO_TEST_URL` and gets `find`, `insert`, and `update` only on `traffic_ai_e2e_audit.e2e_runs`; the
reader uses `MONGO_E2E_READONLY_URL` and gets only `find` on that collection.

## Migration and evidence cleanup

`scripts/migrate_json_to_mongo.py --dry-run` requires the read-only credential and reports records
that are absent from Mongo. It performs no inserts, index creation, or settings seeding. Apply mode
requires `REPO_BACKEND=mongo`; it inserts missing records and skips existing users, cameras, events,
violations, and settings rather than overwriting them. Back up data and review the dry-run counts before
applying a migration.

`scripts/cleanup_evidence.py --days N` is a read-only preview by default and requires the read-only
credential to check confirmed violations. Add `--apply` only after reviewing the preview. Confirmed
violation evidence and records with unknown metadata are preserved. Evidence paths are relative to
`storage/evidence`; do not delete that directory broadly.

## Backup and restore

Keep backups outside Git and protect them like production data. Set the URI privately in the shell or
secret manager; do not paste it directly into a shared command log. For example, with a URI already
available as `MONGO_URL` in the process environment:

```powershell
mongodump --uri="$env:MONGO_URL" --db="$env:MONGO_DB" --out=.\backup
```

Restore to a separate review database first so the source database is not replaced:

```powershell
mongorestore --uri="$env:MONGO_URL" --nsFrom="$env:MONGO_DB.*" --nsTo="traffic_ai_restore.*" .\backup\$env:MONGO_DB
```

Check the current MongoDB Atlas plan for its present storage, backup, and restore limits before relying
on hosted backups. Plan capabilities and limits can change; none are assumed here.
