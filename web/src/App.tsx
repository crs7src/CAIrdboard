import { Route, Routes } from 'react-router-dom'
import Layout from './app/Layout'
import Archive from './features/cards/Archive'
import CardDetail from './features/cards/CardDetail'
import Changes from './features/changes/Changes'
import Home from './features/cards/Home'
import Projects from './features/projects/Projects'
import { settingsRoutes } from './features/settings/routes'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/archive" element={<Archive />} />
        <Route path="/cards/:key" element={<CardDetail />} />
        <Route path="/cards/:key/changes" element={<Changes />} />
        {settingsRoutes}
      </Route>
    </Routes>
  )
}
