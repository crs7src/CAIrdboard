import Alert from '@mui/material/Alert'
import Autocomplete from '@mui/material/Autocomplete'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import DeleteIcon from '@mui/icons-material/Delete'
import { useEffect, useState, type FormEvent } from 'react'
import FolderPicker from './FolderPicker'
import { fetchAiConfig, fetchCards, saveAiConfig } from '../api'

interface Row {
  project: string
  path: string
}

export default function AiSettings() {
  const [statuses, setStatuses] = useState('')
  const [rows, setRows] = useState<Row[]>([])
  const [projects, setProjects] = useState<string[]>([])
  const [picking, setPicking] = useState<number | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetchAiConfig().then(
      (c) => {
        setStatuses(c.eligible_statuses.join(', '))
        setRows(Object.entries(c.project_repos).map(([project, path]) => ({ project, path })))
        setLoaded(true)
      },
      (e: Error) => setError(e.message),
    )
    // Best-effort: without Jira the field just behaves as free text.
    fetchCards().then(
      (cards) => setProjects([...new Set(cards.map((c) => c.project))].sort()),
      () => {},
    )
  }, [])

  function setRow(i: number, patch: Partial<Row>) {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await saveAiConfig({
        eligible_statuses: statuses.split(',').map((s) => s.trim()).filter(Boolean),
        project_repos: Object.fromEntries(
          rows.filter((r) => r.project.trim() || r.path.trim()).map((r) => [r.project, r.path]),
        ),
      })
      setSaved(true)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Box component="form" onSubmit={onSubmit} sx={{ maxWidth: 640 }}>
      <Stack spacing={2}>
        <Typography variant="h6" component="h2">
          AI planning
        </Typography>
        <TextField
          label="Eligible Jira statuses"
          helperText="Comma-separated. Plans can only be generated for cards in these statuses."
          value={statuses}
          onChange={(e) => {
            setStatuses(e.target.value)
            setSaved(false)
          }}
        />
        <Typography variant="h6" component="h2">
          Project repositories
        </Typography>
        {rows.map((row, i) => (
          <Stack key={i} direction="row" spacing={1}>
            <Autocomplete
              freeSolo
              size="small"
              sx={{ minWidth: 180 }}
              options={projects.filter(
                (p) => p === row.project || !rows.some((r) => r.project === p),
              )}
              inputValue={row.project}
              onInputChange={(_, v) => setRow(i, { project: v.toUpperCase() })}
              renderInput={(params) => (
                <TextField {...params} label={`Project key ${i + 1}`} />
              )}
            />
            <TextField
              label={`Repo path ${i + 1}`}
              size="small"
              fullWidth
              value={row.path}
              onChange={(e) => setRow(i, { path: e.target.value })}
            />
            <Button onClick={() => setPicking(i)} aria-label={`Browse for repo ${i + 1}`}>
              Browse
            </Button>
            <IconButton
              aria-label={`Remove project ${i + 1}`}
              onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
            >
              <DeleteIcon />
            </IconButton>
          </Stack>
        ))}
        <Box>
          <Button onClick={() => setRows((rs) => [...rs, { project: '', path: '' }])}>
            Add project
          </Button>
        </Box>
        <FolderPicker
          open={picking !== null}
          initialPath={picking !== null ? (rows[picking]?.path ?? '') : ''}
          onClose={() => setPicking(null)}
          onSelect={(path) => {
            if (picking !== null) setRow(picking, { path })
            setPicking(null)
            setSaved(false)
          }}
        />
        <Button type="submit" variant="contained" disabled={saving || !loaded}>
          Save AI settings
        </Button>
        {saved && (
          <Alert severity="success" role="status">
            AI settings saved.
          </Alert>
        )}
        {error && <Alert severity="error">{error}</Alert>}
      </Stack>
    </Box>
  )
}
