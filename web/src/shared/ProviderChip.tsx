import Chip from '@mui/material/Chip'
import { AI_PROVIDER_LABELS, type AiProviderId } from '../api'

/** Which AI produced a run; nothing for runs that used no AI. */
export default function ProviderChip({ provider }: { provider?: string | null }) {
  if (!provider) return null
  const label = AI_PROVIDER_LABELS[provider as AiProviderId] ?? provider
  return <Chip label={`via ${label}`} size="small" variant="outlined" />
}
