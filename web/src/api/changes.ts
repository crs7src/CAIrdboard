import { failure } from './client'

export interface Changes {
  branch: string
  base_commit: string
  commits: { sha: string; short: string; subject: string }[]
  selected_commit: string | null
  diff: string
}

export async function fetchChanges(key: string, commit?: string): Promise<Changes> {
  const query = commit ? `?commit=${encodeURIComponent(commit)}` : ''
  const response = await fetch(`/api/cards/${key}/changes${query}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}
