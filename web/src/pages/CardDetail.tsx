import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Link from '@mui/material/Link'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useCallback, useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import { Link as RouterLink, useParams } from 'react-router-dom'
import Implementation from './Implementation'
import {
  decidePlan,
  fetchCardDetail,
  fetchPlan,
  generatePlan,
  type CardDetail as CardDetailData,
  type Plan,
} from '../api'

export const POLL_MS = 2000

export default function CardDetail() {
  const { key = '' } = useParams()
  const [card, setCard] = useState<CardDetailData | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState('')

  useEffect(() => {
    Promise.all([fetchCardDetail(key), fetchPlan(key)]).then(
      ([c, p]) => {
        setCard(c)
        setPlan(p)
      },
      (e: Error) => setError(e.message),
    )
  }, [key])

  const running = plan?.state === 'running'
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => {
      fetchPlan(key).then(setPlan, (e: Error) => setError(e.message))
    }, POLL_MS)
    return () => clearInterval(id)
  }, [running, key])

  const act = useCallback(async (fn: () => Promise<Plan>) => {
    setBusy(true)
    setError(null)
    try {
      setPlan(await fn())
      setFeedback('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [])

  if (!card) {
    return error ? (
      <Alert severity="error">{error}</Alert>
    ) : (
      <CircularProgress aria-label="Loading" />
    )
  }

  const canGenerate = card.eligible && card.repo_configured
  const hasPlanText = plan?.plan != null

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography variant="h4" component="h1">
          {card.key}
        </Typography>
        <Chip label={card.status} />
        {card.reopened && <Chip label="Reopened before" color="error" variant="outlined" />}
        {card.priority && <Chip label={card.priority} color="warning" />}
        <Link href={card.url} target="_blank" rel="noreferrer">
          Open in Jira
        </Link>
      </Stack>
      <Typography variant="h6" component="h2">
        {card.summary}
      </Typography>
      <Typography sx={{ whiteSpace: 'pre-wrap' }} color="text.secondary">
        {card.description || 'No description.'}
      </Typography>
      {card.reopened && card.status_history.length > 0 && (
        <Typography variant="body2" color="text.secondary">
          History: {card.status_history.map((h) => `${h.from_status} → ${h.to_status}`).join(', ')}
        </Typography>
      )}
      <Accordion defaultExpanded disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>Comments ({card.comments.length})</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            {card.comments.length === 0 && (
              <Typography color="text.secondary">No comments.</Typography>
            )}
            {card.comments.map((c, i) => (
              <Box key={i}>
                <Typography variant="subtitle2">
                  {c.author} · {new Date(c.created).toLocaleString()}
                  {c.after_reopen && <Chip label="after reopen" size="small" sx={{ ml: 1 }} />}
                </Typography>
                <Typography sx={{ whiteSpace: 'pre-wrap' }}>{c.body}</Typography>
              </Box>
            ))}
          </Stack>
        </AccordionDetails>
      </Accordion>

      {error && <Alert severity="error">{error}</Alert>}
      {!card.eligible && (
        <Alert severity="info" role="note">
          Plans are not generated for cards in &quot;{card.status}&quot;.
        </Alert>
      )}
      {card.eligible && !card.repo_configured && (
        <Alert
          severity="warning"
          role="note"
          action={
            <Button color="inherit" size="small" component={RouterLink} to="/settings/ai">
              AI Settings
            </Button>
          }
        >
          No repo is configured for project {card.project}.
        </Alert>
      )}

      {plan && (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Typography variant="h5" component="h2">
            Plan
          </Typography>
          <Chip label={`v${plan.version}`} size="small" />
          <Chip
            label={plan.state}
            size="small"
            color={
              plan.state === 'approved'
                ? 'success'
                : plan.state === 'failed'
                  ? 'error'
                  : 'default'
            }
          />
        </Stack>
      )}
      {running && (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <CircularProgress size={20} aria-label="Generating plan" />
          <Typography>Generating plan...</Typography>
        </Stack>
      )}
      {plan?.state === 'failed' && <Alert severity="error">{plan.error}</Alert>}
      {plan?.feedback && (
        <Typography color="text.secondary">Feedback used: {plan.feedback}</Typography>
      )}
      {hasPlanText && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Box data-testid="plan-body">
            <Markdown>{plan.plan}</Markdown>
          </Box>
        </Paper>
      )}

      {plan?.state === 'ready' && (
        <Stack direction="row" spacing={1}>
          <Button
            variant="contained"
            color="success"
            disabled={busy}
            onClick={() => act(() => decidePlan(key, 'approve'))}
          >
            Approve
          </Button>
          <Button
            variant="outlined"
            color="error"
            disabled={busy}
            onClick={() => act(() => decidePlan(key, 'reject'))}
          >
            Reject
          </Button>
        </Stack>
      )}

      {plan?.state === 'approved' && card.repo_configured && <Implementation cardKey={key} />}

      {canGenerate && !running && !plan && (
        <Box>
          <Button variant="contained" disabled={busy} onClick={() => act(() => generatePlan(key))}>
            Generate plan
          </Button>
        </Box>
      )}
      {canGenerate && !running && plan && (
        <Stack spacing={1}>
          <TextField
            label="What was wrong with this plan? (optional)"
            multiline
            minRows={2}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
          />
          <Box>
            <Button
              variant="outlined"
              disabled={busy}
              onClick={() => act(() => generatePlan(key, feedback))}
            >
              Regenerate plan
            </Button>
          </Box>
        </Stack>
      )}
    </Stack>
  )
}
