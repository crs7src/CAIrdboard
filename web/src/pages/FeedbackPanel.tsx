import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useState } from 'react'
import type { FeedbackComment, FeedbackRun } from '../api'

function commentLocation(c: FeedbackComment) {
  if (!c.file) return 'General'
  return c.line ? `${c.file}:${c.line}${c.side === 'old' ? ' (removed line)' : ''}` : c.file
}

export function CommentCard({
  comment,
  onEdit,
  onDelete,
  showLocation = true,
}: {
  comment: FeedbackComment
  onEdit?: (text: string) => Promise<boolean>
  onDelete?: () => Promise<unknown>
  showLocation?: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(comment.text)

  return (
    <Paper variant="outlined" sx={{ p: 1, width: '100%' }}>
      {showLocation && (
        <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
          {commentLocation(comment)}
        </Typography>
      )}
      {editing ? (
        <Stack spacing={1}>
          <TextField
            size="small"
            multiline
            fullWidth
            label="Edit comment"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              variant="contained"
              disabled={!text.trim()}
              onClick={async () => {
                if (await onEdit?.(text)) setEditing(false)
              }}
            >
              Save comment
            </Button>
            <Button
              size="small"
              onClick={() => {
                setText(comment.text)
                setEditing(false)
              }}
            >
              Cancel
            </Button>
          </Stack>
        </Stack>
      ) : (
        <Stack direction="row" sx={{ alignItems: 'flex-start' }}>
          <Typography variant="body2" sx={{ flex: 1, whiteSpace: 'pre-wrap' }}>
            {comment.text}
          </Typography>
          {onEdit && (
            <IconButton size="small" aria-label="Edit comment" onClick={() => setEditing(true)}>
              <EditIcon fontSize="small" />
            </IconButton>
          )}
          {onDelete && (
            <IconButton size="small" aria-label="Delete comment" onClick={onDelete}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          )}
        </Stack>
      )}
    </Paper>
  )
}

export function Composer({
  label,
  onAdd,
  onCancel,
}: {
  label: string
  onAdd: (text: string) => Promise<boolean>
  onCancel?: () => void
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  return (
    <Stack spacing={1} sx={{ p: 1, width: '100%', bgcolor: 'background.paper' }}>
      <TextField
        size="small"
        multiline
        fullWidth
        label={label}
        value={text}
        onChange={(e) => setText(e.target.value)}
        autoFocus={!!onCancel}
      />
      <Stack direction="row" spacing={1}>
        <Button
          size="small"
          variant="contained"
          disabled={busy || !text.trim()}
          onClick={async () => {
            setBusy(true)
            try {
              if (await onAdd(text)) setText('')
            } finally {
              setBusy(false)
            }
          }}
        >
          Add comment
        </Button>
        {onCancel && (
          <Button size="small" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </Stack>
    </Stack>
  )
}

export default function FeedbackPanel({
  comments,
  run,
  error,
  submitting,
  onAdd,
  onEdit,
  onDelete,
  onSubmit,
}: {
  comments: FeedbackComment[]
  run: FeedbackRun | null
  error: string | null
  submitting: boolean
  onAdd: (text: string) => Promise<boolean>
  onEdit: (id: string, text: string) => Promise<boolean>
  onDelete: (id: string) => Promise<unknown>
  onSubmit: () => Promise<unknown>
}) {
  const pending = comments.filter((c) => c.status === 'pending')
  const resolved = comments.filter((c) => c.status === 'resolved')
  const running = run?.state === 'running'

  return (
    <Paper
      component="aside"
      variant="outlined"
      aria-label="Review feedback"
      sx={{ width: 340, flexShrink: 0, p: 1.5, overflowY: 'auto' }}
    >
      <Stack spacing={1.5}>
        <Typography variant="h6" component="h2">
          Review feedback
        </Typography>
        {error && <Alert severity="error">{error}</Alert>}
        {running && (
          <Alert severity="info" icon={<CircularProgress size={18} />}>
            An AI is making the requested changes...
          </Alert>
        )}
        {run?.state === 'failed' && <Alert severity="error">{run.error}</Alert>}
        {run?.state === 'done' && (
          <Alert severity="success">
            Changes made ({run.commits.length} {run.commits.length === 1 ? 'commit' : 'commits'}).
            {run.notes.map((n) => (
              <Box key={n}>{n}</Box>
            ))}
          </Alert>
        )}
        {run?.state === 'done' && run.report && (
          <Accordion disableGutters variant="outlined">
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>Agent report</AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                {run.report}
              </Typography>
            </AccordionDetails>
          </Accordion>
        )}

        <Composer label="General comment" onAdd={onAdd} />
        <Typography variant="body2" color="text.secondary">
          To comment on a line, click its line number in the diff (All changes view).
        </Typography>

        <Typography variant="subtitle2" component="h3">
          Pending comments ({pending.length})
        </Typography>
        {pending.map((c) => (
          <CommentCard
            key={c.id}
            comment={c}
            onEdit={(text) => onEdit(c.id, text)}
            onDelete={() => onDelete(c.id)}
          />
        ))}
        <Button
          variant="contained"
          disabled={pending.length === 0 || running || submitting}
          onClick={onSubmit}
        >
          Submit for changes
        </Button>

        {resolved.length > 0 && (
          <Accordion disableGutters variant="outlined">
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              Resolved ({resolved.length})
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1}>
                {resolved.map((c) => (
                  <CommentCard key={c.id} comment={c} />
                ))}
              </Stack>
            </AccordionDetails>
          </Accordion>
        )}
      </Stack>
    </Paper>
  )
}
