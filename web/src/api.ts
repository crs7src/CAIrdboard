export async function fetchHello(): Promise<string> {
  const response = await fetch('/api/hello')
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`)
  }
  const data: { message: string } = await response.json()
  return data.message
}

export interface Card {
  key: string
  summary: string
  status: string
  priority: string | null
  url: string
}

export async function fetchCards(): Promise<Card[]> {
  const response = await fetch('/api/cards')
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed: ${response.status}`)
  }
  return response.json()
}
