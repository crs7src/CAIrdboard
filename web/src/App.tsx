import { Route, Routes } from 'react-router-dom'
import Layout from './Layout'
import Cards from './pages/Cards'
import Home from './pages/Home'
import Settings from './pages/Settings'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/cards" element={<Cards />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
