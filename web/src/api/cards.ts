import { failure } from './client'

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

export interface CardDetail extends Card {
  eligible: boolean
  repo_configured: boolean
}

export async function fetchCardDetail(key: string): Promise<CardDetail> {
  const response = await fetch(`/api/cards/${key}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}
