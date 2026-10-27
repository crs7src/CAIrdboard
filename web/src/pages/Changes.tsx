import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import List from '@mui/material/List'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import MenuItem from '@mui/material/MenuItem'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Diff,
  Hunk,
  getChangeKey,
  isDelete,
  isNormal,
  parseDiff,
  type ChangeData,
  type FileData,
} from 'react-diff-view'
import 'react-diff-view/style/index.css'
import { Link as RouterLink, useParams } from 'react-router-dom'
import {
  addFeedbackComment,
  deleteFeedbackComment,
  editFeedbackComment,
  fetchChanges,
  fetchFeedback,
  submitFeedback,
  type Changes as ChangesData,
  type Feedback,
  type FeedbackComment,
  type FeedbackCommentInput,
} from '../api'
import FeedbackPanel, { CommentCard, Composer } from './FeedbackPanel'

const STATUS: Record<string, { label: string; color: 'success' | 'error' | 'warning' | 'default' }> = {
  add: { label: 'added', color: 'success' },
  delete: { label: 'deleted', color: 'error' },
  modify: { label: 'modified', color: 'warning' },
  rename: { label: 'renamed', color: 'default' },
  copy: { label: 'copied', color: 'default' },
}

function filePath(file: FileData) {
  if (file.type === 'delete') return file.oldPath
  if (file.type === 'rename' || file.type === 'copy') return `${file.oldPath} → ${file.newPath}`
  return file.newPath
}

// The path a comment is filed under: the file's real path, not the rename label.
function commentPath(file: FileData) {
  return file.type === 'delete' ? file.oldPath : file.newPath
}

function lineOf(change: ChangeData) {
  return isNormal(change) ? change.newLineNumber : change.lineNumber
}

interface Target {
  file: string
  line: number
  side: 'new' | 'old'
  code: string
}

function countLines(file: FileData) {
  let added = 0
  let removed = 0
  for (const hunk of file.hunks)
    for (const change of hunk.changes) {
      if (change.type === 'insert') added++
      else if (change.type === 'delete') removed++
    }
  return { added, removed }
}

// react-diff-view styles itself through CSS variables; these match the dark theme.
const diffTheme = {
  '--diff-background-color': '#0d1117',
  '--diff-text-color': '#e6edf3',
  '--diff-font-family': 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  '--diff-gutter-insert-background-color': '#1b4721',
  '--diff-gutter-delete-background-color': '#5c1f24',
  '--diff-code-insert-background-color': '#12261a',
  '--diff-code-delete-background-color': '#2d1618',
  '--diff-code-insert-edit-background-color': '#2a6b36',
  '--diff-code-delete-edit-background-color': '#8a2f36',
  '--diff-selection-background-color': '#264f78',
  fontSize: 13,
}

