import { failure, json } from './client'

export type AiProviderId = 'copilot' | 'anthropic' | 'gemini'

export interface AiProvider {
  id: AiProviderId
  label: string
  configured: boolean
  model: string | null
  default_model: string | null
  models: string[]
  needs_key: boolean
  is_default: boolean
  supports_agent: boolean
}

export interface AiProviderUpdate {
  api_key?: string
  model?: string
}

export const AI_PROVIDER_LABELS: Record<AiProviderId, string> = {
  copilot: 'GitHub Copilot CLI',
  anthropic: 'Anthropic',
  gemini: 'Google Gemini',
}

export async function fetchAiProviders(): Promise<AiProvider[]> {
  const response = await fetch('/api/ai/providers')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function saveAiProvider(id: AiProviderId, update: AiProviderUpdate): Promise<AiProvider> {
  const response = await fetch(`/api/ai/providers/${id}/credentials`, json('PUT', update))
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function removeAiProviderKey(id: AiProviderId): Promise<AiProvider> {
  const response = await fetch(`/api/ai/providers/${id}/credentials`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function checkAiProvider(id: AiProviderId): Promise<void> {
  const response = await fetch(`/api/ai/providers/${id}/check`)
  if (!response.ok) throw await failure(response)
}

export async function setDefaultAiProvider(provider: AiProviderId): Promise<void> {
  const response = await fetch('/api/ai/default', json('PUT', { provider }))
  if (!response.ok) throw await failure(response)
}
