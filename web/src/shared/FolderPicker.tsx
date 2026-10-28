import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import List from '@mui/material/List'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Typography from '@mui/material/Typography'
import FolderIcon from '@mui/icons-material/Folder'
import CodeIcon from '@mui/icons-material/Code'
import { useEffect, useState } from 'react'
import { fetchDirs, type DirListing } from '../api'

interface Props {
  open: boolean
  initialPath: string
  onClose: () => void
  onSelect: (path: string) => void
}

export default function FolderPicker({ open, initialPath, onClose, onSelect }: Props) {
  const [listing, setListing] = useState<DirListing | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function go(path?: string) {
    try {
      setListing(await fetchDirs(path))
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    if (!open) return
    // Fall back to home when the typed path is not a real folder.
    fetchDirs(initialPath || undefined).then(
      (l) => {
        setListing(l)
        setError(null)
      },
      () => go(),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Choose a repository folder</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error">{error}</Alert>}
        {listing && (
          <>
            <Typography variant="body2" sx={{ wordBreak: 'break-all', mb: 1 }}>
              {listing.path}
            </Typography>
            <List dense>
              {listing.parent && (
                <ListItemButton onClick={() => go(listing.parent!)}>
                  <ListItemText primary="Up" />
                </ListItemButton>
              )}
              {listing.dirs.map((d) => (
                <ListItemButton key={d.name} onClick={() => go(`${listing.path}/${d.name}`)}>
                  <ListItemIcon>{d.is_git ? <CodeIcon /> : <FolderIcon />}</ListItemIcon>
                  <ListItemText primary={d.name} secondary={d.is_git ? 'git repository' : undefined} />
                </ListItemButton>
              ))}
            </List>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!listing} onClick={() => listing && onSelect(listing.path)}>
          Select this folder
        </Button>
      </DialogActions>
    </Dialog>
  )
}
