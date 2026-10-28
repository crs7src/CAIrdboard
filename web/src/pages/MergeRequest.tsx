import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import Link from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useEffect, useState } from 'react'
import { fetchMergeRequest, fetchRepoHost, startMergeRequest, type MergeRequest as MrData, type RepoProvider } from '../api'
import StepButton from './StepButton'

export const MR_POLL_MS = 3000

export default function MergeRequest({ cardKey, approved }: { cardKey: string; approved: boolean }) {
  const [mr, setMr] = useState<MrData | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hostProvider, setHostProvider] = useState<RepoProvider>('gitlab')

  useEffect(() => {
    fetchMergeRequest(cardKey).then(
      (r) => {
        setMr(r)
        setLoaded(true)
      },
      (e: Error) => {
        setError(e.message)
        setLoaded(true)
      },
    )
  }, [cardKey, approved])

  // GitHub calls it a pull request; fall back to the GitLab wording if the host is unknown.
  useEffect(() => {
    fetchRepoHost(cardKey.split('-')[0]).then(
      (h) => h.provider && setHostProvider(h.provider),
      () => {},
    )
  }, [cardKey])
  const provider = mr?.provider ?? hostProvider
  const noun = provider === 'github' ? 'pull request' : 'merge request'
  const Noun = noun[0].toUpperCase() + noun.slice(1)

  const running = mr?.state === 'running'
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => {
      fetchMergeRequest(cardKey).then(setMr, (e: Error) => setError(e.message))
    }, MR_POLL_MS)
    return () => clearInterval(id)
  }, [running, cardKey])

  async function start() {
    setBusy(true)
    setError(null)
    try {
      setMr(await startMergeRequest(cardKey))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // Nothing to show until the test is approved, unless a merge request already exists.
  if (!loaded || (!mr && !approved)) return null

  const upToDate = mr?.state === 'created' && !mr.outdated
  const label = mr?.mr_url ? 'Push updates' : `Create ${noun}`
  const chip = !mr
    ? 'not created'
    : running
      ? 'creating'
      : mr.state === 'failed'
        ? 'failed'
        : mr.outdated
          ? 'has new commits'
          : 'created'

  return (
    <Accordion disableGutters aria-label={Noun} defaultExpanded={!upToDate}>
      <AccordionSummary component="div" expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexGrow: 1, minWidth: 0 }}>
          <Typography variant="h6" component="h2">
            {Noun}
          </Typography>
          <Chip
            label={chip}
            size="small"
            color={upToDate ? 'success' : mr?.state === 'failed' ? 'error' : mr?.outdated ? 'warning' : 'default'}
          />
          <Box sx={{ flexGrow: 1 }} />
          {!upToDate && (
            <span onClick={(e) => e.stopPropagation()}>
              <StepButton
                label={label}
                status={running ? 'running' : busy || !approved ? 'blocked' : 'next'}
                onRun={start}
              />
            </span>
          )}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          {running && <Typography>Pushing the branch and creating the {noun}...</Typography>}
          {mr?.mr_url && (
            <Typography>
              <Link href={mr.mr_url} target="_blank" rel="noreferrer">
                {`${provider === 'github' ? '#' : '!'}${mr.mr_iid} ${mr.title}`}
              </Link>
              {` (${mr.branch} → ${mr.target_branch})`}
            </Typography>
          )}
          {mr?.outdated && (
            <Alert severity="warning" role="note">
              The branch has new commits since the last push.
              {approved ? ` Push the updates to the ${noun}.` : ' Approve the manual test again to push them.'}
            </Alert>
          )}
          {mr?.state === 'failed' && <Alert severity="error">{mr.error}</Alert>}
          {error && <Alert severity="error">{error}</Alert>}
          {!mr && !error && (
            <Typography color="text.secondary">
              Pushes the branch to origin and opens a {noun} into the base branch.
            </Typography>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
