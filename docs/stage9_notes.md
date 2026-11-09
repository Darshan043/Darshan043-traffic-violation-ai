# Stage 9 notes — backend contract and implementation record

## Inspection baseline

- Stage 8 is committed at `674e10d` (`Stage 8: MongoDB integration and safety tests`). The preceding commits are Stage 7 changes.
- Stage 7/8 notes and all Python model/router modules under `backend/app/models` and `backend/app/routers` were inspected on 2026-11-09.
- Frontend project files are currently untracked; `.venv.backup-20261105-230503/` is also untracked and was left untouched.
- API errors use `{"error":"CODE","message":"..."}`. Typical codes: `BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `VALIDATION_ERROR`, `TOO_MANY_REQUESTS`, and `INTERNAL_SERVER_ERROR`.
- Date-time fields are ISO 8601 strings (UTC from backend data). Missing nullable values are `null`; do not assume empty strings.

## Backend response shapes used by the UI

Shapes below reflect the actual route response models and return values. Mock responses must follow these contracts; don't invent extra keys on a route response. Request/query details are included where needed to explain how the UI calls the route.

| Operation | Endpoint | Exact successful response shape |
|---|---|---|
| Login | `POST /api/auth/login` | `{ access_token: string, token_type: "bearer", user: UserResponse }`; `UserResponse = { id: string, username: string, role: "admin"|"reviewer"|"viewer", is_active: boolean, created_at: string }`. Request `{ username, password }`. |
| Current user | `GET /api/auth/me` | `UserResponse` as above. |
| Cameras | `GET /api/cameras` | `CameraResponse[]`; one camera is `{ camera_id, name, location, source_type: "file"|"rtsp", source_path, enabled, status: "offline"|"online"|"processing"|"error", driver_side: "left"|"right", camera_view: "front"|"side_or_rear"|"unknown", motorcycle_view: "approaching"|"receding", checks: string[], zone: number[], created_at, updated_at }`. `source_path` masks any RTSP password as `***`. Create/update/upload/zone routes return the same `CameraResponse`; delete returns HTTP 204 and no body. |
| Camera status | `GET /api/cameras/{camera_id}/status` | `{ camera_id: string, status: "offline"|"online"|"processing"|"error" }`. |
| Camera actions | `POST /api/cameras/{id}/start` and `/stop` | `{ camera_id: string, status: string }` (`processing` after start; `offline` after stop). |
| Violation list | `GET /api/violations?...` | `{ items: ViolationModel[], total: number, page: number, limit: number }`. Query keys: `type`, `result`, `camera`, `date_from`, `date_to`, `track_id`, `review_status`, `page`, `limit`. Each list item is `ViolationModel`: `{ event_id, camera_id, track_id, violation_type, ai_result, detection_confidence, reason_code, evidence: object, review_status, final_decision, reviewed_by, reviewed_at, review_note, created_at, review_history: object[] }`. |
| One violation | `GET /api/violations/{event_id}` | `ViolationResponse`: `{ event_id, camera_id, track_id, violation_type, ai_result, detection_confidence, reason_code, evidence: object, review_status, final_decision, reviewed_by, reviewed_at, review_note, created_at }`. Nullable decision/reviewer/time/note fields are `null`; **this response model omits `review_history`**. |
| Review violation | `PUT /api/violations/{event_id}/review` | Same `ViolationResponse` shape as one violation (therefore also omits `review_history`). Request `{ final_decision, review_note }`; accepted final decisions include `CONFIRMED_VIOLATION`, `NOT_A_VIOLATION`, `PENDING` and legacy values. The route preserves `ai_result`. |
| Stats summary | `GET /api/stats/summary` | `{ total_vehicles, compliant_vehicles, violations, needs_review, compliance_percentage, reviewed_count, unreviewed_count, helmet_compliance_percentage, seatbelt_compliance_percentage, review_count }` (numbers). Compliance excludes `NEEDS_REVIEW`; backend returns percentage values on a 0–100 scale. |
| Daily stats | `GET /api/stats/daily` | `DailyStat[]`; each `{ date, total_vehicles, compliant_vehicles, violations, needs_review, compliance_percentage }`. Sorted newest date first by fallback implementation. |
| Camera stats | `GET /api/stats/cameras` | `CameraStat[]`; each `{ camera_id, camera_name, total_vehicles, compliant_vehicles, violations, needs_review, compliance_percentage }`. |
| Settings | `GET/PUT /api/settings` | `{ helmet_min_confidence, seatbelt_min_confidence, seatbelt_min_car_height, duplicate_window_sec, duplicate_iou_threshold, max_workers, frame_skip, image_size, evidence_retention_days, extra: object }`. All fields have backend defaults; request/response are this same shape. Admin only. |
| Users | `GET /api/users` | `UserResponse[]`, where each `{ id, username, role, is_active, created_at }`. Create (`POST`), update (`PUT /{id}`), and disable (`DELETE /{id}`) also return one `UserResponse`; `DELETE` disables and does not remove. Admin only. |
| WebSocket | `WS /ws/alerts?token=...` | JSON message variants: `{ type: "event_candidate", event: object, provisional: true }`; `{ type: "violation", event: ViolationModel }`; `{ type: "camera_status", camera_id, status, error? }`; `{ type: "finished", camera_id }`. Event candidate fields originate in engine event records: `event_id`, `camera_id`, `track_id`, `vehicle_type`, `violation_type`, `decision`, `ai_result`, `confidence`, `reason`, `observations`, `evidence`, `timestamp_sec`, and `frame_idx` (run ID may be attached). Candidate events are provisional; persisted `violation` events are final records. |
| Evidence image | `GET /evidence/{file_path:path}` | Binary file response (usually image bytes), not JSON. Auth accepts `Authorization: Bearer <token>` **or** `?token=...`; missing/invalid token is 401. Use the header and fetch-to-blob for evidence images. Paths are relative to the evidence directory and traversal is rejected. |
| Snapshot | `GET /api/cameras/{id}/snapshot` | Binary `image/jpeg`, not JSON; authenticated with standard Bearer header. |
| MJPEG | `GET /api/stream/{camera_id}?token=...` | Streaming `multipart/x-mixed-replace; boundary=frame`, with JPEG frames. This route specifically requires token in the query string for an `<img>` source. |
| CSV export | `GET /api/violations/export?...` | Streamed `text/csv`, attachment `violations.csv`, not JSON. Header order: `event_id,camera_id,track_id,violation_type,ai_result,detection_confidence,reason_code,review_status,final_decision,reviewed_by,reviewed_at,review_note,created_at`. Supports the violation filters except pagination. |
| Health | `GET /api/health` | `{ status: "ok" }`. |

`ViolationModel.evidence` is an object populated from engine evidence metadata/paths; the API does not declare a fixed nested evidence schema. The client should treat its keys as optional and build evidence URLs from returned relative paths.

## Needed from the backend for Stage 10

1. **Decision-threshold settings are not exposed.** Stage 9 asks for `observation_min_conf`, `min_observations`, `compliant_threshold`, `violation_threshold`, `agreement_ratio`, and `max_unclear_ratio`; `SystemSettings` instead exposes the settings listed above. Engine `DecisionThresholds` has `min_observations`, `violation_threshold`, `compliance_threshold`, `min_mean_confidence`, and `conflict_share`, but these are not connected to the settings API. No backend changes were made.
2. **Live status metrics are absent.** Camera status only returns `camera_id` and `status`; there is no FPS or tracked-vehicle count endpoint/field. The UI can show connection state, but those numeric metrics need backend support.
3. **Storage/database health is absent.** `/api/health` only returns `{status:"ok"}`. There is no read-only endpoint for database connection or storage usage/retention status.
4. **Violation review history is inconsistent across routes.** The list route returns `Violation.model_dump()` including `review_history`; the detail and review routes use `ViolationResponse`, which excludes it. A UI detail drawer cannot rely on review history from those routes without a backend contract change or local fallback. Also, JSON storage uses legacy statuses such as `UNREVIEWED`/`REVIEWED`, while Mongo storage normalizes to `pending`/`confirmed`/`rejected`/`not_required`; clients should accept both enum families.
5. **No dedicated video upload progress API.** The existing multipart upload is a normal HTTP response; browser-side upload progress is possible via XMLHttpRequest, but server does not report processing progress.
6. **No API field reports the current processing pass.** Stage 7 notes mention pass text drawn on annotated frames, but `/api/stream` emits the engine's current MJPEG frame; camera status/WebSocket messages do not expose a structured pass indicator or FPS.

## Relevant route limits and notes

- Video upload extensions: `.mp4`, `.avi`, `.mov`, `.mkv`; size limit defaults to 500 MB (configured by backend `MAX_UPLOAD_MB`).
- Zone payload is `{ points: number[] }`, flattened normalized x/y values in `[0,1]`; at least two points (four numbers), any even number thereafter.
- Camera creation uses `camera_id` (1–50 chars) and `name` (1–100 chars). Camera update is partial.
- Violation pagination: page ≥1; limit 1–500 (default 50). `track_id` is numeric. The backend's `result` query filters by AI result; it is not a separate final-review result field.
- Server-side authorization remains authoritative. UI role gating is only a usability layer.

## Stage 9 pages and implementation

| Page | Main components and data areas | State and access behavior |
|---|---|---|
| Login | `LoginPage`, `AuthContext` | Login loading/error feedback; mock-only accounts are shown only in mock mode. |
| Dashboard | `StatCard`, `LiveCanvas`, `Badge`, `EvidenceImage`, Recharts line chart, `Panel` | Summary, cameras, daily stats and violations each have loading/error/empty states; incoming socket alerts are merged into the newest-first list. |
| Live Monitoring | `LiveCanvas` or authenticated MJPEG `<img>`, `Badge`, `EvidenceImage`, `Panel`, `Modal` | Camera list and status errors can be retried; camera status polls every 5 seconds while visible; socket alerts update the list. FPS, tracked vehicles and structured pass state are unavailable from the backend. |
| Violation Management | `FilterBar`, `DataTable`, `Pagination`, `Badge`, `EvidenceImage`, `ViolationDetailDrawer` | Filters live in the URL; the drawer shows evidence, original AI result, review history where available, and role-gated review controls. |
| Analytics & Reports | Recharts line/bar/donut charts in `ResponsiveContainer`, `DataTable`, `Panel` | Daily, summary and camera-stat data areas show loading/error/empty states; CSV export reports errors and downloads authenticated data. |
| Camera Management | `DataTable`, `CameraForm`, `ZoneEditor`, `ConfirmDialog`, `ErrorBox` | Camera fetch and mutations report errors; snapshot/zone editing has loading, empty and error states. Admin-only controls are hidden from other roles. |
| Settings & Administration | settings tabs, `DataTable`, `ConfirmDialog`, `Modal`, `ErrorBox` | User/settings/health data show loading/error/empty states. Unsupported threshold and storage/database controls say “Not available yet.” |

The frontend tests cover permission rules, badge labels, compliance and formatting utilities, zone coordinate conversion, URL filters, protected routing, viewer review-button visibility, API mock-error states, alert socket reconnect/cap behavior, and polling visibility/cleanup. Run `npm test`, `npm run lint`, and `npm run build` from `frontend/`.

## Stage 9 limits

- Mock mode is the default. Its demo accounts, generated evidence and alerts are for local UI review only.
- Real mode has not been validated against a running backend in this stage; no AI engine was started.
- The API's daily stats are filtered in the browser for chart date ranges; other summary totals cover all available dates.
- The violation list UI loads at most 500 matching rows before local pagination; refine filters to reach older results.
- MJPEG requires a token in the stream URL because an `<img>` request cannot attach an Authorization header. Evidence uses authenticated blob fetches instead.
- RTSP passwords are masked in responses and are not prefilled in the edit form.
- Browser-side upload progress is available, but backend video-processing progress is not.
- UI role checks are for usability; the backend remains responsible for authorization.

