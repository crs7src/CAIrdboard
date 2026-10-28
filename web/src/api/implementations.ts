import { failure } from './client'

export async function fetchImplementationStates(): Promise<Record<string, ImplState>> {
  const response = await fetch('/api/implementations')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export type ImplState = 'running' | 'completed' | 'failed'

export interface Implementation {
  card_key: string
  version: number
  plan_version: number
  state: ImplState
  stage: 'preparing' | 'implementing' | 'done'
  branch: string | null
  base_branch: string | null
  base_commit: string | null
  commits: { sha: string; subject: string }[]
  notes: string[]
  report: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export async function fetchImplementation(key: string): Promise<Implementation | null> {
  const response = await fetch(`/api/cards/${key}/implementation`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function startImplementation(key: string): Promise<Implementation> {
  const response = await fetch(`/api/cards/${key}/implementation`, { method: 'POST' })
  if (!response.ok) throw await failure(response)
  return response.json()
}
