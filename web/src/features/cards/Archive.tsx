import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Link from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import UnarchiveIcon from '@mui/icons-material/Unarchive'
import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { fetchArchive, fetchCardList, unarchiveCard, type Card as JiraCard } from '../../api'

export default function Archive() {
  const [cards, setCards] = useState<JiraCard[] | null>(null)
  const [keys, setKeys] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchCardList(), fetchArchive()])
      .then(([list, archived]) => {
        if (cancelled) return
        setCards(list.cards)
        setKeys(archived)
      })
      .catch((e) => !cancelled && setError((e as Error).message))
    return () => {
      cancelled = true
    }
  }, [])

  async function restore(key: string) {
    setError(null)
    try {
      await unarchiveCard(key)
      setKeys((k) => k.filter((x) => x !== key))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // Archived keys whose card is no longer assigned to the user are still listed, by key only.
  const known = new Map((cards ?? []).map((c) => [c.key, c]))

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="h4" component="h1">
          Archive
        </Typography>
        <Button component={RouterLink} to="/">
          Back to cards
        </Button>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {cards && keys.length === 0 && (
        <Alert severity="info" role="note">
          No archived cards.
        </Alert>
      )}
      {cards &&
        keys.map((key) => {
          const card = known.get(key)
          return (
            <Card key={key} variant="outlined">
              <CardContent>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                  <Link component={RouterLink} to={`/cards/${key}`} sx={{ fontWeight: 'bold' }}>
                    {key}
                  </Link>
                  {card && <Chip label={card.status} size="small" />}
                  <Typography sx={{ flexGrow: 1 }}>{card?.summary}</Typography>
                  <Button
                    size="small"
                    startIcon={<UnarchiveIcon />}
                    aria-label={`Unarchive ${key}`}
                    onClick={() => restore(key)}
                  >
                    Unarchive
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          )
        })}
    </Stack>
  )
}
