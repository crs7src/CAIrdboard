import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useEffect, useState } from 'react'
import { checkRepoHost, fetchRepoHosts, setRepoHost, type RepoHostInfo, type RepoProvider } from '../api'
import { LABELS } from './hosts'

function ProjectRow({
  provider,
  info,
  onChange,
}: {
  provider: RepoProvider
  info: RepoHostInfo
  onChange: (i: RepoHostInfo) => void
}) {
  const name = LABELS[provider]
  const own = info.provider === provider
  const overridden = own && info.source === 'override'
  const [path, setPath] = useState(overridden ? (info.path ?? '') : '')
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
      const updated = await setRepoHost(info.project, { provider, path: path.trim() })
      onChange(updated)
    })
  const reset = () =>
    run(async () => {
      const updated = await setRepoHost(info.project, null)
      setPath('')
      onChange(updated)
    })
  const check = () =>
    run(async () => {
      const p = await checkRepoHost(info.project)
      setResult(`OK: ${p.path}, default branch ${p.default_branch ?? 'none'}`)
    })

  return (
    <Stack spacing={1} aria-label={`${name} project ${info.project}`} role="group">
      <Typography variant="subtitle1">{info.project}</Typography>
      <Typography variant="body2" color="text.secondary">
        {info.repo}
      </Typography>
      <Typography variant="body2">
        {info.path && info.provider
          ? `Using ${own ? '' : `${LABELS[info.provider]} project `}${info.path}${info.source === 'override' ? ' (override)' : ' (from origin remote)'}`
          : `No ${name} project detected. Enter one below.`}
      </Typography>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <TextField
          size="small"
          label={`${name} project path`}
          placeholder={info.detected?.provider === provider ? info.detected.path : provider === 'github' ? 'owner/repo' : 'group/project'}
          value={path}
          onChange={(e) => setPath(e.target.value)}
          sx={{ flex: 1 }}
        />
        <Button variant="contained" disabled={busy || !path.trim() || (overridden && path.trim() === info.path)} onClick={save}>
          Set
        </Button>
        <Button disabled={busy || info.source !== 'override'} onClick={reset}>
          Reset
        </Button>
        <Button disabled={busy || !info.path} onClick={check}>
          Check
        </Button>
      </Stack>
      {result && <Alert severity="success" role="status">{result}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
    </Stack>
  )
}

export default function RepoHostProjects({ provider }: { provider: RepoProvider }) {
  const [projects, setProjects] = useState<RepoHostInfo[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchRepoHosts().then(setProjects, (e: Error) => setError(e.message))
  }, [])

  return (
    <Stack spacing={2} sx={{ maxWidth: 760 }}>
      <Typography variant="h6" component="h2">
        Project mapping
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Each Jira project's repo is matched to a {LABELS[provider]} project from its origin remote. Set a path to override it.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {projects?.length === 0 && (
        <Alert severity="info" role="note">No projects have a repo yet. Add one under Settings → AI.</Alert>
      )}
      {projects?.map((p) => (
        <ProjectRow
          provider={provider}
          key={p.project}
          info={p}
          onChange={(u) => setProjects((all) => all?.map((x) => (x.project === u.project ? u : x)) ?? null)}
        />
      ))}
    </Stack>
  )
}