export default function Changes() {
  const { key = '' } = useParams()
  const [commit, setCommit] = useState('')
  const [data, setData] = useState<ChangesData | null>(null)
  const [commits, setCommits] = useState<ChangesData['commits']>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<Feedback>({ comments: [], run: null })
  const [feedbackError, setFeedbackError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [composing, setComposing] = useState<Target | null>(null)
  // Bumped when an AI run finishes so the diff shows its new commits.
  const [reload, setReload] = useState(0)
  const lastRunState = useRef<string | null>(null)

  useEffect(() => {
    fetchFeedback(key).then(setFeedback, () => {})
  }, [key])

  const running = feedback.run?.state === 'running'
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => fetchFeedback(key).then(setFeedback, () => {}), 2000)
    return () => clearInterval(timer)
  }, [key, running])

  useEffect(() => {
    const state = feedback.run?.state ?? null
    if (lastRunState.current === 'running' && state && state !== 'running') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setReload((n) => n + 1)
    }
    lastRunState.current = state
  }, [feedback.run?.state])

  // Runs a feedback action; returns whether it worked, showing any error in the panel.
  const guard = useCallback(async (action: () => Promise<unknown>) => {
    setFeedbackError(null)
    try {
      await action()
      return true
    } catch (e) {
      setFeedbackError((e as Error).message)
      return false
    }
  }, [])

  const addComment = (input: FeedbackCommentInput) =>
    guard(async () => {
      const c = await addFeedbackComment(key, input)
      setFeedback((f) => ({ ...f, comments: [...f.comments, c] }))
    })
  const editComment = (id: string, text: string) =>
    guard(async () => {
      const c = await editFeedbackComment(key, id, text)
      setFeedback((f) => ({ ...f, comments: f.comments.map((x) => (x.id === id ? c : x)) }))
    })
  const deleteComment = (id: string) =>
    guard(async () => {
      await deleteFeedbackComment(key, id)
      setFeedback((f) => ({ ...f, comments: f.comments.filter((x) => x.id !== id) }))
    })
  const submit = async () => {
    setSubmitting(true)
    await guard(async () => {
      const run = await submitFeedback(key)
      setFeedback((f) => ({ ...f, run }))
    })
    setSubmitting(false)
  }

  useEffect(() => {
    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    fetchChanges(key, commit || undefined).then(
      (d) => {
        if (cancelled) return
        setData(d)
        if (!commit) setCommits(d.commits)
        setError(null)
        setLoading(false)
      },
      (e: Error) => {
        if (cancelled) return
        setError(e.message)
        setLoading(false)
      },
    )
    return () => {
      cancelled = true
    }
  }, [key, commit, reload])

  // parseDiff returns one empty entry for empty input.
  const files = useMemo(
    () => (data ? parseDiff(data.diff).filter((f) => f.oldPath || f.newPath) : []),
    [data],
  )
  const selected = files.find((f) => filePath(f) === selectedPath) ?? files[0]
  const totals = useMemo(
    () =>
      files.reduce(
        (sum, f) => {
          const c = countLines(f)
          return { added: sum.added + c.added, removed: sum.removed + c.removed }
        },
        { added: 0, removed: 0 },
      ),
    [files],
  )

  const back = (
    <Box>
      <Button startIcon={<ArrowBackIcon />} component={RouterLink} to={`/cards/${key}`}>
        Back to {key}
      </Button>
    </Box>
  )

  return (
    <Stack spacing={2} sx={{ height: 'calc(100vh - 96px)', minHeight: 400 }}>
      {back}
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography variant="h4" component="h1">
          Changes for {key}
        </Typography>
        {data && <Chip label={data.branch} variant="outlined" />}
        {loading && <CircularProgress size={20} aria-label="Loading changes" />}
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}

      {commits.length > 0 && (
        <TextField
          select
          size="small"
          label="Commits"
          value={commit}
          onChange={(e) => setCommit(e.target.value)}
          sx={{ maxWidth: 560 }}
        >
          <MenuItem value="">All changes ({commits.length} commits)</MenuItem>
          {commits.map((c) => (
            <MenuItem key={c.sha} value={c.sha}>
              {c.short} {c.subject}
            </MenuItem>
          ))}
        </TextField>
      )}

      {data && (
        <Typography color="text.secondary">
          {files.length} {files.length === 1 ? 'file' : 'files'} changed,{' '}
          <Box component="span" sx={{ color: 'success.main' }}>
            +{totals.added}
          </Box>{' '}
          <Box component="span" sx={{ color: 'error.main' }}>
            −{totals.removed}
          </Box>
        </Typography>
      )}
      {data && files.length === 0 && !loading && (
        <Alert severity="info" role="note">
          No changes to show.
        </Alert>
      )}

      {data && (
        <Stack direction="row" spacing={2} sx={{ flex: 1, minHeight: 0 }}>
          {selected && (
            <>
              <List
                dense
                aria-label="Changed files"
                sx={{ width: 300, flexShrink: 0, overflowY: 'auto' }}
              >
                {files.map((file) => {
                  const { added, removed } = countLines(file)
                  return (
                    <ListItemButton
                      key={`${file.oldPath}-${file.newPath}`}
                      selected={file === selected}
                      onClick={() => setSelectedPath(filePath(file))}
                    >
                      <ListItemText
                        primary={filePath(file)}
                        secondary={`+${added} −${removed}`}
                        slotProps={{ primary: { sx: { wordBreak: 'break-all' } } }}
                      />
                    </ListItemButton>
                  )
                })}
              </List>
              <FilePane
                file={selected}
                comments={feedback.comments}
                // Line numbers only mean something in the combined diff.
                canComment={!commit}
                composing={composing}
                onCompose={setComposing}
                onAdd={(target, text) =>
                  addComment({ text, ...target }).then((ok) => {
                    if (ok) setComposing(null)
                    return ok
                  })
                }
                onEdit={editComment}
                onDelete={deleteComment}
              />
            </>
          )}
          <FeedbackPanel
            comments={feedback.comments}
            run={feedback.run}
            error={feedbackError}
            submitting={submitting}
            onAdd={(text) => addComment({ text })}
            onEdit={editComment}
            onDelete={deleteComment}
            onSubmit={submit}
          />
        </Stack>
      )}
    </Stack>
  )
}

