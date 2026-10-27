import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
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
    fetchJiraStatus().then((s) => {
      setStatus(s)
      // Don't clobber anything the user typed while the request was in flight.
      setBaseUrl((v) => v || s.base_url)
      setEmail((v) => v || s.email)
    }, (e: Error) => setError(e.message))
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
    <Box component="form" onSubmit={onSubmit} sx={{ maxWidth: 560 }}>
      <Stack spacing={2}>
      <Typography variant="h4" component="h1">
        Settings
      </Typography>
      {status?.connected && <Alert severity="success" role="note">Connected to Jira as {status.user}.</Alert>}
      {status?.configured && !status.connected && (
        <Alert severity="warning" role="note">The saved credentials are not working. Please update them.</Alert>
      )}
      {status && !status.configured && (
        <Alert severity="info" role="note">Enter your Jira site, email and API token.</Alert>
      )}
      <TextField
        label="Jira site URL"
        type="url"
        placeholder="https://your-site.atlassian.net"
        value={baseUrl}
        onChange={(e) => setBaseUrl(e.target.value)}
      />
      <TextField
        label="Jira email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <TextField
        label="Jira API token"
        type="password"
        autoComplete="off"
        placeholder={status?.configured ? 'Leave blank to keep current token' : ''}
        value={token}
        onChange={(e) => setToken(e.target.value)}
      />
      <Button type="submit" variant="contained" disabled={saving || !hasChanges}>
        Save
      </Button>
      {saved && <Alert severity="success" role="status">{saved}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
      </Stack>
    </Box>
  )
}
