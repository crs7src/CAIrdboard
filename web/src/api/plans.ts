import { failure } from './client'

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
