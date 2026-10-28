import Brand from '../Brand'
import SyncIcon from '@mui/icons-material/Sync'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardActionArea from '@mui/material/CardActionArea'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useCallback, useEffect, useRef, useState } from 'react'
import Box from '@mui/material/Box'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import StepButton, { type StepStatus } from './StepButton'
import {
  fetchAiConfig,
  fetchCardList,
  fetchImplementationStates,
  fetchPlanStates,
  fetchReviewStates,
  fetchTestStates,
  fetchConfiguredTestProjects,
  fetchTestApprovals,
  fetchMergeRequestStates,
  startMergeRequest,
  type MergeRequestState,
  startTest,
  type TestState,
  generatePlan,
  startReview,
  startImplementation,
  type AiConfig,
  type Card as JiraCard,
  type ImplState,
  type PlanState,
  type ReviewState,
} from '../api'

const POLL_MS = 3000

function isEligible(config: AiConfig | null, status: string, source?: string) {
  if (source === 'github' && status === 'Open') return true
  const wanted = status.trim().toLowerCase()
  return !!config?.eligible_statuses.some((s) => s.trim().toLowerCase() === wanted)
}

function planStep(plan: PlanState | undefined, eligible: boolean): StepStatus {
  if (plan === 'approved') return 'done'
  if (plan === 'running') return 'running'
  if (plan === 'failed') return 'failed'
  if (plan === 'ready') return 'next'
  return eligible ? 'next' : 'blocked'
}

function reviewStep(impl: ImplState | undefined, review: ReviewState | undefined): StepStatus {
  if (review === 'clean') return 'done'
  if (review === 'running') return 'running'
  if (review === 'failed') return 'failed'
  return impl === 'completed' ? 'next' : 'blocked'
}

function testStep(
  review: ReviewState | undefined,
  test: TestState | undefined,
  configured: boolean,
  approved: boolean,
): StepStatus {
  if (approved || test === 'running') return 'done'
  if (test === 'preparing') return 'running'
  if (test === 'failed') return 'failed'
  return review === 'clean' && configured ? 'next' : 'blocked'
}

function mergeRequestStep(mr: MergeRequestState | 'outdated' | undefined, approved: boolean): StepStatus {
  if (mr === 'created') return 'done'
  if (mr === 'running') return 'running'
  if (mr === 'failed') return 'failed'
  return approved ? 'next' : 'blocked'
}

function implementStep(plan: PlanState | undefined, impl: ImplState | undefined, canRun: boolean): StepStatus {
  if (impl === 'completed') return 'done'
  if (impl === 'running') return 'running'
  if (impl === 'failed') return 'failed'
  return plan === 'approved' && canRun ? 'next' : 'blocked'
}

