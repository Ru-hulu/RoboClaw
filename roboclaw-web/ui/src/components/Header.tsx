import { Link } from 'react-router-dom'
import { useI18n } from '../controllers/i18n'

export default function Header() {
  const { locale, setLocale } = useI18n()

  return (
    <header className="app-topbar">
      <div className="app-topbar__title">
        <Link to="/dashboard" className="display-title text-[1.95rem] text-tx">
          RoboClaw
        </Link>
      </div>
      <div className="app-topbar__actions">
        <button
          onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}
          className="app-topbar__locale"
        >
          {locale === 'zh' ? 'EN' : '中文'}
        </button>
      </div>
    </header>
  )
}
