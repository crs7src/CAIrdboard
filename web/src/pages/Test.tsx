import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Link from '@mui/material/Link'
import ToggleButton from '@mui/material/ToggleButton'
import CheckIcon from '@mui/icons-material/Check'
import { Link as RouterLink } from 'react-router-dom'
import TextField from '@mui/material/TextField'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemText from '@mui/material/ListItemText'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import {
  fetchTest,
  fetchTestApproval,
  setTestApproval,
  fetchTestConfig,
  forgetTestConfig,
  fetchFeedback,
  reportTestProblem,
  submitTestFeedback,
  startTest,
  stopTest,
  type FeedbackRun,
  type TestConfig,
  type TestRun,
} from '../api'
import StepButton from './StepButton'

export const TEST_POLL_MS = 3000
export const FEEDBACK_POLL_MS = 2000

const STATE_LABEL = {
  preparing: 'starting the app',
  running: 'app running',
  stopped: 'stopped',
  failed: 'failed',
}

export default function Test({
  cardKey,
  onApprovalChange,
}: {
  cardKey: string
  onApprovalChange?: (approved: boolean) => void
}) {
  const [run, setRun] = useState<TestRun | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<TestConfig | null>(null)
  const [problem, setProblem] = useState('')
  const [approved, setApproved] = useState(false)
  const [issues, setIssues] = useState('')
  const [fixRun, setFixRun] = useState<FeedbackRun | null>(null)

  useEffect(() => {
    fetchTest(cardKey).then(
      (r) => {
        setRun(r)
        setLoaded(true)
      },
      (e: Error) => {
        setError(e.message)
        setLoaded(true)
      },
    )
  }, [cardKey])

  useEffect(() => {
    onApprovalChange?.(approved)
  }, [approved, onApprovalChange])

  const preparing = run?.state === 'preparing'

  // Approval is withdrawn by the server when the branch changes, so re-read it with the run.
  const hasRun = !!run
  useEffect(() => {
    if (!hasRun) return
    fetchTestApproval(cardKey).then((a) => setApproved(a.approved), () => setApproved(false))
  }, [cardKey, hasRun, run?.version, run?.state])

  async function toggleApproval() {
    setError(null)
    try {
      setApproved((await setTestApproval(cardKey, !approved)).approved)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // Settings are saved when a run comes up, so look again whenever the state changes.
  useEffect(() => {
    if (preparing) return
    fetchTestConfig(cardKey).then(setConfig, () => setConfig(null))
  }, [cardKey, run?.state, run?.version, preparing])

  useEffect(() => {
    if (!preparing) return
    const id = setInterval(() => {
      fetchTest(cardKey).then(setRun, (e: Error) => setError(e.message))
    }, TEST_POLL_MS)
    return () => clearInterval(id)
  }, [preparing, cardKey])

  useEffect(() => {
    fetchFeedback(cardKey).then((f) => setFixRun(f.run), () => {})
  }, [cardKey])

  const fixing = fixRun?.state === 'running'
  useEffect(() => {
    if (!fixing) return
    const id = setInterval(() => {
      fetchFeedback(cardKey).then((f) => {
        setFixRun(f.run)
        if (f.run?.state === 'running') return
        // A finished fix run changes the branch and may clear the approval.
        fetchTest(cardKey).then(setRun, () => {})
        fetchTestApproval(cardKey).then((a) => setApproved(a.approved), () => setApproved(false))
      }, () => {})
    }, FEEDBACK_POLL_MS)
    return () => clearInterval(id)
  }, [fixing, cardKey])

  async function sendIssues() {
    setBusy(true)
    setError(null)
    try {
      setFixRun(await submitTestFeedback(cardKey, issues.trim()))
      setIssues('')
      setApproved(false)
      fetchTest(cardKey).then(setRun, () => {})
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function forget() {
    setError(null)
    try {
      await forgetTestConfig(cardKey)
      setConfig(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function act(fn: () => Promise<TestRun>): Promise<boolean> {
    setBusy(true)
    setError(null)
    try {
      setRun(await fn())
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  if (!loaded) return null

  const active = run?.state === 'running'

  return (
    <Accordion disableGutters aria-label="Manual test">
      <AccordionSummary component="div" expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexGrow: 1, minWidth: 0 }}>
          <Typography variant="h6" component="h2">
            Test
          </Typography>
          <Chip
            label={run ? STATE_LABEL[run.state] : 'not started'}
            size="small"
            color={run?.state === 'running' ? 'success' : run?.state === 'failed' ? 'error' : 'default'}
          />
          {config && <Chip label="saved settings" size="small" variant="outlined" />}
          {approved && <Chip label="approved" size="small" color="success" />}
          <Box sx={{ flexGrow: 1 }} />
          {run && (
            <span onClick={(e) => e.stopPropagation()}>
              <ToggleButton
                value="approved"
                size="small"
                selected={approved}
                disabled={preparing}
                aria-pressed={approved}
                onChange={toggleApproval}
                color="success"
              >
                {approved && <CheckIcon fontSize="small" sx={{ mr: 0.5 }} />}
                {approved ? 'Approved' : 'Approve'}
              </ToggleButton>
            </span>
          )}
          {!active && (
            <span onClick={(e) => e.stopPropagation()}>
              <StepButton
                label={run ? 'Test again' : 'Start test'}
                status={preparing ? 'running' : busy || !config ? 'blocked' : 'next'}
                onRun={() => act(() => startTest(cardKey))}
              />
            </span>
          )}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            How the apps are started is set under{' '}
            <Link component={RouterLink} to="/settings/test-apps">
              Settings → Test apps
            </Link>
            . Any further change to the branch withdraws your approval.
          </Typography>
          {preparing && (
            <Typography>
              {run?.source === 'saved'
                ? 'Starting app...'
                : run?.source === 'feedback'
                  ? 'Fixing how the app starts and restarting it...'
                  : 'Working out how to run the app and starting it...'}
            </Typography>
          )}
          {run?.problem && (
            <Alert severity="info" role="note">
              Reported problem: {run.problem}
            </Alert>
          )}
          {run?.notes.map((n) => (
            <Alert key={n} severity="info" role="note">
              {n}
            </Alert>
          ))}
          {run?.state === 'failed' && (
            <Alert severity="error" sx={{ whiteSpace: 'pre-wrap' }}>
              {run.error}
            </Alert>
          )}
          {error && <Alert severity="error">{error}</Alert>}
          {run?.report && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Box data-testid="test-report">
                <Markdown>{run.report}</Markdown>
              </Box>
            </Paper>
          )}
          {run && run.apps.length > 0 && (
            <Paper variant="outlined">
              <List dense aria-label="Running apps">
                {run.apps.map((a) => (
                  <ListItem key={a.name}>
                    <ListItemText
                      primary={a.name}
                      secondary={`${a.start_command} (in ${a.workdir})`}
                    />
                  </ListItem>
                ))}
              </List>
            </Paper>
          )}
          {run && run.links.length > 0 && run.state !== 'failed' && (
            <Paper variant="outlined">
              <List dense aria-label="Places to test">
                {run.links.map((l) => (
                  <ListItem key={l.url}>
                    <ListItemText
                      primary={
                        active ? (
                          <Link href={l.url} target="_blank" rel="noreferrer">
                            {l.title}
                          </Link>
                        ) : (
                          l.title
                        )
                      }
                      secondary={l.check}
                    />
                  </ListItem>
                ))}
              </List>
            </Paper>
          )}
          {active && (
            <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
              <Button
                variant="outlined"
                color="warning"
                disabled={busy}
                onClick={() => act(() => stopTest(cardKey))}
              >
                Stop app
              </Button>
              <Typography variant="body2" color="text.secondary">
                Stop the app when you finish: nothing else can use the repo while it runs.
              </Typography>
            </Stack>
          )}
          <Stack spacing={1}>
            <TextField
              label="Issues"
              size="small"
              multiline
              minRows={2}
              value={issues}
              onChange={(e) => setIssues(e.target.value)}
              helperText="Describe what you found wrong while testing. The app is stopped, the AI that handles code review comments fixes the code, and your approval is withdrawn."
            />
            <Stack direction="row" spacing={1}>
              <Button
                variant="contained"
                disabled={busy || preparing || fixing || !issues.trim()}
                onClick={sendIssues}
              >
                Send to code fixer
              </Button>
              <Button color="inherit" component={RouterLink} to={`/cards/${cardKey}/changes`}>
                View changes
              </Button>
              {config && (
                <Button color="inherit" disabled={busy} onClick={forget}>
                  Forget saved settings
                </Button>
              )}
            </Stack>
            {fixing && (
              <Alert severity="info" role="note">
                An AI is fixing the reported issues...
              </Alert>
            )}
            {fixRun?.state === 'done' && (
              <Alert severity="success" role="note">
                Fixes made ({fixRun.commits.length} {fixRun.commits.length === 1 ? 'commit' : 'commits'}).
                Test again and approve.
              </Alert>
            )}
            {fixRun?.state === 'failed' && <Alert severity="error">{fixRun.error}</Alert>}
          </Stack>
          {(!active && !preparing) || (!preparing && (config || run)) ? (
            <Accordion disableGutters variant="outlined" aria-label="App startup">
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>Start with AI / app startup issues</AccordionSummary>
              <AccordionDetails>
                <Stack spacing={2}>
                  {!active && !preparing && (
                    <Box>
                      <Button
                        variant="outlined"
                        disabled={busy}
                        onClick={() => act(() => startTest(cardKey, true))}
                      >
                        Start with AI
                      </Button>
                    </Box>
                  )}
                  {!preparing && (config || run) && (
                    <Stack spacing={1}>
                      <TextField
                        label="Report an issue with the app startup"
                        size="small"
                        multiline
                        minRows={2}
                        value={problem}
                        onChange={(e) => setProblem(e.target.value)}
                        helperText="An AI will fix how the apps are started (not the code) and restart them."
                      />
                      <Box>
                        <Button
                          variant="contained"
                          disabled={busy || !problem.trim() || !run}
                          onClick={() =>
                            act(() => reportTestProblem(cardKey, problem.trim())).then((ok) => ok && setProblem(''))
                          }
                        >
                          Send startup issue report
                        </Button>
                      </Box>
                    </Stack>
                  )}
                </Stack>
              </AccordionDetails>
            </Accordion>
          ) : null}
          {!run && !error && (
            <Typography color="text.secondary">Manual testing has not been started.</Typography>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