export default function Home() {
  const [warning, setWarning] = useState<string | null>(null)
  const [cards, setCards] = useState<JiraCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [plans, setPlans] = useState<Record<string, PlanState>>({})
  const [reviews, setReviews] = useState<Record<string, ReviewState>>({})
  const [tests, setTests] = useState<Record<string, TestState>>({})
  const [testProjects, setTestProjects] = useState<string[]>([])
  const [approvals, setApprovals] = useState<string[]>([])
  const [mrs, setMrs] = useState<Record<string, MergeRequestState | 'outdated'>>({})
  const [impls, setImpls] = useState<Record<string, ImplState>>({})
  const [config, setConfig] = useState<AiConfig | null>(null)

  const navigate = useNavigate()
  const [actionError, setActionError] = useState<string | null>(null)
  const refreshing = useRef(false)

  async function run(fn: () => Promise<unknown>, onDone: () => void) {
    setActionError(null)
    try {
      await fn()
      onDone()
    } catch (e) {
      setActionError((e as Error).message)
    }
  }

  const refreshStates = useCallback(async () => {
    if (refreshing.current) return
    refreshing.current = true
    try {
      const [p, im, rv, ts, ap, mr] = await Promise.all([
        fetchPlanStates().catch(() => null),
        fetchImplementationStates().catch(() => null),
        fetchReviewStates().catch(() => null),
        fetchTestStates().catch(() => null),
        fetchTestApprovals().catch(() => null),
        fetchMergeRequestStates().catch(() => null),
      ])
      // A failed poll keeps the last known state instead of clearing it.
      if (p) setPlans(p)
      if (im) setImpls(im)
      if (rv) setReviews(rv)
      if (ts) setTests(ts)
      if (ap) setApprovals(ap)
      if (mr) setMrs(mr)
    } finally {
      refreshing.current = false
    }
  }, [])

  const sync = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await fetchCardList()
      setCards(list.cards)
      setWarning(list.warning)
      // Plan info only decorates the list, so failures here are not fatal.
      const [cfg, tp] = await Promise.all([
        fetchAiConfig().catch(() => null),
        fetchConfiguredTestProjects().catch(() => []),
        refreshStates(),
      ])
      setConfig(cfg)
      setTestProjects(tp)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [refreshStates])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    sync()
  }, [sync])

  const active =
    Object.values(plans).includes('running') ||
    Object.values(impls).includes('running') ||
    Object.values(reviews).includes('running') ||
    Object.values(tests).includes('preparing') ||
    Object.values(mrs).includes('running')

  useEffect(() => {
    if (!active) return
    const id = setInterval(refreshStates, POLL_MS)
    return () => clearInterval(id)
  }, [active, refreshStates])

  // An ineligible status is always In Review/Done; otherwise a plan in any state means In Progress.
  // If the config could not be loaded, every card is treated as eligible.
  const inTodo = (c: JiraCard) => !config || isEligible(config, c.status, c.source)
  const sections = cards?.length
    ? [
        { title: 'In Progress', items: cards.filter((c) => plans[c.key] && inTodo(c)) },
        { title: 'To Do', items: cards.filter((c) => !plans[c.key] && inTodo(c)) },
        { title: 'In Review/Done', items: cards.filter((c) => !inTodo(c)) },
      ].filter((s) => s.title !== 'In Review/Done' || s.items.length > 0)
    : []

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
        <Typography variant="h4" component="h1">
          <Brand />
        </Typography>
        <Button variant="contained" startIcon={<SyncIcon />} onClick={sync} disabled={loading}>
          {loading ? 'Syncing...' : 'Sync'}
        </Button>
      </Stack>
      {error && (
        <Alert
          severity="error"
          action={
            <Button color="inherit" size="small" component={RouterLink} to="/settings/jira">
              Update your Jira settings
            </Button>
          }
        >
          {error}
        </Alert>
      )}
      {warning && <Alert severity="warning" role="note">Some cards could not be loaded: {warning}</Alert>}
      {actionError && <Alert severity="error">{actionError}</Alert>}
      {cards?.length === 0 && <Alert severity="info" role="note">No cards assigned to you.</Alert>}
      {sections.map(({ title, items }) => (
        <Stack key={title} component="section" spacing={2} aria-label={title}>
          <Typography variant="h5" component="h2">
            {title}
          </Typography>
          {items.length === 0 && (
            <Typography color="text.secondary">No cards.</Typography>
          )}
          {items.map((card) => (
        <Card key={card.key} variant="outlined" sx={{ position: 'relative' }}>
          <Box sx={{ position: 'absolute', top: 8, right: 8, zIndex: 1, display: 'flex' }}>
            <StepButton
              label="Plan"
              status={planStep(
                plans[card.key],
                isEligible(config, card.status, card.source) && !!config?.project_repos[card.project],
              )}
              onRun={() =>
                plans[card.key] === 'ready'
                  ? navigate(`/cards/${card.key}?open=plan`)
                  : run(
                  () => generatePlan(card.key),
                  () => setPlans((p) => ({ ...p, [card.key]: 'running' })),
                )
              }
            />
            <StepButton
              label="Implement"
              status={implementStep(plans[card.key], impls[card.key], !!config?.project_repos[card.project])}
              onRun={() =>
                run(
                  () => startImplementation(card.key),
                  () => setImpls((i) => ({ ...i, [card.key]: 'running' })),
                )
              }
            />
            <StepButton
              label="Review"
              status={reviewStep(impls[card.key], reviews[card.key])}
              onRun={() =>
                run(
                  () => startReview(card.key),
                  () => setReviews((r) => ({ ...r, [card.key]: 'running' })),
                )
              }
            />
            <StepButton
              label="Test"
              status={testStep(reviews[card.key], tests[card.key], testProjects.includes(card.project), approvals.includes(card.key))}
              onRun={() =>
                run(
                  () => startTest(card.key),
                  () => setTests((t) => ({ ...t, [card.key]: 'preparing' })),
                )
              }
            />
            <StepButton
              label="Create MR"
              status={mergeRequestStep(mrs[card.key], approvals.includes(card.key))}
              onRun={() =>
                run(
                  () => startMergeRequest(card.key),
                  () => setMrs((m) => ({ ...m, [card.key]: 'running' })),
                )
              }
            />
          </Box>
          <CardActionArea component={RouterLink} to={`/cards/${card.key}`}>
            <CardContent>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <Typography component="span" sx={{ fontWeight: 'bold' }}>
                {card.key}
              </Typography>
              <Chip label={card.status} size="small" />
              {card.priority && <Chip label={card.priority} size="small" color="warning" />}
              {reviews[card.key] === 'clean' ? (
                <Chip
                  label={`Test: ${approvals.includes(card.key) ? 'approved' : (tests[card.key] ?? 'available')}`}
                  size="small"
                  color={
                    approvals.includes(card.key)
                      ? 'success'
                      : tests[card.key] === 'failed'
                        ? 'error'
                        : tests[card.key]
                          ? undefined
                          : 'primary'
                  }
                  variant="outlined"
                />
              ) : plans[card.key] === 'approved' && impls[card.key] === 'completed' ? (
                <Chip
                  label={`Review: ${reviews[card.key] ?? 'available'}`}
                  size="small"
                  color={reviews[card.key] === 'failed' ? 'error' : reviews[card.key] ? undefined : 'primary'}
                  variant="outlined"
                />
              ) : plans[card.key] === 'approved' ? (
                <Chip
                  label={`Implementation: ${impls[card.key] ?? 'available'}`}
                  size="small"
                  color={impls[card.key] === 'failed' ? 'error' : impls[card.key] ? undefined : 'primary'}
                  variant="outlined"
                />
              ) : (
                plans[card.key] && (
                  <Chip
                    label={`Plan: ${plans[card.key]}`}
                    size="small"
                    color={plans[card.key] === 'failed' ? 'error' : undefined}
                    variant="outlined"
                  />
                )
              )}
              {!plans[card.key] && isEligible(config, card.status, card.source) && (
                <Chip label="Plan: available" size="small" color="primary" variant="outlined" />
              )}
            </Stack>
            <Typography sx={{ mt: 1 }}>{card.summary}</Typography>
            </CardContent>
          </CardActionArea>
        </Card>
          ))}
        </Stack>
      ))}
    </Stack>
  )
}
