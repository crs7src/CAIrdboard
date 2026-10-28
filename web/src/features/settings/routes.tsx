import { Navigate, Route } from 'react-router-dom'
import AiSettings from './AiSettings'
import GitHubSettings from './auth/GitHubSettings'
import GitLabSettings from './auth/GitLabSettings'
import Settings from './auth/JiraSettings'
import SettingsLayout from './SettingsLayout'
import SkillsSettings from './SkillsSettings'
import TestAppsSettings from './TestAppsSettings'

export const settingsRoutes = (
  <>
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
  </>
)
