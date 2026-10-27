import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'

export default function Home() {
  return (
    <Stack spacing={3}>
      <Typography variant="h3" component="h1">
        AI Card Board
      </Typography>
      <Typography color="text.secondary">
        Review the Jira cards assigned to you, have an AI draft a plan for each one, then hand the
        approved plan to another AI to implement and a third to review.
      </Typography>
    </Stack>
  )
}
