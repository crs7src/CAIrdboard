import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import MenuItem from '@mui/material/MenuItem'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useEffect, useState, type FormEvent } from 'react'
import {
  checkAiProvider,
  fetchAiProviders,
  removeAiProviderKey,
  saveAiProvider,
  setDefaultAiProvider,
  type AiProvider,
  type AiProviderId,
} from '../../api'

interface CardProps {
  provider: AiProvider
  onChanged: (p: AiProvider) => void
}

function ProviderCard({ provider, onChanged }: CardProps) {
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(provider.model ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function run(action: () => Promise<string>) {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      setMessage(await action())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const modelChanged = model !== (provider.model ?? '')
  const canSave = apiKey.trim() !== '' || modelChanged

  function save(e: FormEvent) {
    e.preventDefault()
    void run(async () => {
      const update: { api_key?: string; model?: string } = {}
      if (apiKey.trim()) update.api_key = apiKey.trim()
      if (modelChanged) update.model = model
      const saved = await saveAiProvider(provider.id, update)
      setApiKey('')
      setModel(saved.model ?? '')
      onChanged(saved)
      return 'Saved.'
    })
  }

  const options = model && !provider.models.includes(model) ? [model, ...provider.models] : provider.models
  const modelSelect = (
    <TextField
      select
      label="Model"
      helperText={
        provider.default_model
          ? `Default: ${provider.default_model}`
          : 'Default: the CLI\'s own default model'
      }
      value={model}
      onChange={(e) => setModel(e.target.value)}
    >
      <MenuItem value="">Default</MenuItem>
      {options.map((m) => (
        <MenuItem key={m} value={m}>
          {m}
        </MenuItem>
      ))}
    </TextField>
  )

  return (
    <Paper variant="outlined" sx={{ p: 2 }} component="form" onSubmit={save}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Typography variant="h6" component="h2">
            {provider.label}
          </Typography>
          <Chip
            size="small"
            color={provider.configured ? 'success' : 'default'}
            label={provider.configured ? 'configured' : 'not configured'}
          />
          {provider.is_default && <Chip size="small" color="primary" label="default" />}
        </Stack>
        {!provider.needs_key ? (
          <>
            <Typography variant="body2" color="text.secondary">
              Runs the copilot command on this machine with your signed-in GitHub account. No API key is needed, and
              it is the only provider that can implement, review and address feedback for now.
            </Typography>
            {modelSelect}
            <Stack direction="row" spacing={1}>
              <Button type="submit" variant="contained" disabled={busy || !canSave}>
                Save
              </Button>
            </Stack>
          </>
        ) : (
          <>
            <Typography variant="body2" color="text.secondary">
              Calls the API directly with your own key (billed per token by the provider, not by Copilot). Used for
              plans, branch names and manual test setup. The key is stored on this machine and never shown again.
            </Typography>
            <TextField
              label={`${provider.label} API key`}
              type="password"
              autoComplete="off"
              placeholder={provider.configured ? 'Leave blank to keep the current key' : ''}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            {modelSelect}
            <Stack direction="row" spacing={1}>
              <Button type="submit" variant="contained" disabled={busy || !canSave}>
                Save
              </Button>
              <Button
                disabled={busy || !provider.configured}
                onClick={() =>
                  void run(async () => {
                    await checkAiProvider(provider.id)
                    return 'The key works.'
                  })
                }
              >
                Verify
              </Button>
              <Button
                color="error"
                disabled={busy || !provider.configured}
                onClick={() =>
                  void run(async () => {
                    onChanged(await removeAiProviderKey(provider.id))
                    return 'Saved key removed.'
                  })
                }
              >
                Remove key
              </Button>
            </Stack>
          </>
        )}
        {message && (
          <Alert severity="success" role="status">
            {message}
          </Alert>
        )}
        {error && <Alert severity="error">{error}</Alert>}
      </Stack>
    </Paper>
  )
}

export default function AiProvidersSettings() {
  const [providers, setProviders] = useState<AiProvider[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchAiProviders().then(setProviders, (e: Error) => setError(e.message))
  }, [])

  function replace(updated: AiProvider) {
    setProviders((list) => list?.map((p) => (p.id === updated.id ? updated : p)) ?? null)
  }

  async function changeDefault(id: AiProviderId) {
    setError(null)
    try {
      await setDefaultAiProvider(id)
      setProviders((list) => list?.map((p) => ({ ...p, is_default: p.id === id })) ?? null)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const current = providers?.find((p) => p.is_default)
  return (
    <Stack spacing={2} sx={{ maxWidth: 720 }}>
      <Typography variant="h6" component="h2">
        AI providers
      </Typography>
      <Alert severity="info" role="note">
        Projects use the default provider unless you pick another in the Projects page. Anthropic and Google Gemini
        can run every stage, including implement, review and feedback, with confined file-edit and shell tools.
      </Alert>
      {error && <Alert severity="error">{error}</Alert>}
      {providers && current && (
        <TextField
          select
          label="Default provider"
          value={current.id}
          onChange={(e) => void changeDefault(e.target.value as AiProviderId)}
        >
          {providers.map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.label}
            </MenuItem>
          ))}
        </TextField>
      )}
      {providers?.map((p) => (
        <ProviderCard key={p.id} provider={p} onChanged={replace} />
      ))}
    </Stack>
  )
}
