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
