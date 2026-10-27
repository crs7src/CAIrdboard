import { Link, Route, Routes } from 'react-router-dom'
import Cards from './pages/Cards'
import Hello from './pages/Hello'
import Settings from './pages/Settings'

export default function App() {
  return (
    <>
      <nav>
        <Link to="/">Home</Link> <Link to="/cards">My Cards</Link> <Link to="/settings">Settings</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Hello />} />
        <Route path="/cards" element={<Cards />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </>
  )
}
