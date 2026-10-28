export interface Comment {
  author: string
  created: string
  body: string
  after_reopen: boolean
}

export interface StatusChange {
  from_status: string
  to_status: string
  when: string
  author: string
}

export interface Card {
  key: string
  summary: string
  status: string
  priority: string | null
  url: string
  project: string
  description: string
  comments: Comment[]
  status_history: StatusChange[]
  reopened: boolean
  last_reopened_at: string | null
  source?: 'jira' | 'github'
  external_repo?: string | null
}

export interface CardList {
  cards: Card[]
  // Set when one source (Jira or GitHub) failed while another worked.
  warning: string | null
}

export async function fetchCardList(): Promise<CardList> {
  const response = await fetch('/api/cards')
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed: ${response.status}`)
  }
  return { cards: await response.json(), warning: response.headers?.get('X-Card-Warnings') ?? null }
}

export async function fetchCards(): Promise<Card[]> {
  return (await fetchCardList()).cards
}

export interface JiraStatus {
  configured: boolean
  connected: boolean
  user: string | null
  base_url: string
  email: string
}

export async function fetchJiraStatus(): Promise<JiraStatus> {
  const response = await fetch('/api/jira/status')
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  return response.json()
}

export interface CredentialsUpdate {
  base_url?: string
  email?: string
  token?: string
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((d) => d?.msg ?? 'Invalid input').join('; ')
  }
  return `Request failed: ${status}`
}

export async function saveJiraCredentials(update: CredentialsUpdate): Promise<{ user: string }> {
  const response = await fetch('/api/jira/credentials', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(errorMessage(body?.detail, response.status))
  }
  return response.json()
}

async function failure(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null)
  return new Error(errorMessage(body?.detail, response.status))
}

export interface CardDetail extends Card {
  eligible: boolean
  repo_configured: boolean
}

export async function fetchCardDetail(key: string): Promise<CardDetail> {
  const response = await fetch(`/api/cards/${key}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

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

export type PlanState = 'running' | 'ready' | 'failed' | 'approved' | 'rejected'

export interface Plan {
  card_key: string
  version: number
  state: PlanState
  jira_status: string
  feedback: string | null
  plan: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export async function fetchImplementationStates(): Promise<Record<string, ImplState>> {
  const response = await fetch('/api/implementations')
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchPlanStates(): Promise<Record<string, PlanState>> {
  const response = await fetch('/api/plans')
  if (!response.ok) throw await failure(response)
  return response.json()
}

/** Returns null when the card has no plan yet. */
export async function fetchPlan(key: string): Promise<Plan | null> {
  const response = await fetch(`/api/cards/${key}/plan`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function generatePlan(key: string, feedback?: string): Promise<Plan> {
  const response = await fetch(`/api/cards/${key}/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback: feedback?.trim() || null }),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function decidePlan(key: string, decision: 'approve' | 'reject'): Promise<Plan> {
  const response = await fetch(`/api/cards/${key}/plan/${decision}`, { method: 'POST' })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export type ImplState = 'running' | 'completed' | 'failed'

export interface Implementation {
  card_key: string
  version: number
  plan_version: number
  state: ImplState
  stage: 'preparing' | 'implementing' | 'done'
  branch: string | null
  base_branch: string | null
  base_commit: string | null
  commits: { sha: string; subject: string }[]
  notes: string[]
  report: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export async function fetchImplementation(key: string): Promise<Implementation | null> {
  const response = await fetch(`/api/cards/${key}/implementation`)
  if (response.status === 404) return null
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function startImplementation(key: string): Promise<Implementation> {
  const response = await fetch(`/api/cards/${key}/implementation`, { method: 'POST' })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export type ReviewState = 'running' | 'clean' | 'fixed' | 'failed'

export interface Review {
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

export interface FeedbackCommentInput {
  text: string
  file?: string | null
  line?: number | null
  side?: 'new' | 'old'
  code?: string | null
  origin?: 'review' | 'testing'
}

export interface FeedbackComment {
  id: string
  text: string
  file: string | null
  line: number | null
  side: 'new' | 'old'
  code: string | null
  origin: 'review' | 'testing'
  status: 'pending' | 'resolved'
  resolved_in: number | null
  created_at: string
}

export interface FeedbackRun {
  card_key: string
  version: number
  state: 'running' | 'done' | 'failed'
  branch: string | null
  comments: FeedbackComment[]
  commits: { sha: string; short: string; subject: string }[]
  notes: string[]
  report: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface Feedback {
  comments: FeedbackComment[]
  run: FeedbackRun | null
}

export async function fetchFeedback(key: string): Promise<Feedback> {
  const response = await fetch(`/api/cards/${key}/feedback`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function addFeedbackComment(
  key: string,
  input: FeedbackCommentInput,
): Promise<FeedbackComment> {
  const response = await fetch(`/api/cards/${key}/feedback/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function editFeedbackComment(
  key: string,
  id: string,
  text: string,
): Promise<FeedbackComment> {
  const response = await fetch(`/api/cards/${key}/feedback/comments/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function deleteFeedbackComment(key: string, id: string): Promise<void> {
  const response = await fetch(`/api/cards/${key}/feedback/comments/${id}`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
}

export async function submitFeedback(key: string): Promise<FeedbackRun> {
  const response = await fetch(`/api/cards/${key}/feedback/submit`, { method: 'POST' })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function submitTestFeedback(key: string, message: string): Promise<FeedbackRun> {
  const response = await fetch(`/api/cards/${key}/test/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

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

export type MergeRequestState = 'running' | 'created' | 'failed'

export interface MergeRequest {
  card_key: string
  version: number
  state: MergeRequestState
  branch: string
  target_branch: string
  title: string
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

export async function startMergeRequest(key: string): Promise<MergeRequest> {
  const response = await fetch(`/api/cards/${key}/merge-request`, { method: 'POST' })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export async function fetchMergeRequestStates(): Promise<Record<string, MergeRequestState | 'outdated'>> {
  const response = await fetch('/api/merge-requests')
  if (!response.ok) throw await failure(response)
  return response.json()
}

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
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

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
