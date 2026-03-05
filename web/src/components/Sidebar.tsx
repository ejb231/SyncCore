import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Files, AlertTriangle, Users, ListTodo, Settings, ScrollText, LogOut, FolderSync } from 'lucide-react'

const links = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/files', icon: Files, label: 'Files' },
  { to: '/conflicts', icon: AlertTriangle, label: 'Conflicts' },
  { to: '/peers', icon: Users, label: 'Peers' },
  { to: '/queue', icon: ListTodo, label: 'Queue' },
  { to: '/settings', icon: Settings, label: 'Settings' },
  { to: '/logs', icon: ScrollText, label: 'Logs' },
]

export default function Sidebar() {
  function handleLogout() {
    localStorage.removeItem('adminToken')
    window.location.reload()
  }

  return (
    <aside className="w-56 bg-gray-900 text-gray-200 flex flex-col min-h-screen p-4">
      <div className="flex items-center gap-2.5 mb-8">
        <div className="bg-blue-600 p-1.5 rounded-lg">
          <FolderSync size={20} className="text-white" />
        </div>
        <div>
          <h1 className="text-lg font-bold text-white leading-tight">SyncCore</h1>
          <span className="text-[10px] text-gray-500 leading-none">v1.3.1</span>
        </div>
      </div>
      <nav className="flex flex-col gap-1 flex-1">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition ${isActive ? 'bg-blue-600 text-white' : 'hover:bg-gray-800'}`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
      <button
        onClick={handleLogout}
        className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-400 hover:bg-gray-800 hover:text-gray-200 transition mt-2"
      >
        <LogOut size={18} /> Sign Out
      </button>
    </aside>
  )
}
