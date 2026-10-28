import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useEffect, useState, type FormEvent } from 'react'
import { LABELS } from './hosts'
import { fetchHostStatus, saveHostCredentials, type HostCredentialsUpdate, type HostStatus, type RepoProvider } from '../api'

const PLACEHOLDERS: Record<RepoProvider, string> = {
  gitlab: 'https://gitlab.example.com',
  github: 'https://api.github.com',
}
const HINTS: Record<RepoProvider, string> = {
  gitlab: 'Enter your GitLab URL and a personal access token with the api scope.',
  github:
    'Enter the API URL (https://api.github.com, or https://HOST/api/v3 for Enterprise) and a token. A fine-grained token needs Contents and Pull requests read & write; a classic token needs the repo scope.',
}

export default function HostConnection({ provider }: { provider: RepoProvider }) {
  const name = LABELS[provider]
  const [status, setStatus] = useState<HostStatus | null>(null)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  useEffect(() => {
    fetchHostStatus(provider).then((s) => {
      setStatus(s)
      setUrl((v) => v || s.url)
    }, (e: Error) => setError(e.message))
  }, [provider])

  const update: HostCredentialsUpdate = {}
  if (status) {
    if (url.trim() !== status.url) update.url = url.trim()
    if (token.trim()) update.token = token.trim()
  }
  const hasChanges = Object.keys(update).length > 0

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSaved(null)
    try {
      const result = await saveHostCredentials(provider, update)
      setSaved(`Saved. Connected as ${result.user}.`)
      setToken('')
      const s = await fetchHostStatus(provider)
      setStatus(s)
      setUrl(s.url)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Box component="form" onSubmit={onSubmit} sx={{ maxWidth: 560 }}>
      <Stack spacing={2}>
        <Typography variant="h6" component="h2">
          {name} connection
        </Typography>
        {status?.connected && <Alert severity="success" role="note">Connected to {name} as {status.user}.</Alert>}
        {status?.configured && !status.connected && (
          <Alert severity="warning" role="note">The saved credentials are not working. Please update them.</Alert>
        )}
        {status && !status.configured && (
          <Alert severity="info" role="note">{HINTS[provider]}</Alert>
        )}
        <TextField
          label={`${name} URL`}
          type="url"
          placeholder={PLACEHOLDERS[provider]}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <TextField
          label={`${name} access token`}
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

