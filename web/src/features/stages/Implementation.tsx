import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemText from '@mui/material/ListItemText'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import { fetchImplementation, startImplementation, type Implementation as Impl } from '../../api'

export const IMPL_POLL_MS = 3000

const STAGE_LABEL = { preparing: 'Preparing branch...', implementing: 'Implementing...', done: '' }

interface Props {
  cardKey: string
  onStateChange?: (state: Impl['state'] | null) => void
}

export default function Implementation({ cardKey, onStateChange }: Props) {
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

  const state = impl?.state ?? null
  useEffect(() => {
    if (loaded) onStateChange?.(state)
  }, [loaded, state, onStateChange])

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

  const canStart = !running && (!impl || impl.state === 'failed')
  const startLabel = impl ? 'Retry implementation' : 'Start implementation'

  return (
    <Accordion disableGutters aria-label="Implementation">
      <AccordionSummary component="div" expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexGrow: 1, minWidth: 0 }}>
          <Typography variant="h6" component="h2">
            Implementation
          </Typography>
          <Chip
            label={impl ? impl.state : 'not started'}
            size="small"
            color={
              impl?.state === 'completed' ? 'success' : impl?.state === 'failed' ? 'error' : 'default'
            }
          />
          {impl?.branch && <Chip label={impl.branch} size="small" variant="outlined" />}
          {running && <CircularProgress size={18} aria-label="Implementing" />}
          <Box sx={{ flexGrow: 1 }} />
          {canStart && (
            <Tooltip title={startLabel}>
              <span>
                <IconButton
                  size="small"
                  color="primary"
                  aria-label={startLabel}
                  disabled={busy}
                  onClick={(e) => {
                    e.stopPropagation()
                    start()
                  }}
                  onFocus={(e) => e.stopPropagation()}
                >
                  <PlayArrowIcon />
                </IconButton>
              </span>
            </Tooltip>
          )}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          {running && impl && <Typography>{STAGE_LABEL[impl.stage]}</Typography>}
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
          {!impl && !error && (
            <Typography color="text.secondary">Implementation has not been started.</Typography>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
