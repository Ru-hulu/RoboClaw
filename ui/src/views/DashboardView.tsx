import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDashboard, type SessionState } from '../controllers/dashboard'
import { useI18n } from '../controllers/i18n'
import { CameraPreviewPanel } from '../components/CameraPreviewPanel'
import { ServoPanel } from '../components/ServoPanel'

function canDo(state: SessionState, hwReady: boolean) {
  const idle = state === 'idle'
  const tele = state === 'teleoperating'
  const rec = state === 'recording'
  return {
    teleopStart: idle && hwReady,
    teleopStop: tele,
    recStart: (idle || tele) && hwReady,
    recStop: rec,
    saveEp: rec,
    discardEp: rec,
  }
}

function ActionBtn({
  children, disabled, onClick, color,
}: {
  children: React.ReactNode; disabled?: boolean; onClick?: () => void
  color: 'ac' | 'gn' | 'rd' | 'yl'
}) {
  const cls: Record<string, string> = {
    ac: 'bg-ac hover:bg-ac2 shadow-glow-ac',
    gn: 'bg-gn hover:bg-gn/90 shadow-glow-gn',
    rd: 'bg-rd hover:bg-rd/90 shadow-glow-rd',
    yl: 'bg-yl hover:bg-yl/90 shadow-glow-yl',
  }
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={`w-full px-4 py-2.5 rounded-lg text-sm font-semibold text-white transition-all
        active:scale-[0.97] disabled:opacity-25 disabled:cursor-not-allowed disabled:shadow-none ${cls[color]}`}
    >
      {children}
    </button>
  )
}

