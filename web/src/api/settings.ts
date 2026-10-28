import { failure } from './client'

export interface AiConfig {
  eligible_statuses: string[]
  project_repos: Record<string, string>
  auto_review: boolean
}

export interface DirListing {
  path: string
  parent: string | null
  dirs: { name: string; is_git: boolean }[]
}

export async function fetchDirs(path?: string): Promise<DirListing> {
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  const response = await fetch(`/api/fs/dirs${query}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchAiConfig(): Promise<AiConfig> {
  const response = await fetch('/api/ai-config')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function saveAiConfig(config: AiConfig): Promise<AiConfig> {
  const response = await fetch('/api/ai-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export interface Skill {
  step: 'planner' | 'implementer' | 'reviewer' | 'feedback' | 'tester' | 'testfix'
  content: string
  default_content: string
  customized: boolean
}

export async function fetchSkills(): Promise<Skill[]> {
  const response = await fetch('/api/skills')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function saveSkill(step: string, content: string): Promise<Skill> {
  const response = await fetch(`/api/skills/${step}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function resetSkill(step: string): Promise<Skill> {
  const response = await fetch(`/api/skills/${step}`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
  return response.json()
}
