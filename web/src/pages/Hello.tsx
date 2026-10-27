import { useEffect, useState } from 'react'
import { fetchHello } from '../api'

export default function Hello() {
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchHello().then(setMessage, (e: Error) => setError(e.message))
  }, [])

  if (error) return <p role="alert">{error}</p>
  if (message === null) return <p>Loading...</p>
  return <h1>{message}</h1>
}
