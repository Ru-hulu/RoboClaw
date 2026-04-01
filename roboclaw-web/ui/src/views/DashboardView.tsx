import { useEffect, useRef, useState } from 'react'
import { useDataCollection, type RobotState } from '../controllers/datacollection'
import { useDashboard } from '../controllers/dashboard'
import { useI18n } from '../controllers/i18n'
import { GlassPanel } from '../components/ux'

function canDo(state: RobotState) {
  const disconnected = state === 'disconnected'
  const connected = state === 'connected'
  const teleoperating = state === 'teleoperating'
  const recording = state === 'recording'
  const preparing = state === 'preparing'

  return {
    connect: disconnected,
    disconnect: !disconnected && !preparing,
    teleopStart: connected,
    teleopStop: teleoperating,
    recStart: connected || teleoperating,
    recStop: recording,
    saveEpisode: recording,
    discardEpisode: recording,
  }
}

function stateBadgeClass(state: RobotState) {
  if (state === 'connected') return 'bg-[rgba(47,111,228,0.1)] text-ac'
  if (state === 'teleoperating') return 'bg-[rgba(47,111,228,0.14)] text-ac'
  if (state === 'recording') return 'bg-ac text-white'
  if (state === 'preparing') return 'bg-[rgba(47,111,228,0.1)] text-ac'
  return 'bg-[rgba(17,17,17,0.06)] text-tx2'
}

function actionButtonClass(variant: 'primary' | 'success' | 'warning' | 'danger' | 'neutral') {
  const base =
    'rounded-md border px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-30'

  if (variant === 'success') return `${base} border-ac bg-ac text-white hover:bg-[#1f5fda]`
  if (variant === 'warning') return `${base} border-ac bg-[rgba(47,111,228,0.08)] text-ac hover:bg-[rgba(47,111,228,0.14)]`
  if (variant === 'danger') return `${base} border-bd bg-[rgba(17,17,17,0.04)] text-tx hover:bg-[rgba(17,17,17,0.08)]`
  if (variant === 'neutral') return `${base} border-bd bg-white text-tx2 hover:bg-[rgba(47,111,228,0.08)]`
  return `${base} border-ac bg-ac text-white hover:bg-[#1f5fda]`
}

function sectionCardClass(fullWidth = false) {
  return `${fullWidth ? 'md:col-span-2' : ''}`
}

function StatusText({
  active,
  activeText,
  inactiveText,
}: {
  active: boolean
  activeText: string
  inactiveText: string
}) {
  return (
    <div className={`text-sm ${active ? 'text-ac' : 'text-tx2'}`}>
      {active ? activeText : inactiveText}
    </div>
  )
}

function CameraPreview({
  cameras,
  enabled,
  paused,
  t,
}: {
  cameras: Array<{ alias: string; connected: boolean; width: number; height: number }>
  enabled: boolean
  paused: boolean
  t: (key: any) => string
}) {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!enabled || paused) return
    const connected = cameras.filter((camera) => camera.connected)
    if (!connected.length) return

    const timer = setInterval(() => setTick((value) => value + 1), 1500)
    return () => clearInterval(timer)
  }, [cameras, enabled, paused])

  const connected = cameras.filter((camera) => camera.connected)

  if (!enabled) {
    return (
      <div className="flex min-h-[220px] items-center justify-center border-b border-bd bg-white/35 px-4 text-sm text-tx2">
        {t('camerasDisabled')}
      </div>
    )
  }

  if (paused) {
    return (
      <div className="flex min-h-[220px] items-center justify-center border-b border-bd bg-white/35 px-4 text-sm text-tx2">
        {t('hwInitializing')}
      </div>
    )
  }

  if (!connected.length) {
    return (
      <div className="flex min-h-[220px] items-center justify-center border-b border-bd bg-white/35 px-4 text-sm text-tx2">
        {t('noCameraFeed')}
      </div>
    )
  }

  return (
    <div className="grid min-h-[220px] gap-3 border-b border-bd bg-[rgba(47,111,228,0.06)] p-3 lg:grid-cols-2">
      {connected.map((camera) => (
        <div key={camera.alias} className="overflow-hidden rounded-lg border border-bd bg-[#dbe8ff]">
          <div className="flex items-center justify-between bg-[#2f6fe4]/88 px-3 py-2 text-xs text-white">
            <span>{camera.alias}</span>
            <span>{camera.width} x {camera.height}</span>
          </div>
          <img
            src={`/api/dashboard/camera-preview/${camera.alias}?t=${tick}`}
            alt={camera.alias}
            className="aspect-video w-full object-cover"
          />
        </div>
      ))}
    </div>
  )
}

