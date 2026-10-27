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
import { useEffect, useMemo, useState } from 'react'
import { Diff, Hunk, parseDiff, type FileData } from 'react-diff-view'
import 'react-diff-view/style/index.css'
import { Link as RouterLink, useParams } from 'react-router-dom'
import { fetchChanges, type Changes as ChangesData } from '../api'

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
  }, [key, commit])

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

      {selected && (
        <Stack direction="row" spacing={2} sx={{ flex: 1, minHeight: 0 }}>
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
          <FilePane file={selected} />
        </Stack>
      )}
    </Stack>
  )
}

function FilePane({ file }: { file: FileData }) {
  const { added, removed } = countLines(file)
  const status = STATUS[file.type] ?? STATUS.modify
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
            <Diff viewType="unified" diffType={file.type} hunks={file.hunks}>
              {(hunks) => hunks.map((h) => <Hunk key={h.content} hunk={h} />)}
            </Diff>
          </Box>
        )}
      </Box>
    </Paper>
  )
}
