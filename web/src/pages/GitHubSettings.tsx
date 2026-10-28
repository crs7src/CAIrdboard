import Divider from '@mui/material/Divider'
import Stack from '@mui/material/Stack'
import HostConnection from './HostConnection'
import RepoHostProjects from './RepoHostProjects'

export default function GitHubSettings() {
  return (
    <Stack spacing={3}>
      <HostConnection provider="github" />
      <Divider />
      <RepoHostProjects provider="github" />
    </Stack>
  )
}
