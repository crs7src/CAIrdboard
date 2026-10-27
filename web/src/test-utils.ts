import { vi } from 'vitest'

export interface Reply {
  status?: number
  body?: unknown
}

type Route = Reply | Reply[] | ((init?: RequestInit) => Reply)

/**
 * Stubs global fetch with per-endpoint replies, keyed by "METHOD /path"
 * (method defaults to GET when omitted). An array replies in order and then
 * keeps repeating its last element. Unknown endpoints answer 404.
 */
export function mockApi(routes: Record<string, Route>) {
  const counters = new Map<string, number>()
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const id = `${init?.method ?? 'GET'} ${url}`
    const route = routes[id] ?? routes[url]
    let reply: Reply = { status: 404, body: { detail: 'not found' } }
    if (typeof route === 'function') reply = route(init)
    else if (Array.isArray(route)) {
      const n = counters.get(id) ?? 0
      counters.set(id, n + 1)
      reply = route[Math.min(n, route.length - 1)]
    } else if (route) reply = route
    const status = reply.status ?? 200
    return { ok: status < 400, status, json: async () => reply.body }
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

export const card = (key: string, over: Record<string, unknown> = {}) => ({
  key,
  summary: `Summary ${key}`,
  status: 'To Do',
  priority: 'High',
  url: `https://x.atlassian.net/browse/${key}`,
  project: key.split('-')[0],
  description: `Description of ${key}`,
  comments: [],
  status_history: [],
  reopened: false,
  last_reopened_at: null,
  ...over,
})

export const plan = (over: Record<string, unknown> = {}) => ({
  card_key: 'AB-1',
  version: 1,
  state: 'ready',
  jira_status: 'To Do',
  feedback: null,
  plan: '## Steps\n\n1. Do the thing',
  error: null,
  created_at: 't',
  updated_at: 't',
  ...over,
})

export const implementation = (over: Record<string, unknown> = {}) => ({
  card_key: 'AB-1',
  version: 1,
  plan_version: 1,
  state: 'completed',
  stage: 'done',
  branch: 'AB-1_add_dark_mode',
  base_branch: 'main',
  base_commit: 'abc',
  commits: [],
  notes: [],
  report: null,
  error: null,
  created_at: 't',
  updated_at: 't',
  ...over,
})

export const review = (over: Record<string, unknown> = {}) => ({
  card_key: 'AB-1',
  version: 1,
  implementation_version: 1,
  state: 'clean',
  branch: 'AB-1_add_dark_mode',
  base_commit: 'abc',
  head_before: 'def',
  fix_commits: [],
  notes: [],
  report: null,
  error: null,
  created_at: 't',
  updated_at: 't',
  ...over,
})

export const testRun = (over: Record<string, unknown> = {}) => ({
  card_key: 'AB-1',
  version: 1,
  review_version: 1,
  state: 'running',
  source: 'ai',
  problem: null,
  branch: 'AB-1_add_dark_mode',
  apps: [{ name: 'web', start_command: 'npm run dev', workdir: '.', ready_url: 'http://localhost:5173/' }],
  links: [{ title: 'Settings page', url: 'http://localhost:5173/settings', check: 'Toggle dark mode' }],
  notes: [],
  report: null,
  error: null,
  created_at: 't',
  updated_at: 't',
  ...over,
})

export const SAMPLE_DIFF = `diff --git a/src/a.ts b/src/a.ts
index 111..222 100644
--- a/src/a.ts
+++ b/src/a.ts
@@ -1,3 +1,3 @@
 keep
-old line
+new line
 tail
diff --git a/src/new.ts b/src/new.ts
new file mode 100644
index 0000000..333
--- /dev/null
+++ b/src/new.ts
@@ -0,0 +1,2 @@
+one
+two
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
index 444..0000000
--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
`

export const changes = (over: Record<string, unknown> = {}) => ({
  branch: 'AB-1_add_dark_mode',
  base_commit: 'abc',
  commits: [
    { sha: 'aaaaaaa1111', short: 'aaaaaaa', subject: 'AB-1: step 1 - add toggle' },
    { sha: 'bbbbbbb2222', short: 'bbbbbbb', subject: 'AB-1: review fix - null check' },
  ],
  selected_commit: null,
  diff: SAMPLE_DIFF,
  ...over,
})

export const feedbackComment = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  text: `Comment ${id}`,
  file: null,
  line: null,
  side: 'new',
  code: null,
  status: 'pending',
  resolved_in: null,
  created_at: 'now',
  ...over,
})

export const feedbackRun = (over: Record<string, unknown> = {}) => ({
  card_key: 'AB-1',
  version: 1,
  state: 'running',
  branch: 'AB-1_add_dark_mode',
  comments: [],
  commits: [],
  notes: [],
  report: null,
  error: null,
  created_at: 'now',
  updated_at: 'now',
  ...over,
})
