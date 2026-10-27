import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './Layout'
import AiSettings from './pages/AiSettings'
import CardDetail from './pages/CardDetail'
import Cards from './pages/Cards'
import Home from './pages/Home'
import Settings from './pages/Settings'
import SettingsLayout from './pages/SettingsLayout'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/cards" element={<Cards />} />
        <Route path="/cards/:key" element={<CardDetail />} />
        <Route path="/ai-settings" element={<Navigate to="/settings/ai" replace />} />
        <Route path="/settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="/settings/ai" replace />} />
          <Route path="jira" element={<Settings />} />
          <Route path="ai" element={<AiSettings />} />
        </Route>
      </Route>
    </Routes>
  )
}
