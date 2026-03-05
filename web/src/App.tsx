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

type AppState = 'loading' | 'setup' | 'login' | 'ready' | 'connection-error'

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
      // Network error — likely a TLS certificate issue or server not running
      setState('connection-error')
    }
  }

  if (state === 'loading') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center">
        <div className="text-gray-400 text-sm">Connecting to SyncCore…</div>
      </div>
    )
  }

  if (state === 'connection-error') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full text-center">
          <div className="text-4xl mb-4">🔒</div>
          <h1 className="text-xl font-bold text-gray-900 mb-2">Cannot Connect to SyncCore</h1>
          <p className="text-sm text-gray-600 mb-4 leading-relaxed">
            This usually happens after a reset because the browser needs to
            accept the new TLS certificate.
          </p>
          <div className="bg-gray-50 rounded-lg p-4 text-left text-sm space-y-2 mb-5">
            <p className="font-medium text-gray-700">To fix this:</p>
            <ol className="list-decimal list-inside space-y-1 text-gray-600">
              <li>Open <a href={window.location.origin} target="_blank" rel="noreferrer"
                className="text-blue-600 underline">{window.location.origin}</a> in a new tab</li>
              <li>Accept the certificate warning (click "Advanced" → "Accept the Risk")</li>
              <li>Come back here and click Retry</li>
            </ol>
          </div>
          <button
            onClick={() => { setState('loading'); setTimeout(checkState, 500) }}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg font-semibold hover:bg-blue-700 transition-colors"
          >
            Retry Connection
          </button>
          <p className="text-xs text-gray-400 mt-4">
            If this persists, make sure SyncCore is running (<code className="bg-gray-100 px-1 py-0.5 rounded">python main.py run</code>).
          </p>
        </div>
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
