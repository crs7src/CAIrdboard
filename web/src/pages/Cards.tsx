import SyncIcon from '@mui/icons-material/Sync'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Link from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useCallback, useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  fetchAiConfig,
  fetchCards,
  fetchPlanStates,
  type AiConfig,
  type Card as JiraCard,
  type PlanState,
} from '../api'

function isEligible(config: AiConfig | null, status: string) {
  const wanted = status.trim().toLowerCase()
  return !!config?.eligible_statuses.some((s) => s.trim().toLowerCase() === wanted)
}

export default function Cards() {
  const [cards, setCards] = useState<JiraCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [plans, setPlans] = useState<Record<string, PlanState>>({})
  const [config, setConfig] = useState<AiConfig | null>(null)

  const sync = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setCards(await fetchCards())
      // Plan info only decorates the list, so failures here are not fatal.
      const [p, cfg] = await Promise.all([
        fetchPlanStates().catch(() => ({})),
        fetchAiConfig().catch(() => null),
      ])
      setPlans(p)
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
      {cards?.length === 0 && <Alert severity="info" role="note">No cards assigned to you.</Alert>}
      {cards?.map((card) => (
        <Card key={card.key} variant="outlined">
          <CardContent>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <Link component={RouterLink} to={`/cards/${card.key}`} sx={{ fontWeight: 'bold' }}>
                {card.key}
              </Link>
              <Chip label={card.status} size="small" />
              {card.priority && <Chip label={card.priority} size="small" color="warning" />}
              {plans[card.key] && <Chip label={`Plan: ${plans[card.key]}`} size="small" variant="outlined" />}
              {!plans[card.key] && isEligible(config, card.status) && (
                <Button size="small" component={RouterLink} to={`/cards/${card.key}`}>
                  Plan
                </Button>
              )}
            </Stack>
            <Typography sx={{ mt: 1 }}>{card.summary}</Typography>
          </CardContent>
        </Card>
      ))}
    </Stack>
  )
}
