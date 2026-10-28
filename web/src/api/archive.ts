import { failure } from './client'

export async function fetchArchive(): Promise<string[]> {
  const response = await fetch('/api/archive')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function archiveCard(key: string): Promise<void> {
  const response = await fetch(`/api/cards/${key}/archive`, { method: 'PUT' })
  if (!response.ok) throw await failure(response)
}

export async function unarchiveCard(key: string): Promise<void> {
  const response = await fetch(`/api/cards/${key}/archive`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
}
