import Divider from '@mui/material/Divider'
import Stack from '@mui/material/Stack'
import HostConnection from './HostConnection'
import RepoHostProjects from './RepoHostProjects'

export default function GitLabSettings() {
  return (
    <Stack spacing={3}>
      <HostConnection provider="gitlab" />
      <Divider />
      <RepoHostProjects provider="gitlab" />
    </Stack>
  )
}
