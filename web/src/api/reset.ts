import { failure } from './client'

export interface ResetResult {
  branch: string | null
  branch_deleted: boolean
  deleted_sha: string | null
  notes: string[]
}

export async function resetCard(key: string, deleteBranch = true): Promise<ResetResult> {
  const response = await fetch(`/api/cards/${key}/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ delete_branch: deleteBranch }),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function dismissReopenPrompt(key: string): Promise<void> {
  const response = await fetch(`/api/cards/${key}/reopen-prompt/dismiss`, { method: 'PUT' })
  if (!response.ok) throw await failure(response)
}
