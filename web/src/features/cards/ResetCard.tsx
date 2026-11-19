import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import { useState } from 'react'
import { dismissReopenPrompt, resetCard } from '../../api'

interface Props {
  cardKey: string
  onReset: () => void
  onError: (message: string) => void
}

export function ReopenNotice({
  cardKey,
  onReset,
  onDismiss,
  onError,
}: Props & { onDismiss: () => void }) {
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<unknown>, done: () => void) => {
    setBusy(true)
    try {
      await fn()
      done()
    } catch (e) {
      onError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Alert
      severity="warning"
      role="note"
      action={
        <>
          <Button
            color="inherit"
            size="small"
            disabled={busy}
            onClick={() => run(() => resetCard(cardKey, true), onReset)}
          >
            Yes
          </Button>
          <Button
            color="inherit"
            size="small"
            disabled={busy}
            onClick={() => run(() => dismissReopenPrompt(cardKey), onDismiss)}
          >
            No
          </Button>
        </>
      }
    >
      This card has been reopened since the last change. Do you want it reset to work on the new
      requested changes?
    </Alert>
  )
}

export function ResetButton({ cardKey, onReset, onError, disabled }: Props & { disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const confirm = async () => {
    setBusy(true)
    try {
      await resetCard(cardKey, true)
      setOpen(false)
      onReset()
    } catch (e) {
      setOpen(false)
      onError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button
        color="error"
        variant="outlined"
        disabled={disabled}
        sx={{ ml: 'auto' }}
        onClick={() => setOpen(true)}
      >
        Reset card
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)}>
        <DialogTitle>Reset {cardKey}?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This deletes the card&apos;s local branch (unpushed commits are lost; the remote branch
            and any merge request are kept) and clears all of its plans, runs and comments.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button color="error" onClick={confirm} disabled={busy}>
            Reset
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
