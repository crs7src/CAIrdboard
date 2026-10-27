import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'

export type StepStatus = 'next' | 'blocked' | 'running' | 'done'

interface Props {
  label: string
  status: StepStatus
  onRun?: () => void
}

/** Play button for one workflow step; becomes a green check once the step is done. */
export default function StepButton({ label, status, onRun }: Props) {
  if (status === 'done') {
    return (
      <Tooltip title={label}>
        <span role="img" style={{ display: 'inline-flex', padding: 4 }}>
          <CheckCircleIcon color="success" />
        </span>
      </Tooltip>
    )
  }
  return (
    <Tooltip title={label}>
      <span>
        <IconButton
          size="small"
          color="primary"
          aria-label={label}
          disabled={status !== 'next'}
          onClick={onRun}
        >
          {status === 'running' ? <CircularProgress size={18} /> : <PlayArrowIcon />}
        </IconButton>
      </span>
    </Tooltip>
  )
}
