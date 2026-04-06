import { useEffect } from 'react'
import { useSetup } from '../controllers/setup'
import { useI18n } from '../controllers/i18n'
import DeviceList from '../components/setup/DeviceList'
import DiscoveryWizard from '../components/setup/DiscoveryWizard'

export default function SetupView() {
  const { t } = useI18n()
  const { wizardActive, startWizard, loadDevices, loadCatalog, error } = useSetup()

  useEffect(() => {
    loadDevices()
    loadCatalog()
  }, [])

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="flex items-center justify-between border-b border-bd p-4">
        <h2 className="text-lg font-semibold">{t('setup')}</h2>
        {!wizardActive && (
          <button
            onClick={startWizard}
            className="px-4 py-1.5 border border-ac text-ac rounded text-sm transition-colors hover:bg-ac/10 active:scale-[0.97]"
          >
            添加设备
          </button>
        )}
      </div>

      {error && (
        <div className="mx-4 mt-4 rounded-lg border border-rd/30 bg-rd/5 p-3 text-sm text-rd">
          {error}
        </div>
      )}

      <div className="flex-1 p-4 space-y-4">
        <DeviceList />
        {wizardActive && <DiscoveryWizard />}
      </div>
    </div>
  )
}
