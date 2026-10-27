import SyncIcon from '@mui/icons-material/Sync'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardActionArea from '@mui/material/CardActionArea'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useCallback, useEffect, useState } from 'react'
import Box from '@mui/material/Box'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import StepButton, { type StepStatus } from './StepButton'
import {
  fetchAiConfig,
  fetchCards,
  fetchImplementationStates,
  fetchPlanStates,
  fetchReviewStates,
  generatePlan,
  startReview,
  startImplementation,
  type AiConfig,
  type Card as JiraCard,
  type ImplState,
  type PlanState,
  type ReviewState,
} from '../api'

function isEligible(config: AiConfig | null, status: string) {
  const wanted = status.trim().toLowerCase()
  return !!config?.eligible_statuses.some((s) => s.trim().toLowerCase() === wanted)
}

function planStep(plan: PlanState | undefined, eligible: boolean): StepStatus {
  if (plan === 'approved') return 'done'
  if (plan === 'running') return 'running'
  if (plan === 'ready') return 'next'
  return eligible ? 'next' : 'blocked'
}

function reviewStep(impl: ImplState | undefined, review: ReviewState | undefined): StepStatus {
  if (review === 'clean') return 'done'
  if (review === 'running') return 'running'
  return impl === 'completed' ? 'next' : 'blocked'
}

function implementStep(plan: PlanState | undefined, impl: ImplState | undefined, canRun: boolean): StepStatus {
  if (impl === 'completed') return 'done'
  if (impl === 'running') return 'running'
  return plan === 'approved' && canRun ? 'next' : 'blocked'
}

export default function Home() {
  const [cards, setCards] = useState<JiraCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [plans, setPlans] = useState<Record<string, PlanState>>({})
  const [reviews, setReviews] = useState<Record<string, ReviewState>>({})
  const [impls, setImpls] = useState<Record<string, ImplState>>({})
  const [config, setConfig] = useState<AiConfig | null>(null)

  const navigate = useNavigate()
  const [actionError, setActionError] = useState<string | null>(null)

  async function run(fn: () => Promise<unknown>, onDone: () => void) {
    setActionError(null)
    try {
      await fn()
      onDone()
    } catch (e) {
      setActionError((e as Error).message)
    }
  }

  const sync = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setCards(await fetchCards())
      // Plan info only decorates the list, so failures here are not fatal.
      const [p, im, rv, cfg] = await Promise.all([
        fetchPlanStates().catch(() => ({})),
        fetchImplementationStates().catch(() => ({})),
        fetchReviewStates().catch(() => ({})),
        fetchAiConfig().catch(() => null),
      ])
      setPlans(p)
      setImpls(im)
      setReviews(rv)
      setConfig(cfg)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    sync()
  }, [sync])

  // A card is in progress once it has a plan in any state.
  const sections = cards?.length
    ? [
        { title: 'In Progress', items: cards.filter((c) => plans[c.key]) },
        { title: 'To Do', items: cards.filter((c) => !plans[c.key]) },
      ]
    : []

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
        <Typography variant="h4" component="h1">
          CAIrdboard
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
                isEligible(config, card.status) && !!config?.project_repos[card.project],
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
          </Box>
          <CardActionArea component={RouterLink} to={`/cards/${card.key}`}>
            <CardContent>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <Typography component="span" sx={{ fontWeight: 'bold' }}>
                {card.key}
              </Typography>
              <Chip label={card.status} size="small" />
              {card.priority && <Chip label={card.priority} size="small" color="warning" />}
              {plans[card.key] === 'approved' && impls[card.key] === 'completed' ? (
                <Chip
                  label={`Review: ${reviews[card.key] ?? 'available'}`}
                  size="small"
                  color={reviews[card.key] ? undefined : 'primary'}
                  variant="outlined"
                />
              ) : plans[card.key] === 'approved' ? (
                <Chip
                  label={`Implementation: ${impls[card.key] ?? 'available'}`}
                  size="small"
                  color={impls[card.key] ? undefined : 'primary'}
                  variant="outlined"
                />
              ) : (
                plans[card.key] && (
                  <Chip label={`Plan: ${plans[card.key]}`} size="small" variant="outlined" />
                )
              )}
              {!plans[card.key] && isEligible(config, card.status) && (
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
