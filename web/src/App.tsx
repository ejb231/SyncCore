import { useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import FilesPage from './pages/FilesPage'
import ConflictsPage from './pages/ConflictsPage'
import PeersPage from './pages/PeersPage'
import QueuePage from './pages/QueuePage'
import SettingsPage from './pages/SettingsPage'
import LogsPage from './pages/LogsPage'
import SetupPage from './pages/SetupPage'
import { useWebSocket } from './hooks/useWebSocket'
import { getAdminToken } from './api/client'

function Layout() {
  const { toast } = useWebSocket()
  return (
    <div className="flex min-h-screen bg-gray-100">
      <Sidebar />
      <main className="flex-1 p-6 overflow-auto">
        {toast && (
          <div className="fixed top-4 right-4 bg-amber-100 border border-amber-300 text-amber-800 px-4 py-2 rounded-lg shadow-lg text-sm z-50">
            {toast}
          </div>
        )}
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/files" element={<FilesPage />} />
          <Route path="/conflicts" element={<ConflictsPage />} />
          <Route path="/peers" element={<PeersPage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/logs" element={<LogsPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  const [setupDone, setSetupDone] = useState(!!getAdminToken())

  if (!setupDone) {
    return (
      <Routes>
        <Route path="/setup" element={<SetupPage onComplete={() => setSetupDone(true)} />} />
        <Route path="*" element={<SetupPage onComplete={() => setSetupDone(true)} />} />
      </Routes>
    )
  }

  return <Layout />
}
