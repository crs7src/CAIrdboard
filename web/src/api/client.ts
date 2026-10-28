export function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((d) => d?.msg ?? 'Invalid input').join('; ')
  }
  return `Request failed: ${status}`
}

export async function failure(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null)
  return new Error(errorMessage(body?.detail, response.status))
}

export const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
