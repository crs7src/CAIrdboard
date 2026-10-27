import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchCards, type Card } from '../api'

export default function Cards() {
  const [cards, setCards] = useState<Card[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const sync = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setCards(await fetchCards())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    sync()
  }, [sync])

  return (
    <main>
      <h1>My Cards</h1>
      <button onClick={sync} disabled={loading}>
        {loading ? 'Syncing...' : 'Sync'}
      </button>
      {error && <p role="alert">{error}</p>}
      {error && (
        <p>
          <Link to="/settings">Update your Jira settings</Link>
        </p>
      )}
      {cards?.length === 0 && <p>No cards assigned to you.</p>}
      <ul>
        {cards?.map((card) => (
          <li key={card.key}>
            <a href={card.url} target="_blank" rel="noreferrer">
              {card.key}
            </a>{' '}
            {card.summary} — {card.status}
            {card.priority && ` (${card.priority})`}
          </li>
        ))}
      </ul>
    </main>
  )
}
