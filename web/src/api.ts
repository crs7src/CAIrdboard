export interface Card {
  key: string
  summary: string
  status: string
  priority: string | null
  url: string
  project: string
  description: string
}

export async function fetchCards(): Promise<Card[]> {
  const response = await fetch('/api/cards')
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed: ${response.status}`)
  }
  return response.json()
}

export interface JiraStatus {
  configured: boolean
  connected: boolean
  user: string | null
  base_url: string
  email: string
}

export async function fetchJiraStatus(): Promise<JiraStatus> {
  const response = await fetch('/api/jira/status')
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  return response.json()
}

export interface CredentialsUpdate {
  base_url?: string
  email?: string
  token?: string
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((d) => d?.msg ?? 'Invalid input').join('; ')
  }
  return `Request failed: ${status}`
}

export async function saveJiraCredentials(update: CredentialsUpdate): Promise<{ user: string }> {
  const response = await fetch('/api/jira/credentials', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(errorMessage(body?.detail, response.status))
  }
  return response.json()
}

async function failure(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null)
  return new Error(errorMessage(body?.detail, response.status))
}

export interface CardDetail extends Card {
  eligible: boolean
  repo_configured: boolean
}

export async function fetchCardDetail(key: string): Promise<CardDetail> {
  const response = await fetch(`/api/cards/${key}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export interface AiConfig {
  eligible_statuses: string[]
  project_repos: Record<string, string>
}

export interface DirListing {
  path: string
  parent: string | null
  dirs: { name: string; is_git: boolean }[]
}

export async function fetchDirs(path?: string): Promise<DirListing> {
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  const response = await fetch(`/api/fs/dirs${query}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchAiConfig(): Promise<AiConfig> {
  const response = await fetch('/api/ai-config')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function saveAiConfig(config: AiConfig): Promise<AiConfig> {
  const response = await fetch('/api/ai-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export type PlanState = 'running' | 'ready' | 'failed' | 'approved' | 'rejected'

export interface Plan {
  card_key: string
  version: number
  state: PlanState
  jira_status: string
  feedback: string | null
  plan: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export async function fetchPlanStates(): Promise<Record<string, PlanState>> {
  const response = await fetch('/api/plans')
  if (!response.ok) throw await failure(response)
  return response.json()
}

/** Returns null when the card has no plan yet. */
export async function fetchPlan(key: string): Promise<Plan | null> {
  const response = await fetch(`/api/cards/${key}/plan`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function generatePlan(key: string, feedback?: string): Promise<Plan> {
  const response = await fetch(`/api/cards/${key}/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback: feedback?.trim() || null }),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function decidePlan(key: string, decision: 'approve' | 'reject'): Promise<Plan> {
  const response = await fetch(`/api/cards/${key}/plan/${decision}`, { method: 'POST' })
  if (!response.ok) throw await failure(response)
  return response.json()
}
