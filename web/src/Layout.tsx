import AppBar from '@mui/material/AppBar'
import Button from '@mui/material/Button'
import Container from '@mui/material/Container'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import { Link, Outlet } from 'react-router-dom'

const links = [
  { to: '/', label: 'Home' },
  { to: '/cards', label: 'My Cards' },
  { to: '/settings', label: 'Settings' },
]

export default function Layout() {
  return (
    <>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            AI Card Board
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
      <Container component="main" maxWidth="md" sx={{ py: 4 }}>
        <Outlet />
      </Container>
    </>
  )
}
