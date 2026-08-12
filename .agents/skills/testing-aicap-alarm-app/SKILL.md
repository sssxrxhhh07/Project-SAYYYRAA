---
name: testing-aicap-alarm-app
description: How to run and end-to-end test the AICAP alarm app (FastAPI backend + vanilla-JS SPA) locally — which server to start, which frontend is the real API client, how to log in, and how to trigger the ringing/snooze/dismiss overlay.
---

# Testing the AICAP alarm app locally

## Two frontends — pick the right one
- `AICAP-Frontend/` is the **real API-connected SPA** (`js/api.js` → `API_BASE_URL` defaults to `http://localhost:8000`). All auth + alarm CRUD testing must happen here.
- `AICAP-Backend/templates/index.html` is a **self-contained localStorage demo** (client-side PBKDF2 "users" table); it does NOT call the API. The backend SPA routes (`/`, `/login`, `/register`, `/dashboard`, `/dashboard/{path}`) only serve this shell, so use them solely to check "renders HTML 200, no 500".

## Start the services
```bash
# Backend — MUST run from AICAP-Backend/ (top-level absolute imports + Jinja2Templates(directory="templates"))
cd AICAP-Backend && DATABASE_URL=sqlite:////tmp/test_sayraa.db \
  ~/venv-sayraa/bin/uvicorn main:app --port 8000 --host 127.0.0.1 > /tmp/uvicorn.log 2>&1 &

# Frontend — any static server on a different port
cd AICAP-Frontend && python3 -m http.server 5500 &
```
- `AICAP-Backend/.env` points `DATABASE_URL` at a local Postgres that is usually **not running** on Devin boxes — always override with SQLite as above, otherwise every request 500s.
- Google OAuth cannot work locally (no valid redirect URI): use local email/password auth only.
- Keep `/tmp/uvicorn.log` and grep it for `500`/`Traceback` after each UI action — the SPA masks backend 500s as a generic "Lost connection. Retrying…" toast, so the log is the only place the real error shows up.

## Auth in the UI (http://localhost:5500/index.html)
- "Sign up" tab → Name / Email / Password (min 8) / Confirm / role "Just for me" (→ backend `USER`) → "Create account" auto-logs in and routes to the USER dashboard.
- Do NOT use the landing page's "Skip for testing" button — it fakes a JWT (`main.js:skipForTesting`) and every API call then 401s. (Worth flagging to the user: this button ships in the production UI.)
- A "Turn on notifications" prompt overlays the bottom-center of the page and can swallow clicks on the modal's submit button — click "Not now" first.
- Time inputs are `<input type="time">`: type `07:15AM` / `04:08PM` (with AM/PM) to fill them reliably.

## Triggering the ringing overlay (needed for snooze/dismiss)
`js/alarm-audio.js:AlarmMonitor` polls `GET /alarms/today` every second and fires only when `alarm.alarm_time === current HH:MM` **and** `seconds < 5`. To test:
1. Edit an alarm's time to the *next* upcoming minute of the box clock (`date +%H:%M:%S`).
2. Stay on the Alarms view and wait until the top of that minute; the `#alarmTriggerOverlay` ("Alarm Ringing!") appears with "I'm up" / "Snooze".
3. After Snooze/Dismiss the card is **not** auto-refreshed — click another sidebar item and back (or reload) to see the server state (snooze = time +5 min; dismiss = alarm disabled).

## Known/possible bugs to watch for (verified once; may still be present)
- `DELETE /alarms/{id}` returns **500** (`NOT NULL constraint failed: alarm_events.alarm_id`) for any alarm that has snooze/dismiss history: `AlarmEvent.alarm_id` is `nullable=False` with DB-level `ondelete="CASCADE"`, but SQLAlchemy's default ORM behaviour nulls the FK instead (no `cascade="all, delete-orphan"` on the `Alarm.events` backref, and SQLite FK enforcement is off). Workaround for testing: delete only alarms that never rang.
- `snooze_minutes` / `seconds_to_dismiss` are declared as scalar params on the endpoints, so FastAPI binds them as **query** params while the frontend sends them in a JSON body → the sent values are ignored and defaults (5 min / 0 s) are used.
- Clicking "Sign out" shows the toast but leaves the dashboard rendered when the hash is already `#/` (no re-route); reload to reach the landing page.

## Backend unit tests
```bash
cd AICAP-Backend && ~/venv-sayraa/bin/python -m pytest --cov --cov-report=term-missing
```
Uses a throwaway SQLite DB via `tests/conftest.py`; no `.env` needed.

## Devin Secrets Needed
None — local email/password auth is sufficient; Google OAuth is untestable locally.
