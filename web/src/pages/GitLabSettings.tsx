import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Divider from '@mui/material/Divider'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useEffect, useState, type FormEvent } from 'react'
import {
  checkGitLabProject,
  fetchGitLabProjects,
  fetchGitLabStatus,
  saveGitLabCredentials,
  setGitLabProject,
  type GitLabCredentialsUpdate,
  type GitLabProjectInfo,
  type GitLabStatus,
} from '../api'

function Connection() {
  const [status, setStatus] = useState<GitLabStatus | null>(null)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  useEffect(() => {
    fetchGitLabStatus().then((s) => {
      setStatus(s)
      setUrl((v) => v || s.url)
    }, (e: Error) => setError(e.message))
  }, [])

  const update: GitLabCredentialsUpdate = {}
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
      const result = await saveGitLabCredentials(update)
      setSaved(`Saved. Connected as ${result.user}.`)
      setToken('')
      const s = await fetchGitLabStatus()
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
          GitLab connection
        </Typography>
        {status?.connected && <Alert severity="success" role="note">Connected to GitLab as {status.user}.</Alert>}
        {status?.configured && !status.connected && (
          <Alert severity="warning" role="note">The saved credentials are not working. Please update them.</Alert>
        )}
        {status && !status.configured && (
          <Alert severity="info" role="note">Enter your GitLab URL and a personal access token with the api scope.</Alert>
        )}
        <TextField
          label="GitLab URL"
          type="url"
          placeholder="https://gitlab.example.com"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <TextField
          label="GitLab access token"
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

function ProjectRow({ info, onChange }: { info: GitLabProjectInfo; onChange: (i: GitLabProjectInfo) => void }) {
  const [path, setPath] = useState(info.override ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      await action()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    run(async () => {
      const updated = await setGitLabProject(info.project, path.trim())
      onChange(updated)
    })
  const reset = () =>
    run(async () => {
      const updated = await setGitLabProject(info.project, null)
      setPath('')
      onChange(updated)
    })
  const check = () =>
    run(async () => {
      const p = await checkGitLabProject(info.project)
      setResult(`OK: ${p.path}, default branch ${p.default_branch ?? 'none'}`)
    })

  return (
    <Stack spacing={1} aria-label={`GitLab project ${info.project}`} role="group">
      <Typography variant="subtitle1">{info.project}</Typography>
      <Typography variant="body2" color="text.secondary">
        {info.repo}
      </Typography>
      <Typography variant="body2">
        {info.effective
          ? `Using ${info.effective}${info.override ? ' (override)' : ' (from origin remote)'}`
          : 'No GitLab project detected. Enter one below.'}
      </Typography>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <TextField
          size="small"
          label="GitLab project path"
          placeholder={info.detected ?? 'group/project'}
          value={path}
          onChange={(e) => setPath(e.target.value)}
          sx={{ flex: 1 }}
        />
        <Button variant="contained" disabled={busy || !path.trim() || path.trim() === info.override} onClick={save}>
          Set
        </Button>
        <Button disabled={busy || !info.override} onClick={reset}>
          Reset
        </Button>
        <Button disabled={busy || !info.effective} onClick={check}>
          Check
        </Button>
      </Stack>
      {result && <Alert severity="success" role="status">{result}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
    </Stack>
  )
}

function Projects() {
  const [projects, setProjects] = useState<GitLabProjectInfo[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchGitLabProjects().then(setProjects, (e: Error) => setError(e.message))
  }, [])

  return (
    <Stack spacing={2} sx={{ maxWidth: 760 }}>
      <Typography variant="h6" component="h2">
        Project mapping
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Each Jira project's repo is matched to a GitLab project from its origin remote. Set a path to override it.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {projects?.length === 0 && (
        <Alert severity="info" role="note">No projects have a repo yet. Add one under Settings → AI.</Alert>
      )}
      {projects?.map((p) => (
        <ProjectRow
          key={p.project}
          info={p}
          onChange={(u) => setProjects((all) => all?.map((x) => (x.project === u.project ? u : x)) ?? null)}
        />
      ))}
    </Stack>
  )
}

export default function GitLabSettings() {
  return (
    <Stack spacing={3}>
      <Connection />
      <Divider />
      <Projects />
    </Stack>
  )
}
