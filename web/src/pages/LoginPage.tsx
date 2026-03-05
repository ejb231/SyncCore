import { useState } from 'react'
import { api, setAdminToken } from '../api/client'
import { FolderSync, KeyRound } from 'lucide-react'

export default function LoginPage({ onComplete }: { onComplete: () => void }) {
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.login(token.trim())
      setAdminToken(token.trim())
      onComplete()
    } catch {
      setError('Invalid admin token. Check your terminal output or .env file.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full">
        <div className="flex items-center gap-3 mb-2">
          <div className="bg-blue-600 p-2.5 rounded-xl"><FolderSync size={28} className="text-white" /></div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Welcome Back</h1>
            <p className="text-sm text-gray-500">SyncCore is already set up</p>
          </div>
        </div>

        <p className="text-sm text-gray-600 mt-3 mb-6 leading-relaxed">
          Enter your admin token to continue. You can find it in your terminal
          output or by running <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs font-mono">python main.py show-token</code>.
        </p>

        {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2.5 rounded-lg mb-4 text-sm">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1">
              <KeyRound size={15} className="text-blue-500" /> Admin Token
            </label>
            <input
              type="password"
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              placeholder="Paste your admin token"
              value={token}
              onChange={e => setToken(e.target.value)}
              autoFocus
            />
          </div>

          <button
            type="submit"
            disabled={loading || !token.trim()}
            className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50 transition-colors text-base"
          >
            {loading ? 'Verifying…' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  )
}
