import Stack from '@mui/material/Stack'
import Tab from '@mui/material/Tab'
import Tabs from '@mui/material/Tabs'
import Typography from '@mui/material/Typography'
import { Link, Outlet, useLocation } from 'react-router-dom'

export default function SettingsLayout() {
  const { pathname } = useLocation()
  return (
    <Stack spacing={2}>
      <Typography variant="h4" component="h1">
        Settings
      </Typography>
      <Tabs
        value={
          ['/settings/jira', '/settings/skills', '/settings/test-apps', '/settings/gitlab'].find((p) => pathname.startsWith(p)) ?? '/settings/ai'
        }
        sx={{
          bgcolor: '#0d2a4d',
          borderRadius: 1,
          '& .MuiTab-root': { color: '#fff' },
          '& .MuiTab-root.Mui-selected': { color: '#fff' },
          '& .MuiTabs-indicator': { backgroundColor: '#fff' },
        }}
      >
        <Tab label="AI" value="/settings/ai" component={Link} to="/settings/ai" />
        <Tab label="Skills" value="/settings/skills" component={Link} to="/settings/skills" />
        <Tab label="Test apps" value="/settings/test-apps" component={Link} to="/settings/test-apps" />
        <Tab label="Jira" value="/settings/jira" component={Link} to="/settings/jira" />
        <Tab label="GitLab" value="/settings/gitlab" component={Link} to="/settings/gitlab" />
      </Tabs>
      <Outlet />
    </Stack>
  )
}
