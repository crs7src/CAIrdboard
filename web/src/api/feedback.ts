import { failure } from './client'

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
