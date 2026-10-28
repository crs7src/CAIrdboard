import { failure } from './client'

export type RepoProvider = 'gitlab' | 'github'

export interface HostStatus {
  configured: boolean
  connected: boolean
  user: string | null
  url: string
}

export interface HostCredentialsUpdate {
  url?: string
  token?: string
}

export interface RepoHostInfo {
  project: string
  repo: string
  provider: RepoProvider | null
  path: string | null
  source: 'override' | 'origin' | null
  detected: { provider: RepoProvider; path: string } | null
}

export interface RepoHostCheck {
  provider: RepoProvider
  path: string
  web_url: string
  default_branch: string | null
}

export async function fetchHostStatus(provider: RepoProvider): Promise<HostStatus> {
  const response = await fetch(`/api/${provider}/status`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function saveHostCredentials(
  provider: RepoProvider,
  update: HostCredentialsUpdate,
): Promise<{ user: string }> {
  const response = await fetch(`/api/${provider}/credentials`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchRepoHosts(): Promise<RepoHostInfo[]> {
  const response = await fetch('/api/repo-hosts')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchRepoHost(project: string): Promise<RepoHostInfo> {
  const response = await fetch(`/api/repo-hosts/${project}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function setRepoHost(
  project: string,
  mapping: { provider: RepoProvider; path: string } | null,
): Promise<RepoHostInfo> {
  const response = await fetch(
    `/api/repo-hosts/${project}`,
    mapping === null
      ? { method: 'DELETE' }
      : {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(mapping),
        },
  )
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function checkRepoHost(project: string): Promise<RepoHostCheck> {
  const response = await fetch(`/api/repo-hosts/${project}/check`)
  if (!response.ok) throw await failure(response)
  return response.json()
}
