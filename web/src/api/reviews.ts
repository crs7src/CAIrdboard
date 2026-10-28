import { failure } from './client'

export type ReviewState = 'running' | 'clean' | 'fixed' | 'failed'

export interface Review {
  // The AI that ran it; null when none was used.
  provider?: string | null
  card_key: string
  version: number
  implementation_version: number
  state: ReviewState
  branch: string | null
  base_commit: string | null
  head_before: string | null
  fix_commits: { sha: string; subject: string }[]
  notes: string[]
  report: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export async function fetchReview(key: string): Promise<Review | null> {
  const response = await fetch(`/api/cards/${key}/review`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function startReview(key: string): Promise<Review> {
  const response = await fetch(`/api/cards/${key}/review`, { method: 'POST' })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchReviewStates(): Promise<Record<string, ReviewState>> {
  const response = await fetch('/api/reviews')
  if (!response.ok) throw await failure(response)
  return response.json()
}
