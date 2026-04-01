import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchProviderStatus, saveProviderConfig } from '../controllers/provider'
import { useI18n } from '../controllers/i18n'
import { ActionButton, GlassPanel } from '../components/ux'

export default function SettingsView() {
  const navigate = useNavigate()
  const { t } = useI18n()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiBase, setApiBase] = useState('')

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const payload = await fetchProviderStatus()
        if (cancelled) return
        setApiBase(payload.custom_provider.api_base || '')
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : 'Failed to load settings.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSave(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')

    try {
      const payload = await saveProviderConfig({ api_key: apiKey, api_base: apiBase })
      setApiBase(payload.custom_provider.api_base || '')
      setNotice(t('saveSuccess'))
      setApiKey('')
      window.setTimeout(() => navigate('/dashboard'), 600)
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page-enter mx-auto flex w-full max-w-2xl">
      <GlassPanel className="w-full p-0">
        <div className="px-5 py-5 md:px-6 md:py-6">
          {loading && <p className="text-sm text-tx2">{t('loading')}</p>}
          {!loading && (
            <form onSubmit={handleSave} className="space-y-5">
              {error && (
                <div className="rounded-[18px] border border-rd/20 bg-rd/10 px-4 py-3 text-sm text-rd">
                  {error}
                </div>
              )}
              {notice && (
                <div className="rounded-[18px] border border-gn/20 bg-gn/10 px-4 py-3 text-sm text-gn">
                  {notice}
                </div>
              )}

              <label className="space-y-2 text-sm text-tx2">
                <span>{t('baseUrl')}</span>
                <div className="field-shell px-4 py-3">
                  <input
                    value={apiBase}
                    onChange={(e) => setApiBase(e.target.value)}
                    className="w-full border-0 bg-transparent text-tx outline-none placeholder:text-tx2"
                    placeholder="https://your-openai-compatible-endpoint/v1"
                  />
                </div>
              </label>

              <label className="space-y-2 text-sm text-tx2">
                <span>{t('apiKey')}</span>
                <div className="field-shell px-4 py-3">
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    className="w-full border-0 bg-transparent text-tx outline-none placeholder:text-tx2"
                    placeholder={t('apiKeyPlaceholder')}
                  />
                </div>
              </label>

              <div>
                <ActionButton type="submit" variant="success" disabled={saving}>
                  {saving ? t('saving') : t('saveSettings')}
                </ActionButton>
              </div>
            </form>
          )}
        </div>
      </GlassPanel>
    </div>
  )
}
