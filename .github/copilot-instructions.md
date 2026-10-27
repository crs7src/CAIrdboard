# Copilot Instructions

## Purpose

A local web app that shows the JIRA cards assigned to the user and drives a three-stage AI workflow per card:

1. **Plan** – button triggers an AI to write a plan for the card; the user reviews/approves it.
2. **Implement** – button triggers a second AI to follow the approved plan.
3. **Review** – a third AI performs code review on the result.

## Architecture

- **Frontend**: React + React Router + TypeScript (Vite) in `web/`, styled with MUI (dark theme in `web/src/theme.ts`, shell/nav in `web/src/Layout.tsx`). API calls go through `web/src/api.ts`; the Vite dev server proxies `/api` to the backend at `127.0.0.1:8000`.
- **Backend**: local Python server (FastAPI + uvicorn) in `server/`. It runs on the user's machine and is the only layer that talks to JIRA and spawns the local AI CLI commands (via `asyncio.create_subprocess_exec`). The browser never executes commands or holds JIRA credentials.
- Flow: React UI → backend HTTP API → (JIRA REST API | spawned AI CLI processes). Long-running AI runs should stream/poll progress back to the UI (SSE or polling), and each stage's output (plan, implementation, review) should be persisted per card so stages can be gated on the previous one's approval.
- Keep the stages as separate backend modules/endpoints so each AI step is independently testable with the process runner mocked.
- **Jira** (Cloud, basic auth with email + API token): `server/app/jira.py` is the client; cards are fetched live from `/rest/api/3/search/jql` (`assignee = currentUser()`) on every `/api/cards` request, with no local storage. Config comes from `server/.env` (gitignored; copy `server/.env.example`) via `app/config.py`, read only by the backend. Site URL, email and token can all be set from the UI (`/settings` → `PUT /api/jira/credentials`, partial updates allowed, verified against Jira's `/myself` before saving). There is a single credential set (no user accounts), stored at `server/data/jira.json` (gitignored, mode 0600); saved values override `.env` per field and `get_settings()` re-reads them per request. The token is never returned by any endpoint. Unconfigured → 503, Jira failure → 502 (the UI shows the `detail`).
- Frontend and backend are separate toolchains. Generate TypeScript API types from FastAPI's OpenAPI spec (`openapi-typescript`) rather than hand-maintaining them.

## Commands

Root `package.json` orchestrates both projects (setup: `npm install` in both the root and `web/`, and `cd server && uv sync`). Playwright browsers: `cd web && npx playwright install chromium`.

```
npm run dev        # uvicorn (:8000, reload) + Vite concurrently
npm run build      # tsc -b && vite build (web/)
npm run lint       # oxlint (web) + ruff check + ruff format --check (server)
npm test           # vitest (web) + pytest (server)
npm run test:e2e   # Playwright; auto-starts uvicorn and Vite via webServer config
```

Single tests:

```
cd web && npx vitest run src/pages/Home.test.tsx
cd web && npx vitest run -t "test name"
cd server && uv run pytest tests/test_x.py::test_name
cd web && npx playwright test e2e/home.spec.ts
cd web && npx playwright test -g "test name"
```

Test tooling (frontend tests are `src/**/*.test.tsx`, e2e specs are `web/e2e/`; backend tests are `server/tests/`): Vitest + React Testing Library (`jsdom`) for the frontend, pytest (+ `respx` for mocking Jira, FastAPI `TestClient`; override settings with `app.dependency_overrides[get_settings]`, or set `JIRA_CREDENTIALS_FILE` to a tmp path via env when exercising the real file logic) for the backend, Playwright for e2e.

## Conventions

- **UI**: use MUI components (not raw HTML elements/custom CSS); style via the theme or `sx`. Layout props like `alignItems` go inside `sx` (not typed as direct props here). Inline status messages use `Alert`: only errors keep the default `role="alert"`; informational ones use `role="note"` so tests can target errors unambiguously.
- **Plan before changing**: when asked to make any modification to files, first present a plan of the changes and wait for the user to accept it before proceeding.
- **Unit tests** are required for all new functionality in both frontend and backend. "Functionality" means an input producing an expected output; pure UI styling does not need tests.
- **E2E tests** (Playwright) are required for the major functionality points of each feature.
- **Before finishing any request**, create/update the needed unit and e2e tests and run them to confirm they pass.
- **Tests must clean up after themselves**: leave no changes in the database or the app (use temp/isolated DBs, reset state in teardown, and never leave created cards/plans/runs behind).
- E2E tests mock backend endpoints with `page.route`.
- Tests must never call real JIRA or spawn real AI CLIs; mock/stub them (and use a fake process runner in e2e).

## Plan generation (per card)

- Only cards whose Jira status is in `eligible_statuses` (`server/data/ai_config.json`, editable at `/ai-settings`; default Backlog, Ready to Play, DEV In Progress, Merge Requested, To Do, In Progress) can get a plan; Testing/UAT/Prod cannot (API returns 409).
- `ai_config.json` also maps Jira project key → absolute repo path; the AI runs with that repo as cwd.
- `app/planner.py` runs `copilot -s -p <prompt> --available-tools view grep glob --allow-tool view grep glob` (read-only, no shell) as a background task. Plans are stored as `server/data/plans/<KEY>/<n>.json` (gitignored), states: `running` → `ready` → `approved`/`rejected`, or `failed`. Regenerating accepts optional user feedback and includes the previous plan in the prompt. `approved` is the hook for the future implement/review stages.
- Backend tests inject a `FakeRunner` via the `get_runner` dependency; frontend unit tests use `mockApi` from `web/src/test-utils.ts`; e2e mocks plan endpoints with `page.route`.
- Routes: `/cards/:key` (card detail + plan), `/ai-settings`.
