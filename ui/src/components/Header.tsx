import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useWebSocket } from '../controllers/connection'
import { useDashboard } from '../controllers/dashboard'
import { useI18n } from '../controllers/i18n'

export default function Header() {
  const location = useLocation()
  const { connected } = useWebSocket()
  const { networkInfo, fetchNetworkInfo } = useDashboard()
  const { t, locale, setLocale } = useI18n()

  useEffect(() => {
    fetchNetworkInfo()
  }, [fetchNetworkInfo])

  const navItems = [
    { path: '/control', label: t('controlCenter') },
    { path: '/data', label: t('dataCenter') },
    { path: '/settings', label: t('settings') },
    { path: '/logs', label: t('logs') },
    { path: '/chat', label: t('assistantChat') },
  ]

  return (
    <header className="flex items-center gap-3 px-4 py-2 bg-sf border-b border-bd/50 flex-wrap">
      <h1 className="text-base font-bold tracking-tight text-ac whitespace-nowrap">RoboClaw</h1>

      <span className={`flex items-center gap-1.5 text-2xs font-mono ${connected ? 'text-gn' : 'text-rd'}`}>
        <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-gn' : 'bg-rd'}`} />
        {connected ? t('connected') : t('disconnected')}
      </span>

      <nav className="flex items-center gap-0.5 ml-3">
        {navItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={`px-2.5 py-1 text-sm rounded-md transition-all ${
              location.pathname === item.path
                ? 'text-ac font-semibold bg-ac/10'
                : 'text-tx2 hover:text-tx hover:bg-bd/30'
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="flex-1" />

      {networkInfo && (
        <span className="text-2xs text-tx3 font-mono whitespace-nowrap mr-2">
          {networkInfo.lan_ip}:{networkInfo.port}
        </span>
      )}

      <button
        onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}
        className="text-tx3 hover:text-tx2 text-xs transition-colors"
      >
        {locale === 'zh' ? 'EN' : '中文'}
      </button>
    </header>
  )
}
