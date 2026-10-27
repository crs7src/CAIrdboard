import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import DeleteIcon from '@mui/icons-material/Delete'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useEffect, useState } from 'react'
import {
  clearProjectTestConfig,
  fetchAiConfig,
  fetchProjectTestConfig,
  saveProjectTestConfig,
  type TestApp,
} from '../api'

const blank = (): TestApp => ({ name: '', start_command: '', workdir: '.', ready_url: '', ready_timeout_seconds: null })

function ProjectEditor({ project }: { project: string }) {
  const [apps, setApps] = useState<TestApp[]>([])
  const [configured, setConfigured] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetchProjectTestConfig(project).then(
      (c) => {
        setApps(c?.apps ?? [])
        setConfigured(!!c)
        setLoaded(true)
      },
      (e: Error) => setError(e.message),
    )
  }, [project])

  const edit = (i: number, patch: Partial<TestApp>) => {
    setSaved(false)
    setApps((a) => a.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  }
  const move = (i: number, d: number) => {
    setSaved(false)
    setApps((a) => {
      const next = [...a]
      ;[next[i], next[i + d]] = [next[i + d], next[i]]
      return next
    })
  }
  const complete = apps.length > 0 && apps.every((a) => a.name.trim() && a.start_command.trim() && a.ready_url.trim())

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      await fn()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const save = () =>
    run(async () => {
      const cfg = await saveProjectTestConfig(
        project,
        apps.map((a) => ({ ...a, ready_timeout_seconds: a.ready_timeout_seconds || null })),
      )
      setApps(cfg.apps)
      setConfigured(true)
      setSaved(true)
    })
  const clear = () =>
    run(async () => {
      await clearProjectTestConfig(project)
      setApps([])
      setConfigured(false)
    })

  return (
    <Accordion disableGutters aria-label={`${project} test apps`}>
      <AccordionSummary component="div" expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Typography variant="h6" component="h3">
            {project}
          </Typography>
          {loaded && <Chip size="small" label={configured ? 'Configured' : 'Not set'} color={configured ? 'success' : 'default'} />}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          {apps.map((a, i) => (
            <Paper key={i} variant="outlined" sx={{ p: 2 }}>
              <Stack spacing={1.5}>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                  <TextField label="Name" size="small" value={a.name} onChange={(e) => edit(i, { name: e.target.value })} sx={{ flexGrow: 1 }} />
                  <IconButton aria-label={`Move ${a.name || 'app'} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                    <ArrowUpwardIcon />
                  </IconButton>
                  <IconButton aria-label={`Move ${a.name || 'app'} down`} disabled={i === apps.length - 1} onClick={() => move(i, 1)}>
                    <ArrowDownwardIcon />
                  </IconButton>
                  <IconButton
                    aria-label={`Remove ${a.name || 'app'}`}
                    onClick={() => {
                      setSaved(false)
                      setApps(apps.filter((_, j) => j !== i))
                    }}
                  >
                    <DeleteIcon />
                  </IconButton>
                </Stack>
                <TextField label="Start command" size="small" value={a.start_command} onChange={(e) => edit(i, { start_command: e.target.value })} slotProps={{ htmlInput: { style: { fontFamily: 'monospace' } } }} />
                <Stack direction="row" spacing={1}>
                  <TextField label="Folder (inside the repo)" size="small" value={a.workdir} onChange={(e) => edit(i, { workdir: e.target.value })} sx={{ flex: 1 }} />
                  <TextField label="Ready URL" size="small" value={a.ready_url} onChange={(e) => edit(i, { ready_url: e.target.value })} placeholder="http://localhost:5173" sx={{ flex: 2 }} />
                  <TextField
                    label="Timeout (s)"
                    size="small"
                    type="number"
                    value={a.ready_timeout_seconds ?? ''}
                    onChange={(e) => edit(i, { ready_timeout_seconds: e.target.value ? Number(e.target.value) : null })}
                    sx={{ width: 120 }}
                  />
                </Stack>
              </Stack>
            </Paper>
          ))}
          {error && <Alert severity="error">{error}</Alert>}
          {saved && <Alert severity="success">Saved.</Alert>}
          <Stack direction="row" spacing={1}>
            <Button onClick={() => { setSaved(false); setApps([...apps, blank()]) }}>Add app</Button>
            <Button variant="contained" disabled={busy || !complete} onClick={save}>
              Save
            </Button>
            <Button color="inherit" disabled={busy || !configured} onClick={clear}>
              Clear
            </Button>
          </Stack>
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}

export default function TestAppsSettings() {
  const [projects, setProjects] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchAiConfig().then(
      (c) => setProjects(Object.keys(c.project_repos).sort()),
      (e: Error) => setError(e.message),
    )
  }, [])

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        Test apps
      </Typography>
      <Typography color="text.secondary">
        How each project&apos;s apps are started for manual testing. Apps start in the order listed, each waiting
        for its ready URL (localhost only). Start test uses only these settings; use &quot;Start with AI&quot; on a
        card to have an AI work them out (its result replaces what is saved here).
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {projects?.length === 0 && (
        <Alert severity="info" role="note">
          Map a project to a repo under the AI tab first.
        </Alert>
      )}
      {projects?.map((p) => <ProjectEditor key={p} project={p} />)}
    </Stack>
  )
}
