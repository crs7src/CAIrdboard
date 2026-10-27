import { useEffect, useState, type FormEvent } from 'react'
import {
  fetchJiraStatus,
  saveJiraCredentials,
  type CredentialsUpdate,
  type JiraStatus,
} from '../api'

export default function Settings() {
  const [status, setStatus] = useState<JiraStatus | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  function applyStatus(s: JiraStatus) {
    setStatus(s)
    setBaseUrl(s.base_url)
    setEmail(s.email)
  }

  useEffect(() => {
    fetchJiraStatus().then(applyStatus, (e: Error) => setError(e.message))
  }, [])

  // Only send fields the user actually changed; the backend keeps the rest.
  const update: CredentialsUpdate = {}
  if (status) {
    if (baseUrl.trim() !== status.base_url) update.base_url = baseUrl.trim()
    if (email.trim() !== status.email) update.email = email.trim()
    if (token.trim()) update.token = token.trim()
  }
  const hasChanges = Object.keys(update).length > 0

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSaved(null)
    try {
      const result = await saveJiraCredentials(update)
      setSaved(`Saved. Connected as ${result.user}.`)
      setToken('')
      applyStatus(await fetchJiraStatus())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <main>
      <h1>Settings</h1>
      {status?.connected && <p>Connected to Jira as {status.user}.</p>}
      {status?.configured && !status.connected && (
        <p>The saved credentials are not working. Please update them.</p>
      )}
      {status && !status.configured && <p>Enter your Jira site, email and API token.</p>}
      <form onSubmit={onSubmit}>
        <label>
          Jira site URL
          <input
            type="url"
            placeholder="https://your-site.atlassian.net"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </label>
        <label>
          Jira email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Jira API token
          <input
            type="password"
            autoComplete="off"
            placeholder={status?.configured ? 'Leave blank to keep current token' : ''}
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </label>
        <button type="submit" disabled={saving || !hasChanges}>
          Save
        </button>
      </form>
      {saved && <p role="status">{saved}</p>}
      {error && <p role="alert">{error}</p>}
    </main>
  )
}