function FilePane({
  file,
  comments,
  canComment,
  composing,
  onCompose,
  onAdd,
  onEdit,
  onDelete,
}: {
  file: FileData
  comments: FeedbackComment[]
  canComment: boolean
  composing: Target | null
  onCompose: (target: Target | null) => void
  onAdd: (target: Target, text: string) => Promise<boolean>
  onEdit: (id: string, text: string) => Promise<boolean>
  onDelete: (id: string) => Promise<unknown>
}) {
  const { added, removed } = countLines(file)
  const status = STATUS[file.type] ?? STATUS.modify
  const path = commentPath(file)

  // Pending line comments and the open composer appear under the line they belong to.
  const widgets = useMemo(() => {
    const result: Record<string, ReactNode> = {}
    if (!canComment) return result
    const mine = comments.filter((c) => c.status === 'pending' && c.file === path && c.line)
    for (const hunk of file.hunks)
      for (const change of hunk.changes) {
        const side = isDelete(change) ? 'old' : 'new'
        const line = lineOf(change)
        const here = mine.filter((c) => c.line === line && c.side === side)
        const open = composing?.file === path && composing.line === line && composing.side === side
        if (!here.length && !open) continue
        result[getChangeKey(change)] = (
          <Stack spacing={1} sx={{ p: 1, whiteSpace: 'normal', fontFamily: 'sans-serif' }}>
            {here.map((c) => (
              <CommentCard
                key={c.id}
                comment={c}
                showLocation={false}
                onEdit={(text) => onEdit(c.id, text)}
                onDelete={() => onDelete(c.id)}
              />
            ))}
            {open && composing && (
              <Composer
                label={`Your comment on line ${line}`}
                onAdd={(text) => onAdd(composing, text)}
                onCancel={() => onCompose(null)}
              />
            )}
          </Stack>
        )
      }
    return result
  }, [canComment, comments, composing, file.hunks, onAdd, onCompose, onDelete, onEdit, path])

  return (
    <Paper
      variant="outlined"
      aria-label="File diff"
      sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', p: 1.5 }}>
        <Typography sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
          {filePath(file)}
        </Typography>
        <Chip label={status.label} size="small" color={status.color} />
        <Typography variant="body2" sx={{ color: 'success.main' }}>
          +{added}
        </Typography>
        <Typography variant="body2" sx={{ color: 'error.main' }}>
          −{removed}
        </Typography>
      </Stack>
      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {file.hunks.length === 0 ? (
          <Typography color="text.secondary" sx={{ p: 2 }}>
            No textual changes (binary file or mode change).
          </Typography>
        ) : (
          <Box sx={diffTheme}>
            <Diff
              viewType="unified"
              diffType={file.type}
              hunks={file.hunks}
              widgets={widgets}
              renderGutter={({ change, side, renderDefault, inHoverState }) => {
                const own = isDelete(change) ? 'old' : 'new'
                if (!canComment || side !== own) return renderDefault()
                const line = lineOf(change)
                return (
                  <button
                    type="button"
                    aria-label={`Comment on ${own === 'old' ? 'removed ' : ''}line ${line}`}
                    onClick={() => onCompose({ file: path, line, side: own, code: change.content })}
                    style={{
                      background: 'none',
                      border: 0,
                      color: 'inherit',
                      cursor: 'pointer',
                      font: 'inherit',
                      padding: 0,
                      width: '100%',
                    }}
                  >
                    {inHoverState ? '+' : renderDefault()}
                  </button>
                )
              }}
            >
              {(hunks) => hunks.map((h) => <Hunk key={h.content} hunk={h} />)}
            </Diff>
          </Box>
        )}
      </Box>
    </Paper>
  )
}
