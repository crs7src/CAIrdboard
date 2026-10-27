import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Link from '@mui/material/Link'
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
  fetchTestConfig,
  forgetTestConfig,
  reportTestProblem,
  startTest,
  stopTest,
  type TestConfig,
  type TestRun,
} from '../api'
import StepButton from './StepButton'

export const TEST_POLL_MS = 3000

const STATE_LABEL = {
  preparing: 'starting the app',
  running: 'app running',
  stopped: 'stopped',
  failed: 'failed',
}

export default function Test({ cardKey }: { cardKey: string }) {
  const [run, setRun] = useState<TestRun | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<TestConfig | null>(null)
  const [problem, setProblem] = useState('')

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

  const preparing = run?.state === 'preparing'

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
          <Box sx={{ flexGrow: 1 }} />
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
          {!preparing && (config || run) && (
            <Stack spacing={1}>
              <TextField
                label="Describe what is not running right"
                size="small"
                multiline
                minRows={2}
                value={problem}
                onChange={(e) => setProblem(e.target.value)}
                helperText="An AI will fix how the apps are started (not the code) and restart them."
              />
              <Stack direction="row" spacing={1}>
                <Button
                  variant="contained"
                  disabled={busy || !problem.trim() || !run}
                  onClick={() => act(() => reportTestProblem(cardKey, problem.trim())).then((ok) => ok && setProblem(''))}
                >
                  Send problem report
                </Button>
                {config && (
                  <Button color="inherit" disabled={busy} onClick={forget}>
                    Forget saved settings
                  </Button>
                )}
              </Stack>
            </Stack>
          )}
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
          {!run && !error && (
            <Typography color="text.secondary">Manual testing has not been started.</Typography>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
