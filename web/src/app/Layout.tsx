import Brand from './Brand'
import AppBar from '@mui/material/AppBar'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Container from '@mui/material/Container'
import Toolbar from '@mui/material/Toolbar'
import { Link, Outlet, useLocation } from 'react-router-dom'

const links = [
  { to: '/', label: 'Home' },
  { to: '/projects', label: 'Projects' },
  { to: '/settings', label: 'Settings' },
]

export default function Layout() {
  // The changes page needs the whole screen so diff lines are not cramped.
  const wide = /\/changes$/.test(useLocation().pathname)
  return (
    <>
      <AppBar position="static">
        <Toolbar>
          <Box sx={{ flexGrow: 1 }}>
            <Button color="inherit" component={Link} to="/" sx={{ textTransform: 'none', fontSize: '1.25rem' }}>
              <Brand />
            </Button>
          </Box>
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