export default function DashboardView() {
  const store = useDataCollection()
  const { state, stats, logs, datasets, loading, currentEpisode, totalEpisodes } = store
  const { hardwareStatus, fetchHardwareStatus } = useDashboard()
  const { t } = useI18n()
  const logRef = useRef<HTMLDivElement>(null)
  const ok = canDo(state)

  const stateLabel: Record<RobotState, string> = {
    disconnected: t('stateDisconnected'),
    connected: t('stateConnected'),
    preparing: t('hwInitializing'),
    teleoperating: t('stateTeleoperating'),
    recording: t('stateRecording'),
  }

  const [camerasEnabled, setCamerasEnabled] = useState(false)
  const [datasetName, setDatasetName] = useState('')
  const [task, setTask] = useState('')
  const [fps, setFps] = useState(30)
  const [numEpisodes, setNumEpisodes] = useState(10)

  useEffect(() => {
    store.connectStatusWs()
    store.loadDatasets()
    store.addLog('RoboClaw UI loaded')
    fetchHardwareStatus()

    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') fetchHardwareStatus()
    }, 5000)

    return () => {
      store.disconnectStatusWs()
      clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight)
  }, [logs])

  useEffect(() => {
    if (loading === 'teleop' || loading === 'record') {
      setCamerasEnabled(false)
    }
  }, [loading])

  function handleRecordStart() {
    if (!datasetName.trim()) {
      store.addLog(t('fillDatasetName'), 'err')
      return
    }

    if (!task.trim()) {
      store.addLog(t('fillTaskDesc'), 'err')
      return
    }

    store.doRecordStart({
      dataset_name: datasetName.trim(),
      task: task.trim(),
      fps,
      num_episodes: numEpisodes,
    })
  }

  const previewPaused = state === 'teleoperating' || state === 'recording'

  return (
    <div className="flex min-h-[calc(100vh-210px)] w-full flex-col overflow-hidden bg-transparent">
      <div className="flex flex-wrap items-center gap-4 border-b border-bd px-4 py-3 text-sm">
        <span className={`rounded px-2 py-1 text-xs font-semibold ${stateBadgeClass(state)}`}>
          {stateLabel[state]}
        </span>
        <span className="text-tx2">Arms: {stats.arms}</span>
        <span className="text-tx2">FPS: {stats.fps}</span>
        <span className="text-tx2">Frames: {stats.frames}</span>
        <span className="text-tx2">Episodes: {stats.episodes}</span>
      </div>

      <div className="grid flex-1 overflow-hidden xl:grid-cols-[minmax(0,1fr),320px]">
        <div className="flex min-h-0 flex-col overflow-y-auto">
          <CameraPreview
            cameras={hardwareStatus?.cameras || []}
            enabled={camerasEnabled}
            paused={previewPaused}
            t={t}
          />

          <div className="grid gap-4 p-4 md:grid-cols-2">
            <GlassPanel className={`tile-enter h-fit p-4 ${sectionCardClass()}`} style={{ animationDelay: '60ms' }}>
              <div className="mb-3 text-sm font-medium text-tx">{t('connection')}</div>
              <div className="space-y-2 text-sm text-tx2">
                {hardwareStatus?.arms.length ? (
                  hardwareStatus.arms.map((arm) => (
                    <div key={arm.alias} className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-tx">{arm.alias}</span>
                      <span>{arm.connected ? t('hwConnected') : t('hwDisconnected')}</span>
                      <span>{arm.calibrated ? t('hwCalibrated') : t('hwUncalibrated')}</span>
                    </div>
                  ))
                ) : (
                  <div>{t('noArms')}</div>
                )}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={!ok.connect || loading === 'connect'}
                  onClick={store.doConnect}
                  className={actionButtonClass('success')}
                >
                  {loading === 'connect' ? t('connecting') : t('connect')}
                </button>
                <button
                  type="button"
                  disabled={!ok.disconnect || !!loading}
                  onClick={store.doDisconnect}
                  className={actionButtonClass('danger')}
                >
                  {t('disconnect')}
                </button>
              </div>
            </GlassPanel>

            <GlassPanel className={`tile-enter h-fit p-4 ${sectionCardClass()}`} style={{ animationDelay: '120ms' }}>
              <div className="mb-3 text-sm font-medium text-tx">{t('cameras')}</div>
              <div className="space-y-2 text-sm text-tx2">
                {hardwareStatus?.cameras.length ? (
                  hardwareStatus.cameras.map((camera) => (
                    <div key={camera.alias} className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-tx">{camera.alias}</span>
                      <span>{camera.connected ? t('hwConnected') : t('hwDisconnected')}</span>
                      {camera.connected && <span>{camera.width} x {camera.height}</span>}
                    </div>
                  ))
                ) : (
                  <div>{t('noCameras')}</div>
                )}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={camerasEnabled}
                  onClick={() => setCamerasEnabled(true)}
                  className={actionButtonClass('success')}
                >
                  {t('enablePreview')}
                </button>
                <button
                  type="button"
                  disabled={!camerasEnabled}
                  onClick={() => setCamerasEnabled(false)}
                  className={actionButtonClass('danger')}
                >
                  {t('disablePreview')}
                </button>
              </div>
            </GlassPanel>

            <GlassPanel className={`tile-enter h-fit p-4 ${sectionCardClass()}`} style={{ animationDelay: '180ms' }}>
              <div className="mb-3 text-sm font-medium text-tx">{t('teleoperation')}</div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={!ok.teleopStart || !!loading}
                  onClick={store.doTeleopStart}
                  className={actionButtonClass('primary')}
                >
                  {loading === 'teleop' ? t('startingTeleop') : t('startTeleop')}
                </button>
                <button
                  type="button"
                  disabled={!ok.teleopStop || !!loading}
                  onClick={store.doTeleopStop}
                  className={actionButtonClass('warning')}
                >
                  {t('stopTeleop')}
                </button>
              </div>
              <div className="mt-4">
                <StatusText
                  active={state === 'teleoperating'}
                  activeText={t('stateTeleoperating')}
                  inactiveText={state === 'recording' ? t('stateRecording') : t('hwInitializing')}
                />
              </div>
            </GlassPanel>

            <GlassPanel className={`tile-enter p-4 ${sectionCardClass(true)}`} style={{ animationDelay: '240ms' }}>
              <div className="mb-4 text-sm font-medium text-tx">{t('recording')}</div>

              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex flex-col gap-1 text-xs text-tx2">
                  {t('datasetName')}
                  <input
                    value={datasetName}
                    onChange={(event) => setDatasetName(event.target.value)}
                    placeholder="my_dataset"
                    className="rounded-md border border-bd bg-white px-3 py-2 text-sm text-tx outline-none focus:border-ac"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs text-tx2">
                  {t('taskDesc')}
                  <input
                    value={task}
                    onChange={(event) => setTask(event.target.value)}
                    placeholder="Pick up the red block"
                    className="rounded-md border border-bd bg-white px-3 py-2 text-sm text-tx outline-none focus:border-ac"
                  />
                </label>
              </div>

              <div className="mt-3 grid gap-3 md:grid-cols-[120px,140px,minmax(0,1fr)]">
                <label className="flex flex-col gap-1 text-xs text-tx2">
                  FPS
                  <input
                    type="number"
                    value={fps}
                    onChange={(event) => setFps(Number(event.target.value) || 30)}
                    min={1}
                    max={120}
                    className="rounded-md border border-bd bg-white px-3 py-2 text-sm text-tx outline-none focus:border-ac"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs text-tx2">
                  {t('numEpisodes')}
                  <input
                    type="number"
                    value={numEpisodes}
                    onChange={(event) => setNumEpisodes(Number(event.target.value) || 10)}
                    min={1}
                    className="rounded-md border border-bd bg-white px-3 py-2 text-sm text-tx outline-none focus:border-ac"
                  />
                </label>
                <div className="flex flex-wrap items-end gap-2">
                  <button
                    type="button"
                    disabled={!ok.recStart || !!loading}
                    onClick={handleRecordStart}
                    className={actionButtonClass('success')}
                  >
                    {loading === 'record' ? t('startingRecord') : t('startRecording')}
                  </button>
                  <button
                    type="button"
                    disabled={!ok.recStop}
                    onClick={store.doRecordStop}
                    className={actionButtonClass('danger')}
                  >
                    {t('stopRecording')}
                  </button>
                </div>
              </div>

              {state === 'recording' && (
                <div className="mt-4 rounded-lg border border-bd bg-white px-4 py-4">
                  <div className="text-sm text-tx">
                    {t('episodesRecorded')}: {currentEpisode} / {totalEpisodes || 0}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={store.doSaveEpisode}
                      className={actionButtonClass('primary')}
                    >
                      {t('saveEpisode')}
                    </button>
                    <button
                      type="button"
                      onClick={store.doDiscardEpisode}
                      className={actionButtonClass('warning')}
                    >
                      {t('discardEpisode')}
                    </button>
                  </div>
                </div>
              )}
            </GlassPanel>
          </div>
        </div>

        <div className="flex min-h-0 flex-col border-l border-bd bg-white/35 max-xl:border-l-0 max-xl:border-t">
          <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
            <GlassPanel className="tile-enter flex min-h-[240px] flex-col p-0" style={{ animationDelay: '300ms' }}>
              <div className="flex items-center justify-between border-b border-bd px-4 py-3">
                <div className="text-sm font-medium text-tx">{t('datasets')}</div>
                <button
                  type="button"
                  onClick={store.loadDatasets}
                  className={actionButtonClass('primary')}
                >
                  {t('refresh')}
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                {datasets.length === 0 ? (
                  <div className="py-8 text-center text-sm text-tx2">{t('noDatasets')}</div>
                ) : (
                  <div className="space-y-2">
                    {datasets.map((dataset) => (
                      <div key={dataset.name} className="rounded-md border border-bd bg-white/70 px-3 py-2 text-sm">
                        <div className="flex items-center gap-2">
                          <span className="flex-1 font-medium text-tx">{dataset.name}</span>
                          <button
                            type="button"
                            onClick={() => {
                              if (confirm(`${t('deleteConfirm')} "${dataset.name}"?`)) {
                                store.deleteDataset(dataset.name)
                              }
                            }}
                            className="rounded border border-rd px-2 py-1 text-xs text-rd hover:bg-rd/10"
                          >
                            {t('del')}
                          </button>
                        </div>
                        <div className="mt-1 text-xs text-tx2">
                          {dataset.total_episodes != null ? `${dataset.total_episodes} ep` : ''}
                          {dataset.total_frames != null ? `${dataset.total_episodes != null ? ' | ' : ''}${dataset.total_frames} fr` : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </GlassPanel>

            <GlassPanel className="tile-enter flex min-h-[240px] flex-col p-0" style={{ animationDelay: '360ms' }}>
              <div className="flex items-center justify-between border-b border-bd px-4 py-3">
                <div className="text-sm font-medium text-tx">{t('log')}</div>
                <button
                  type="button"
                  onClick={store.clearLog}
                  className={actionButtonClass('neutral')}
                >
                  {t('clear')}
                </button>
              </div>
              <div ref={logRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-2 font-mono text-xs">
                {logs.map((entry, index) => (
                  <div
                    key={`${entry.time}-${index}`}
                    className={`border-b border-bd/50 py-1.5 ${
                      entry.cls === 'err' ? 'text-rd' : entry.cls === 'ok' ? 'text-gn' : 'text-tx2'
                    }`}
                  >
                    <span className="mr-2 text-[11px] opacity-70">{entry.time}</span>
                    {entry.message}
                  </div>
                ))}
              </div>
            </GlassPanel>
          </div>
        </div>
      </div>
    </div>
  )
}
