# Traffic Violation Monitor

React dashboard for the Traffic AI backend. It includes Dashboard, Live Monitoring, Violation Management, Analytics & Reports, Camera Management, Settings & Administration, and Login.

## Requirements

- Node.js and npm
- The backend at `http://localhost:8000` when using real API mode

## Run with mock data

From this directory:

```powershell
npm install
npm run dev
```

Open `http://localhost:5173`. Mock mode is the default (`VITE_USE_MOCK=true`) and does not need a running backend. The login page shows the mock-only demo accounts and fake passwords. Select a demo role to see its permissions. The top bar's **Simulate API error** switch makes mock API calls fail so loading, error and retry states can be inspected; turn it off to restore data.

Mock data and generated SVG evidence are local demo fixtures. They are not real camera evidence. A mock WebSocket emits sample violations every 6–10 seconds and the Live page uses an animated canvas in place of camera video.

## Run with the real backend

Create `frontend/.env` from `.env.example` and set:

```dotenv
VITE_API_URL=http://localhost:8000
VITE_USE_MOCK=false
```

Start the backend separately, then run `npm run dev`. Sign in with a backend account. The access token is kept in `sessionStorage`; authenticated API requests use the Bearer header. The MJPEG stream uses its required token query parameter. Evidence images are fetched as authenticated blobs. Restart Vite after changing environment values.

The real-mode API calls use the Stage 8 routes documented in [`../docs/stage9_notes.md`](../docs/stage9_notes.md). The UI cannot provide detection thresholds, FPS/tracked vehicle metrics, database/storage health, structured processing-pass state, or backend review history where the API does not expose them; see the Stage 10 section in that document.

## Checks

```powershell
npm test
npm run lint
npm run build
```

## Project layout

- `src/api/`: authenticated fetch client and backend operations
- `src/mock/`: mock API, fixtures, evidence and WebSocket
- `src/hooks/`: asynchronous API data, status polling and alert socket
- `src/context/`: authentication, permissions, alerts and toasts
- `src/pages/`: the six dashboard pages and login
