import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemText from '@mui/material/ListItemText'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import { fetchImplementation, startImplementation, type Implementation as Impl } from '../api'

export const IMPL_POLL_MS = 3000

const STAGE_LABEL = { preparing: 'Preparing branch...', implementing: 'Implementing...', done: '' }

export default function Implementation({ cardKey }: { cardKey: string }) {
  const [impl, setImpl] = useState<Impl | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchImplementation(cardKey).then(
      (i) => {
        setImpl(i)
        setLoaded(true)
      },
      (e: Error) => {
        setError(e.message)
        setLoaded(true)
      },
    )
  }, [cardKey])

  const running = impl?.state === 'running'
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => {
      fetchImplementation(cardKey).then(setImpl, (e: Error) => setError(e.message))
    }, IMPL_POLL_MS)
    return () => clearInterval(id)
  }, [running, cardKey])

  async function start() {
    setBusy(true)
    setError(null)
    try {
      setImpl(await startImplementation(cardKey))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!loaded) return null

  return (
    <Stack spacing={2} component="section" aria-label="Implementation">
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="h5" component="h2">
          Implementation
        </Typography>
        {impl && (
          <Chip
            label={impl.state}
            size="small"
            color={impl.state === 'completed' ? 'success' : impl.state === 'failed' ? 'error' : 'default'}
          />
        )}
        {impl?.branch && <Chip label={impl.branch} size="small" variant="outlined" />}
      </Stack>

      {running && (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <CircularProgress size={20} aria-label="Implementing" />
          <Typography>{STAGE_LABEL[impl.stage]}</Typography>
        </Stack>
      )}
      {impl?.notes.map((n) => (
        <Alert key={n} severity="info" role="note">
          {n}
        </Alert>
      ))}
      {impl?.state === 'failed' && <Alert severity="error">{impl.error}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}

      {impl && impl.commits.length > 0 && (
        <Paper variant="outlined">
          <List dense aria-label="Commits">
            {impl.commits.map((c) => (
              <ListItem key={c.sha}>
                <ListItemText primary={c.subject} secondary={c.sha} />
              </ListItem>
            ))}
          </List>
        </Paper>
      )}
      {impl?.report && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Box data-testid="implementation-report">
            <Markdown>{impl.report}</Markdown>
          </Box>
        </Paper>
      )}

      {!running && (!impl || impl.state === 'failed') && (
        <Box>
          <Button variant="contained" disabled={busy} onClick={start}>
            {impl ? 'Retry implementation' : 'Start implementation'}
          </Button>
        </Box>
      )}
    </Stack>
  )
}
