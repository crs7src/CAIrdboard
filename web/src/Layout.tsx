import AppBar from '@mui/material/AppBar'
import Button from '@mui/material/Button'
import Container from '@mui/material/Container'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import { Link, Outlet, useLocation } from 'react-router-dom'

const links = [
  { to: '/', label: 'Home' },
  { to: '/settings', label: 'Settings' },
]

export default function Layout() {
  // The changes page needs the whole screen so diff lines are not cramped.
  const wide = /\/changes$/.test(useLocation().pathname)
  return (
    <>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            CAIrdboard
          </Typography>
          <nav>
            {links.map((l) => (
              <Button key={l.to} color="inherit" component={Link} to={l.to}>
                {l.label}
              </Button>
            ))}
          </nav>
        </Toolbar>
      </AppBar>
      <Container component="main" maxWidth={wide ? false : 'md'} sx={{ py: wide ? 2 : 4 }}>
        <Outlet />
      </Container>
    </>
  )
}
