# CAIrdboard

A local web app that shows the Jira cards and GitHub issues assigned to you and drives an AI workflow for each one:

1. **Plan** – an AI writes a plan for the card; you review and approve it.
2. **Implement** – a second AI follows the approved plan on a new branch, one commit per step.
3. **Review** – a third AI code-reviews the result and fixes real issues.
4. **Test** – an AI works out how to run the app locally; the server starts it and links to the parts to test by hand.
5. **Merge request** – push the branch and open a GitLab merge request or GitHub pull request.

Everything runs on your machine. The browser never holds credentials or runs commands.

## How it works

- **Frontend** (`web/`): React, React Router, TypeScript, Vite and MUI.
- **Backend** (`server/`): FastAPI. It is the only layer that talks to Jira, GitHub and GitLab and that spawns the AI CLIs.
- **Storage**: a SQLite file and settings files in `server/data/`.

## Prerequisites

- Node.js and npm
- Python 3.15 or later (see `server/pyproject.toml`)
- [uv](https://docs.astral.sh/uv/)
- git
- An AI provider: the [Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli) (the default) or an Anthropic/Gemini API key. Implement, review and feedback steps always use Copilot.
- Credentials for the services you use: Jira (email + API token), GitHub token, GitLab token.

## Setup

```
npm install
cd web && npm install && cd ..
cd server && uv sync && cd ..
cp server/.env.example server/.env   # optional
```

Credentials can go in `server/.env` or be entered in the UI under **Settings**; see `server/.env.example` for the variables.

For end-to-end tests only: `cd web && npx playwright install chromium`.

## Run

```
npm run dev     # development: API on http://127.0.0.1:6100, UI on http://localhost:6101
npm start       # build the UI, then run the API and a preview of the built UI
```

Open http://localhost:6101.

## First-time configuration

1. Connect Jira, GitHub and/or GitLab under **Settings**.
2. On the **Projects** page, map each project to a local repository.
3. Optionally pick an AI provider and the eligible card statuses under **Settings → AI**.
4. Save the test-app settings per project (**Settings → Test apps**) so manual testing can start the app.

## Development

```
npm run lint       # oxlint + ruff
npm test           # vitest + pytest
npm run test:e2e   # Playwright (starts the API and UI itself)
npm run build
```

See [`.github/copilot-instructions.md`](.github/copilot-instructions.md) for architecture details and conventions.

## Security notes

- `server/.env` and `server/data/` are gitignored. Saved tokens are stored with file mode 0600 and never returned by the API.
- The app is intended for local use only; do not expose it to a network.
