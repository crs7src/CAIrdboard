import { failure, json } from './client'
import type { AiProviderId } from './ai'
import type { RepoHostInfo, RepoProvider } from './hosts'

export interface SetupItem {
  id: string
  label: string
  done: boolean
}

export interface ProjectCard {
  key: string
  summary: string
  status: string
  source: string
  url: string
  eligible: boolean
  plan_state: string | null
  implementation_state: string | null
  review_state: string | null
  test_state: string | null
}

export interface Project {
  key: string
  name: string
  repo_path: string
  repo_exists: boolean
  jira: boolean
  host: RepoHostInfo
  jira_connected: boolean
  gitlab_connected: boolean
  github_connected: boolean
  test_apps_configured: boolean
  ai_provider: AiProviderId | null
  effective_ai_provider: AiProviderId
  status: SetupItem[]
  // Only present on the single-project endpoint.
  cards: ProjectCard[] | null
  card_warnings: string | null
}

export interface ProjectInput {
  name: string
  repo_path: string
  key?: string | null
  jira_enabled: boolean
  provider?: RepoProvider | null
  host_path?: string | null
  ai_provider?: AiProviderId | null
}

export async function fetchProjects(): Promise<Project[]> {
  const response = await fetch('/api/projects')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchProject(key: string): Promise<Project> {
  const response = await fetch(`/api/projects/${key}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function createProject(input: ProjectInput): Promise<Project> {
  const response = await fetch('/api/projects', json('POST', input))
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function updateProject(key: string, input: ProjectInput): Promise<Project> {
  const response = await fetch(`/api/projects/${key}`, json('PUT', input))
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function deleteProject(key: string): Promise<void> {
  const response = await fetch(`/api/projects/${key}`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
}
