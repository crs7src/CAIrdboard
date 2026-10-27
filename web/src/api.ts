export async function fetchHello(): Promise<string> {
  const response = await fetch('/api/hello')
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`)
  }
  const data: { message: string } = await response.json()
  return data.message
}

export interface Card {
  key: string
  summary: string
  status: string
  priority: string | null
  url: string
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
