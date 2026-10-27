import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import DeleteIcon from '@mui/icons-material/Delete'
import { useEffect, useState, type FormEvent } from 'react'
import { fetchAiConfig, saveAiConfig } from '../api'

interface Row {
  project: string
  path: string
}

export default function AiSettings() {
  const [statuses, setStatuses] = useState('')
  const [rows, setRows] = useState<Row[]>([])
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
        <Typography variant="h4" component="h1">
          AI Settings
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
            <TextField
              label={`Project key ${i + 1}`}
              size="small"
              value={row.project}
              onChange={(e) => setRow(i, { project: e.target.value })}
            />
            <TextField
              label={`Repo path ${i + 1}`}
              size="small"
              fullWidth
              value={row.path}
              onChange={(e) => setRow(i, { path: e.target.value })}
            />
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
