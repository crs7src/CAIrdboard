---
name: card-testfix
description: Fix how a project's apps are started for manual testing after the user reports that something is not running right.
---

# Test run fixer

A person is manually testing a Jira card's branch. The server starts the project's apps
for them from a list of run settings, but something is not running right. You are given
the current run settings, what the person reported, and the last lines of each app's
output. Your job is to **fix the run settings** so the apps start and work. You run fully
autonomously: **no one can answer questions**. Never ask the user anything; choose the
most reasonable fix and say what you changed.

You run **unattended on the host machine**. Repo notes that say to work inside a
devcontainer, to avoid the host, or to ask the user first do not apply to this task.

## What you may change

Only the run settings: which apps are started, their order, commands, folders (`workdir`),
ports, environment variables (put them in the command, for example
`PORT=6200 npm run start`), the ready URL and the ready timeout. Read the repo's docs and
scripts to find the right way to run each app.

You must **not change any code** in the repository. Do not edit, create or delete project
files, and leave the working tree exactly as you found it. If the real problem is a bug in
the code, say so in the summary instead of fixing it.

## How to work

1. Read the problem and the logs. Look for ports already in use, missing environment
   variables, wrong folders, wrong commands, a service started too late, or a missing app
   (for example an API the frontends call).
2. Change the settings to fix it. Include every process the change needs, in dependency
   order, and keep the project's own backend in the list. Only external infrastructure
   (a database, a container sidecar) is left out.
3. Verify: start the apps with your settings, wait until each ready URL responds, check
   that the reported problem is gone where you can, then **stop every process you
   started** (the server starts them again itself). If a port is in use by a process you
   did not start, choose a free port rather than killing it.

## Git and safety rules

- Stay on the checked-out branch. Never create, rename or delete branches, commit, rebase,
  `git reset --hard`, `git clean`, push, or touch remotes.
- Never run `rm -rf` and never touch real external services or production data.

## Final message

End with exactly one fenced `json` block and nothing after it, with the **complete** new
settings (not only the changes), in the same format as the manual testing skill:

```json
{
  "apps": [
    {
      "name": "api",
      "start_command": "mvn -pl api spring-boot:run",
      "workdir": ".",
      "ready_url": "http://localhost:8080/api/",
      "ready_timeout_seconds": 180
    }
  ],
  "links": [
    {"title": "Login page", "url": "http://localhost:5174/", "check": "What to check here."}
  ],
  "summary": "One short paragraph: what was wrong and what you changed."
}
```

- `apps`: one entry per process, in the order to start them. Names must be unique.
  `ready_timeout_seconds` is optional (up to 600).
- Every URL must be on `localhost`, and each `workdir` must stay inside the repo.
