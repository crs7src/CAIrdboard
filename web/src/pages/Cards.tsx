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
  generatePlan,
  startImplementation,
  type AiConfig,
  type Card as JiraCard,
  type ImplState,
  type PlanState,
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

function implementStep(plan: PlanState | undefined, impl: ImplState | undefined, canRun: boolean): StepStatus {
  if (impl === 'completed') return 'done'
  if (impl === 'running') return 'running'
  return plan === 'approved' && canRun ? 'next' : 'blocked'
}

export default function Cards() {
  const [cards, setCards] = useState<JiraCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [plans, setPlans] = useState<Record<string, PlanState>>({})
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
      const [p, im, cfg] = await Promise.all([
        fetchPlanStates().catch(() => ({})),
        fetchImplementationStates().catch(() => ({})),
        fetchAiConfig().catch(() => null),
      ])
      setPlans(p)
      setImpls(im)
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

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
        <Typography variant="h4" component="h1">
          My Cards
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
      {cards?.map((card) => (
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
            <StepButton label="Review" status="blocked" />
          </Box>
          <CardActionArea component={RouterLink} to={`/cards/${card.key}`}>
            <CardContent>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <Typography component="span" sx={{ fontWeight: 'bold' }}>
                {card.key}
              </Typography>
              <Chip label={card.status} size="small" />
              {card.priority && <Chip label={card.priority} size="small" color="warning" />}
              {plans[card.key] === 'approved' ? (
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
  )
}
