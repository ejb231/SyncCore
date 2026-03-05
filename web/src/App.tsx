import { useState, useEffect } from 'react'
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
import LoginPage from './pages/LoginPage'
import { useWebSocket } from './hooks/useWebSocket'
import { getAdminToken, onAuthFailure } from './api/client'

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

type AppState = 'loading' | 'setup' | 'login' | 'ready'

export default function App() {
  const [state, setState] = useState<AppState>('loading')

  useEffect(() => {
    checkState()
    onAuthFailure(() => setState('login'))
  }, [])

  async function checkState() {
    try {
      const res = await fetch('/api/v1/setup/status')
      if (!res.ok) {
        // Endpoint returned an error — assume setup is done,
        // show login unless we already have a token.
        setState(getAdminToken() ? 'ready' : 'login')
        return
      }
      const text = await res.text()
      let data: { setup_complete?: boolean }
      try {
        data = JSON.parse(text)
      } catch {
        // Got a non-JSON response (e.g. the SPA index.html)
        setState(getAdminToken() ? 'ready' : 'login')
        return
      }
      if (!data.setup_complete) {
        setState('setup')
      } else if (getAdminToken()) {
        setState('ready')
      } else {
        setState('login')
      }
    } catch {
      // Network error / server not ready
      setState(getAdminToken() ? 'ready' : 'login')
    }
  }

  if (state === 'loading') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center">
        <div className="text-gray-400 text-sm">Connecting to SyncCore…</div>
      </div>
    )
  }

  if (state === 'setup') {
    return (
      <Routes>
        <Route path="*" element={<SetupPage onComplete={() => setState('ready')} />} />
      </Routes>
    )
  }

  if (state === 'login') {
    return (
      <Routes>
        <Route path="*" element={<LoginPage onComplete={() => setState('ready')} />} />
      </Routes>
    )
  }

  return <Layout />
}
