import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemText from '@mui/material/ListItemText'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import { fetchReview, startReview, type Review as ReviewData } from '../../api'
import ProviderChip from '../../shared/ProviderChip'
import StepButton from '../cards/StepButton'

export const REVIEW_POLL_MS = 3000

const STATE_LABEL = {
  running: 'running',
  clean: 'clean',
  fixed: 'fixes made',
  failed: 'failed',
}

export default function Review({
  cardKey,
  onStateChange,
}: {
  cardKey: string
  onStateChange?: (state: ReviewData['state'] | undefined) => void
}) {
  const [review, setReview] = useState<ReviewData | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchReview(cardKey).then(
      (r) => {
        setReview(r)
        setLoaded(true)
      },
      (e: Error) => {
        setError(e.message)
        setLoaded(true)
      },
    )
  }, [cardKey])

  useEffect(() => {
    onStateChange?.(review?.state)
  }, [review?.state, onStateChange])

  const running = review?.state === 'running'
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => {
      fetchReview(cardKey).then(setReview, (e: Error) => setError(e.message))
    }, REVIEW_POLL_MS)
    return () => clearInterval(id)
  }, [running, cardKey])

  async function start() {
    setBusy(true)
    setError(null)
    try {
      setReview(await startReview(cardKey))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!loaded) return null

  const done = review?.state === 'clean'
  const stepLabel = review ? 'Review again' : 'Start review'

  return (
    <Accordion disableGutters aria-label="Review">
      <AccordionSummary component="div" expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexGrow: 1, minWidth: 0 }}>
          <Typography variant="h6" component="h2">
            Review
          </Typography>
          <Chip
            label={review ? STATE_LABEL[review.state] : 'not started'}
            size="small"
            color={
              review?.state === 'clean' ? 'success' : review?.state === 'failed' ? 'error' : review?.state === 'fixed' ? 'warning' : 'default'
            }
          />
          <ProviderChip provider={review?.provider} />
          <Box sx={{ flexGrow: 1 }} />
          {!done && (
            <span onClick={(e) => e.stopPropagation()}>
              <StepButton
                label={stepLabel}
                status={running ? 'running' : busy ? 'blocked' : 'next'}
                onRun={start}
              />
            </span>
          )}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          {running && <Typography>Reviewing the changes...</Typography>}
          {review?.state === 'fixed' && (
            <Alert severity="warning" role="note">
              The reviewer committed fixes, so the result needs another review.
            </Alert>
          )}
          {review?.notes.map((n) => (
            <Alert key={n} severity="info" role="note">
              {n}
            </Alert>
          ))}
          {review?.state === 'failed' && <Alert severity="error">{review.error}</Alert>}
          {error && <Alert severity="error">{error}</Alert>}
          {review && review.fix_commits.length > 0 && (
            <Paper variant="outlined">
              <List dense aria-label="Review fixes">
                {review.fix_commits.map((c) => (
                  <ListItem key={c.sha}>
                    <ListItemText primary={c.subject} secondary={c.sha} />
                  </ListItem>
                ))}
              </List>
            </Paper>
          )}
          {review?.report && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Box data-testid="review-report">
                <Markdown>{review.report}</Markdown>
              </Box>
            </Paper>
          )}
          {!review && !error && (
            <Typography color="text.secondary">The review has not been started.</Typography>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