export default function DashboardView() {
  const store = useDashboard()
  const { session, logs, datasets, loading, hardwareStatus: hwStatus } = store
  const { state, episode_phase: episodePhase, saved_episodes: savedEpisodes, target_episodes: targetEpisodes } = session
  const hwReady = hwStatus?.ready ?? false
  const ok = canDo(state, hwReady)
  const logRef = useRef<HTMLDivElement>(null)
  const { t } = useI18n()
  const navigate = useNavigate()

  const [task, setTask] = useState('')
  const [numEp, setNumEp] = useState(10)
  const [episodeTime, setEpisodeTime] = useState(300)
  const [resetTime, setResetTime] = useState(10)

  useEffect(() => {
    store.loadDatasets()
    store.addLog('RoboClaw UI loaded')
    store.fetchHardwareStatus()
    const hwInterval = setInterval(() => {
      if (document.visibilityState === 'visible') store.fetchHardwareStatus()
    }, 5000)
    return () => clearInterval(hwInterval)
  }, [])

  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight)
  }, [logs])

  function handleRecordStart() {
    if (!task.trim()) { store.addLog(t('fillTaskDesc'), 'err'); return }
    store.doRecordStart({
      task: task.trim(),
      num_episodes: numEp,
      episode_time_s: episodeTime,
      reset_time_s: resetTime,
    })
  }

  const stateLabel: Record<string, string> = {
    preparing: t('hwInitializing'),
    teleoperating: t('stateTeleoperating'),
    recording: t('stateRecording'),
  }
  const stateBadgeCls: Record<string, string> = {
    preparing: 'bg-yl/15 text-yl border-yl/30',
    teleoperating: 'bg-ac/15 text-ac border-ac/30',
    recording: 'bg-rd/15 text-rd border-rd/30',
  }

  const hwAccent = !hwStatus ? 'shadow-inset-ac' : hwStatus.ready ? 'shadow-inset-gn' : 'shadow-inset-yl'
  const camerasExist = hwStatus && hwStatus.cameras.length > 0 && hwStatus.cameras.some((c: any) => c.connected)
  const pct = targetEpisodes > 0 ? Math.round((savedEpisodes / targetEpisodes) * 100) : 0

  return (
    <div className="flex flex-col h-full">
      {/* Active state banner */}
      {state !== 'idle' && (
        <div className="flex items-center gap-3 px-4 py-2 border-b border-bd/60 text-sm bg-sf">
          <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold border ${stateBadgeCls[state]}`}>
            {stateLabel[state]}
          </span>
          {state === 'recording' && (
            <span className="text-tx2 font-mono text-xs">{t('savedEpisodes')}: {savedEpisodes} / {targetEpisodes}</span>
          )}
        </div>
      )}

      {session.error && (
        <div className="px-4 py-2 bg-rd/10 border-b border-rd/30 border-l-4 border-l-rd text-rd text-sm font-mono whitespace-pre-wrap">
          {session.error}
        </div>
      )}

      {!hwReady && hwStatus && (
        <div className="px-4 py-2.5 bg-yl/8 border-b border-yl/20 text-yl text-sm font-medium">
          {hwStatus.missing.join(' · ')}
        </div>
      )}

      {session.rerun_web_port > 0 && (state === 'teleoperating' || state === 'recording') && (
        <div className="border-b border-bd">
          <iframe
            src={`${location.protocol}//${location.hostname}:${session.rerun_web_port}`}
            className="w-full border-0"
            style={{ height: '400px' }}
            title="Rerun Visualization"
          />
        </div>
      )}

      {/* Main layout */}
      <div className="flex-1 grid grid-cols-[1fr_280px] overflow-hidden max-[900px]:grid-cols-1">
        {/* Left: controls + monitoring */}
        <div className="flex flex-col overflow-y-auto">
          {/* Top row: 3 control cards horizontal */}
          <div className="flex gap-3 p-4 pb-2 max-[900px]:flex-col">
            {/* Hardware status — clickable */}
            <div
              onClick={() => navigate('/settings')}
              className={`w-[170px] max-[900px]:w-full shrink-0 bg-sf rounded-lg p-3.5 cursor-pointer
                ${hwAccent} transition-all hover:shadow-card-hover animate-slide-up stagger-1`}
            >
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-2xs text-tx3 font-mono uppercase tracking-widest">{t('arms')}</span>
                  <div className="flex items-center gap-1">
                    {hwStatus?.arms.map(arm => (
                      <span key={arm.alias}
                        className={`w-2.5 h-2.5 rounded-full ring-2 ring-white ${!arm.connected ? 'bg-rd' : !arm.calibrated ? 'bg-yl' : 'bg-gn'}`}
                        title={arm.alias}
                      />
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-2xs text-tx3 font-mono uppercase tracking-widest">{t('cameras')}</span>
                  <div className="flex items-center gap-1">
                    {hwStatus?.cameras.map(cam => (
                      <span key={cam.alias}
                        className={`w-2.5 h-2.5 rounded-full ring-2 ring-white ${cam.connected ? 'bg-gn' : 'bg-rd'}`}
                        title={cam.alias}
                      />
                    ))}
                  </div>
                </div>
              </div>
              <div className="mt-2 text-2xs text-tx3 font-medium group-hover:text-ac">
                {hwStatus?.ready ? t('hwReady') : `${hwStatus?.missing?.length ?? 0} ${t('warnings')}`}
              </div>
            </div>

            {/* Teleop */}
            <div className="w-[190px] max-[900px]:w-full shrink-0 bg-sf rounded-lg p-3.5 shadow-card animate-slide-up stagger-2">
              <h3 className="text-2xs text-tx3 font-mono uppercase tracking-widest mb-3">{t('teleoperation')}</h3>
              <div className="space-y-2">
                <ActionBtn color="ac" disabled={!ok.teleopStart || !!loading} onClick={store.doTeleopStart}>
                  {loading === 'teleop' ? t('startingTeleop') : t('startTeleop')}
                </ActionBtn>
                <ActionBtn color="yl" disabled={!ok.teleopStop || !!loading} onClick={store.doTeleopStop}>
                  {t('stopTeleop')}
                </ActionBtn>
              </div>
              {(loading === 'teleop' || state === 'teleoperating') && (
                <div className="mt-3 flex items-center gap-2 text-xs text-ac font-medium">
                  <span className="w-2 h-2 rounded-full bg-ac animate-pulse" />
                  {loading === 'teleop' ? t('hwInitializing') : t('stateTeleoperating')}
                </div>
              )}
            </div>

            {/* Recording */}
            <div className="flex-1 min-w-0 bg-sf rounded-lg p-3.5 shadow-card animate-slide-up stagger-3">
              <h3 className="text-2xs text-tx3 font-mono uppercase tracking-widest mb-3">{t('recording')}</h3>

              <input
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Pick up the red block"
                className="w-full bg-sf2 border border-bd text-tx px-3 py-2 rounded-lg text-sm
                  focus:outline-none focus:border-ac focus:shadow-glow-ac placeholder:text-tx3 mb-3"
              />

              <div className="flex gap-2 items-end flex-wrap">
                <label className="flex flex-col gap-1 text-2xs text-tx3 font-mono w-[72px]">
                  {t('numEpisodes')}
                  <input type="number" value={numEp} onChange={(e) => setNumEp(Number(e.target.value) || 10)} min={1}
                    className="bg-sf2 border border-bd text-tx px-2 py-1.5 rounded text-sm font-mono focus:outline-none focus:border-ac" />
                </label>
                <label className="flex flex-col gap-1 text-2xs text-tx3 font-mono w-[80px]">
                  {t('epTime')}
                  <input type="number" value={episodeTime} onChange={(e) => setEpisodeTime(Number(e.target.value) || 300)} min={1}
                    className="bg-sf2 border border-bd text-tx px-2 py-1.5 rounded text-sm font-mono focus:outline-none focus:border-ac" />
                </label>
                <label className="flex flex-col gap-1 text-2xs text-tx3 font-mono w-[80px]">
                  {t('resetTime')}
                  <input type="number" value={resetTime} onChange={(e) => setResetTime(Number(e.target.value) || 10)} min={0}
                    className="bg-sf2 border border-bd text-tx px-2 py-1.5 rounded text-sm font-mono focus:outline-none focus:border-ac" />
                </label>
                <div className="flex gap-2 ml-auto">
                  <ActionBtn color="gn" disabled={!ok.recStart || !!loading} onClick={handleRecordStart}>
                    {loading === 'record' ? t('startingRecord') : t('startRecording')}
                  </ActionBtn>
                  <ActionBtn color="rd" disabled={!ok.recStop} onClick={store.doRecordStop}>
                    {t('stopRecording')}
                  </ActionBtn>
                </div>
              </div>

              {state === 'recording' && (
                <div className="mt-3 pt-3 border-t border-bd/40">
                  <div className="flex items-center justify-between text-xs mb-1.5">
                    <span className="font-mono text-tx2">{savedEpisodes} / {targetEpisodes}</span>
                    <span className="font-mono font-bold text-ac">{pct}%</span>
                  </div>
                  <div className="w-full h-2 bg-sf2 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-ac2 to-ac rounded-full transition-all duration-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="flex gap-2 mt-3">
                    <ActionBtn color="gn" disabled={episodePhase !== 'recording'} onClick={store.doSaveEpisode}>
                      {episodePhase === 'saving' ? t('episodeSaving') : t('saveEpisode')}
                    </ActionBtn>
                    <ActionBtn color="yl" disabled={episodePhase !== 'recording'} onClick={store.doDiscardEpisode}>
                      {t('discardEpisode')}
                    </ActionBtn>
                    {episodePhase === 'resetting' && (
                      <ActionBtn color="ac" onClick={store.doSkipReset}>
                        {t('skipReset')}
                      </ActionBtn>
                    )}
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-xs font-medium">
                    {(episodePhase === 'recording' || !episodePhase) && (
                      <><span className="w-2 h-2 rounded-full bg-ac animate-pulse" /><span className="text-ac">{t('stateRecording')}</span></>
                    )}
                    {episodePhase === 'saving' && (
                      <><span className="w-2 h-2 rounded-full bg-yl animate-pulse" /><span className="text-yl">{t('episodeSaving')}</span></>
                    )}
                    {episodePhase === 'resetting' && (
                      <><span className="w-2 h-2 rounded-full bg-yl animate-pulse" /><span className="text-yl">{t('episodeResetting')}</span></>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Bottom: live monitoring */}
          <div className="grid grid-cols-2 gap-3 px-4 py-2 flex-1 min-h-[240px] max-[900px]:grid-cols-1">
            {camerasExist ? (
              <CameraPreviewPanel cameras={hwStatus!.cameras} busy={session.state !== 'idle'} />
            ) : (
              <div className="bg-sf rounded-lg p-4 shadow-card flex items-center justify-center text-sm text-tx3">
                {t('noCameraFeed')}
              </div>
            )}
            <ServoPanel state={state} />
          </div>
        </div>

        {/* Right sidebar */}
        <div className="bg-sf border-l border-bd/50 flex flex-col overflow-hidden max-[900px]:border-l-0 max-[900px]:border-t max-[900px]:max-h-[50vh]">
          <div className="px-3 py-2.5 border-b border-bd/40">
            <div className="flex items-center justify-between">
              <h3 className="text-2xs text-tx3 font-mono uppercase tracking-widest">{t('datasets')}</h3>
              <button
                onClick={store.loadDatasets}
                className="px-2.5 py-0.5 bg-ac/10 text-ac rounded text-xs font-medium hover:bg-ac/20 transition-colors"
              >
                {t('refresh')}
              </button>
            </div>
          </div>
          <div className="overflow-y-auto flex-1 p-2">
            {datasets.length === 0 && (
              <div className="text-tx3 text-center py-6 text-sm">{t('noDatasets')}</div>
            )}
            {datasets.map((d) => (
              <div
                key={d.name}
                className="bg-bg border border-bd/30 rounded-lg mb-1.5 px-3 py-2 flex items-center gap-2 text-sm"
              >
                <span className="flex-1 font-semibold text-tx truncate">{d.name}</span>
                <span className="text-tx3 text-2xs font-mono whitespace-nowrap">
                  {d.total_episodes != null ? `${d.total_episodes} ep` : ''}
                  {d.total_frames != null ? ` · ${d.total_frames} fr` : ''}
                </span>
                <button
                  onClick={() => {
                    if (confirm(`${t('deleteConfirm')} "${d.name}"?`)) store.deleteDataset(d.name)
                  }}
                  className="px-2 py-0.5 text-rd/60 rounded text-xs hover:text-rd hover:bg-rd/10 transition-colors"
                >
                  {t('del')}
                </button>
              </div>
            ))}
          </div>

          <div className="px-3 py-2.5 border-t border-bd/40">
            <div className="flex items-center justify-between">
              <h3 className="text-2xs text-tx3 font-mono uppercase tracking-widest">{t('log')}</h3>
              <button
                onClick={store.clearLog}
                className="px-2.5 py-0.5 text-tx3 rounded-sm text-xs hover:text-tx2 hover:bg-bd/30 transition-colors"
              >
                {t('clear')}
              </button>
            </div>
          </div>
          <div ref={logRef} className="flex-1 overflow-y-auto px-3 py-1 font-mono text-xs">
            {logs.map((entry, i) => (
              <div
                key={i}
                className={`py-0.5 border-b border-bd/20 ${
                  entry.cls === 'err' ? 'text-rd' : entry.cls === 'ok' ? 'text-gn' : 'text-tx3'
                }`}
              >
                <span className="text-tx3/60 mr-2 text-2xs">{entry.time}</span>
                {entry.message}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
