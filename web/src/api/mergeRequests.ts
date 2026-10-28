import { failure } from './client'
import type { RepoProvider } from './hosts'

export type MergeRequestState = 'running' | 'created' | 'failed'

export interface MergeRequest {
  card_key: string
  version: number
  state: MergeRequestState
  branch: string
  target_branch: string
  title: string
  description: string | null
  provider: RepoProvider
  host_project: string
  mr_iid: number | null
  mr_url: string | null
  updated_existing: boolean
  outdated: boolean
  error: string | null
}

export async function fetchMergeRequest(key: string): Promise<MergeRequest | null> {
  const response = await fetch(`/api/cards/${key}/merge-request`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export interface MergeRequestDefaults {
  title: string
  description: string
}

export async function fetchMergeRequestDefaults(key: string): Promise<MergeRequestDefaults> {
  const response = await fetch(`/api/cards/${key}/merge-request/defaults`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function startMergeRequest(key: string, edits?: Partial<MergeRequestDefaults>): Promise<MergeRequest> {
  const response = await fetch(
    `/api/cards/${key}/merge-request`,
    edits
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(edits) }
      : { method: 'POST' },
  )
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchMergeRequestUrls(): Promise<Record<string, string>> {
  const response = await fetch('/api/merge-requests/urls')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchMergeRequestStates(): Promise<Record<string, MergeRequestState | 'outdated'>> {
  const response = await fetch('/api/merge-requests')
  if (!response.ok) throw await failure(response)
  return response.json()
}
