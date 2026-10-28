import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './Layout'
import AiSettings from './pages/AiSettings'
import CardDetail from './pages/CardDetail'
import Changes from './pages/Changes'
import GitHubSettings from './pages/GitHubSettings'
import GitLabSettings from './pages/GitLabSettings'
import Home from './pages/Home'
import TestAppsSettings from './pages/TestAppsSettings'
import SkillsSettings from './pages/SkillsSettings'
import Settings from './pages/Settings'
import SettingsLayout from './pages/SettingsLayout'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/cards/:key" element={<CardDetail />} />
        <Route path="/cards/:key/changes" element={<Changes />} />
        <Route path="/ai-settings" element={<Navigate to="/settings/ai" replace />} />
        <Route path="/settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="/settings/ai" replace />} />
          <Route path="jira" element={<Settings />} />
          <Route path="ai" element={<AiSettings />} />
          <Route path="skills" element={<SkillsSettings />} />
          <Route path="gitlab" element={<GitLabSettings />} />
          <Route path="github" element={<GitHubSettings />} />
          <Route path="test-apps" element={<TestAppsSettings />} />
        </Route>
      </Route>
    </Routes>
  )
}
