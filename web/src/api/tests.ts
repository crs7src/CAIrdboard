import { failure } from './client'

export type TestState = 'preparing' | 'running' | 'stopped' | 'failed'

export interface TestRun {
  card_key: string
  version: number
  review_version: number | null
  state: TestState
  source: 'ai' | 'saved' | 'feedback'
  problem: string | null
  branch: string | null
  apps: { name: string; start_command: string; workdir: string; ready_url: string; ready_timeout_seconds?: number | null }[]
  links: { title: string; url: string; check: string }[]
  notes: string[]
  report: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export async function fetchTest(key: string): Promise<TestRun | null> {
  const response = await fetch(`/api/cards/${key}/test`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function startTest(key: string, useAi = false): Promise<TestRun> {
  const response = await fetch(
    `/api/cards/${key}/test`,
    useAi
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ use_ai: true }) }
      : { method: 'POST' },
  )
  if (!response.ok) throw await failure(response)
  return response.json()
}

export interface TestConfig {
  project: string
  apps: TestRun['apps']
  saved_from: string
  saved_at: string
}

export async function fetchTestConfig(key: string): Promise<TestConfig | null> {
  const response = await fetch(`/api/cards/${key}/test/config`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export type TestApp = TestRun['apps'][number]

export interface TestApproval {
  approved: boolean
  approved_at: string | null
}

export async function fetchTestApproval(key: string): Promise<TestApproval> {
  const response = await fetch(`/api/cards/${key}/test/approval`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function setTestApproval(key: string, approved: boolean): Promise<TestApproval> {
  const response = await fetch(`/api/cards/${key}/test/approval`, { method: approved ? 'PUT' : 'DELETE' })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchTestApprovals(): Promise<string[]> {
  const response = await fetch('/api/test-approvals')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchConfiguredTestProjects(): Promise<string[]> {
  const response = await fetch('/api/test-configs')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchProjectTestConfig(project: string): Promise<TestConfig | null> {
  const response = await fetch(`/api/test-configs/${project}`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function saveProjectTestConfig(project: string, apps: TestApp[]): Promise<TestConfig> {
  const response = await fetch(`/api/test-configs/${project}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ apps }),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function clearProjectTestConfig(project: string): Promise<void> {
  const response = await fetch(`/api/test-configs/${project}`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
}

export async function forgetTestConfig(key: string): Promise<void> {
  const response = await fetch(`/api/cards/${key}/test/config`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
}

export async function reportTestProblem(key: string, message: string): Promise<TestRun> {
  const response = await fetch(`/api/cards/${key}/test/problem`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function stopTest(key: string): Promise<TestRun> {
  const response = await fetch(`/api/cards/${key}/test`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchTestStates(): Promise<Record<string, TestState>> {
  const response = await fetch('/api/tests')
  if (!response.ok) throw await failure(response)
  return response.json()
}
