import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlined'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'

export type StepStatus = 'next' | 'blocked' | 'running' | 'done' | 'failed'

interface Props {
  label: string
  status: StepStatus
  onRun?: () => void
  /** Show a grey check instead of a play arrow until the step is done. */
  check?: boolean
  /** When the step is done, make the check a link that opens in a new tab. */
  href?: string
}

/** Play button for one workflow step; becomes a green check once the step is done. */
export default function StepButton({ label, status, onRun, check, href }: Props) {
  if (status === 'done' && href) {
    return (
      <Tooltip title="Open merge request">
        <IconButton
          size="small"
          color="success"
          component="a"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={label}
        >
          <CheckCircleIcon />
        </IconButton>
      </Tooltip>
    )
  }
  if (status === 'done') {
    return (
      <Tooltip title={label}>
        <span role="img" style={{ display: 'inline-flex', padding: 4 }}>
          <CheckCircleIcon color="success" />
        </span>
      </Tooltip>
    )
  }
  if (status === 'failed') {
    return (
      <Tooltip title={`${label} failed – click to retry`}>
        <span>
          <IconButton size="small" color="error" aria-label={`${label} failed`} onClick={onRun}>
            <ErrorIcon />
          </IconButton>
        </span>
      </Tooltip>
    )
  }
  return (
    <Tooltip title={label}>
      <span>
        <IconButton
          size="small"
          color={check ? 'default' : 'primary'}
          aria-label={label}
          disabled={status !== 'next'}
          onClick={onRun}
        >
          {status === 'running' ? <CircularProgress size={18} /> : check ? <CheckCircleOutlineIcon /> : <PlayArrowIcon />}
        </IconButton>
      </span>
    </Tooltip>
  )
}
