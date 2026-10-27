import { Route, Routes } from 'react-router-dom'
import Layout from './Layout'
import AiSettings from './pages/AiSettings'
import CardDetail from './pages/CardDetail'
import Cards from './pages/Cards'
import Home from './pages/Home'
import Settings from './pages/Settings'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/cards" element={<Cards />} />
        <Route path="/cards/:key" element={<CardDetail />} />
        <Route path="/ai-settings" element={<AiSettings />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
