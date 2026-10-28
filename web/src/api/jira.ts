import { errorMessage } from './client'

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
