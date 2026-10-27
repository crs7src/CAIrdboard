import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import Link from '@mui/material/Link'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import { useCallback, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { Link as RouterLink, useParams, useSearchParams } from 'react-router-dom'
import Implementation from './Implementation'
import Review from './Review'
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
  const [searchParams] = useSearchParams()
  const [planOpen, setPlanOpen] = useState(searchParams.get('open') === 'plan')
  const [focusApprove, setFocusApprove] = useState(false)
  const [implState, setImplState] = useState<string | null>(null)
  const approveRef = useRef<HTMLButtonElement>(null)

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

  useEffect(() => {
    if (!focusApprove || !planOpen || !approveRef.current) return
    approveRef.current.focus()
    approveRef.current.scrollIntoView?.({ block: 'center' })
    setFocusApprove(false)
  }, [focusApprove, planOpen, plan])

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

  const backButton = (
    <Box>
      <Button startIcon={<ArrowBackIcon />} component={RouterLink} to="/cards">
        Back to My Cards
      </Button>
    </Box>
  )

  if (!card) {
    return (
      <Stack spacing={2}>
        {backButton}
        {error ? <Alert severity="error">{error}</Alert> : <CircularProgress aria-label="Loading" />}
      </Stack>
    )
  }

  const canGenerate = card.eligible && card.repo_configured
  const hasPlanText = plan?.plan != null

  let playLabel: string | null = null
  let onPlay = () => {}
  if (plan?.state === 'ready') {
    playLabel = 'Review plan'
    onPlay = () => {
      setPlanOpen(true)
      setFocusApprove(true)
    }
  } else if (canGenerate && !running && plan?.state !== 'approved') {
    playLabel = !plan ? 'Run plan' : 'Retry plan'
    onPlay = () => act(() => generatePlan(key, feedback))
  }

  return (
    <Stack spacing={2}>
      {backButton}
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
        <AccordionSummary component="div" expandIcon={<ExpandMoreIcon />}>
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

      {(plan || canGenerate) && (
        <Accordion expanded={planOpen} onChange={(_, v) => setPlanOpen(v)} disableGutters>
          <AccordionSummary component="div" expandIcon={<ExpandMoreIcon />}>
            <Stack
              direction="row"
              spacing={1}
              sx={{ alignItems: 'center', flexGrow: 1, minWidth: 0 }}
            >
              <Typography variant="h6" component="h2">
                Plan
              </Typography>
              {plan && <Chip label={`v${plan.version}`} size="small" />}
              <Chip
                label={plan ? plan.state : 'not started'}
                size="small"
                color={
                  plan?.state === 'approved'
                    ? 'success'
                    : plan?.state === 'failed'
                      ? 'error'
                      : 'default'
                }
              />
              {running && <CircularProgress size={18} aria-label="Generating plan" />}
              <Box sx={{ flexGrow: 1 }} />
              {playLabel && (
                <Tooltip title={playLabel}>
                  <span>
                    <IconButton
                      size="small"
                      color="primary"
                      aria-label={playLabel}
                      disabled={busy}
                      onClick={(e) => {
                        e.stopPropagation()
                        onPlay()
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
              {running && <Typography>Generating plan...</Typography>}
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
                    ref={approveRef}
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

              {canGenerate && !running && !plan && (
                <Box>
                  <Button
                    variant="contained"
                    disabled={busy}
                    onClick={() => act(() => generatePlan(key))}
                  >
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
          </AccordionDetails>
        </Accordion>
      )}

      {plan?.state === 'approved' && card.repo_configured && (
        <Implementation cardKey={key} onStateChange={setImplState} />
      )}
      {plan?.state === 'approved' && card.repo_configured && implState === 'completed' && (
        <Review cardKey={key} />
      )}
    </Stack>
  )
}
