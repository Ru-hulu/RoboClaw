import { useState, useEffect } from 'react'
import { useSetup, deviceLabel } from '../../controllers/setup'
import { useI18n } from '../../controllers/i18n'
import type { CatalogModel } from '../../controllers/setup'
import ScanArea from './ScanArea'
import DeviceNode from './DeviceNode'

const STEPS = ['select', 'scan', 'identify', 'review'] as const
const btnBack = 'px-4 py-1.5 text-sm text-tx2 hover:text-tx'
const btnPrimary = 'px-4 py-1.5 text-sm bg-ac text-white rounded hover:bg-ac/90 disabled:opacity-40'
const btnOutline = 'px-4 py-1.5 text-sm border border-ac text-ac rounded hover:bg-ac/10'
const cardBase = 'px-5 py-3 rounded-lg border text-sm font-medium transition-colors'
const formBox = 'mt-2 p-3 bg-sf border border-bd rounded-lg space-y-2'
const inputCls = 'w-full px-3 py-1.5 text-sm bg-bg border border-bd rounded focus:border-ac outline-none text-tx'

// -- Step Indicator ----------------------------------------------------------

function StepIndicator({ current }: { current: string }) {
  const idx = STEPS.indexOf(current as (typeof STEPS)[number])
  return (
    <div className="flex items-center justify-center gap-2 mb-6">
      {STEPS.map((s, i) => (
        <div key={s} className={`w-2.5 h-2.5 rounded-full transition-colors ${
          i === idx ? 'bg-ac' : i < idx ? 'bg-ac/40' : 'bg-bd'
        }`} />
      ))}
    </div>
  )
}

// -- Step 1: Model Select ----------------------------------------------------

function ModelSelect() {
  const { catalog, selectedCategory, selectedModel, setCategory, setModel, goToStep, cancelWizard } =
    useSetup()
  const categories = catalog?.categories ?? []
  const models: CatalogModel[] =
    selectedCategory && catalog?.models ? catalog.models[selectedCategory] ?? [] : []

  return (
    <div className="space-y-4">
      <div className="flex gap-3 flex-wrap">
        {categories.map((cat) => (
          <button key={cat.id} disabled={!cat.supported} onClick={() => setCategory(cat.id)}
            className={`${cardBase} ${!cat.supported ? 'border-bd bg-sf/40 text-tx2 cursor-not-allowed'
              : cat.id === selectedCategory ? 'border-ac bg-ac/10 text-ac' : 'border-bd bg-sf hover:border-ac text-tx'}`}>
            {cat.id}
            {!cat.supported && <span className="block text-2xs text-tx2 mt-0.5">即将支持</span>}
          </button>
        ))}
      </div>
      {selectedCategory && models.length > 0 && (
        <div className="flex gap-3 flex-wrap">
          {models.map((m) => (
            <button key={m.name} onClick={() => { setModel(m.name); goToStep('scan') }}
              className={`${cardBase} ${m.name === selectedModel ? 'border-ac bg-ac/10 text-ac' : 'border-bd bg-sf hover:border-ac text-tx'}`}>
              {m.name}
              {m.roles.length > 0 && <span className="block text-2xs text-tx2 mt-0.5">{m.roles.join(' / ')}</span>}
            </button>
          ))}
        </div>
      )}
      <div className="flex justify-end pt-2">
        <button onClick={cancelWizard} className={btnBack}>取消</button>
      </div>
    </div>
  )
}

// -- Step 2: Scan ------------------------------------------------------------

function ScanStep() {
  const { scannedPorts, scannedCameras, scanning, doScan, goToStep } = useSetup()
  useEffect(() => { doScan() }, [])

  const hasDevices = scannedPorts.length > 0 || scannedCameras.length > 0

  return (
    <div className="space-y-4">
      <ScanArea ports={scannedPorts} cameras={scannedCameras} scanning={scanning} />
      <div className="flex justify-between pt-2">
        <button onClick={() => goToStep('select')} className={btnBack}>返回</button>
        <div className="flex gap-2">
          {!scanning && !hasDevices && (
            <button onClick={doScan} className={btnOutline}>重新扫描</button>
          )}
          {!scanning && hasDevices && (
            <button onClick={() => goToStep('identify')} className={btnPrimary}>下一步</button>
          )}
        </div>
      </div>
    </div>
  )
}

// -- Step 3: Identify --------------------------------------------------------

function PortAssignForm({ stableId, roles, model }: {
  stableId: string; roles: string[]; model: string
}) {
  const { sessionAssign } = useSetup()
  const [alias, setAlias] = useState('')
  const [role, setRole] = useState('')

  function submit() {
    if (!alias.trim()) return
    const combined = role ? `${alias.trim()}_${role}` : alias.trim()
    const spec = role ? `${model}_${role}` : model
    sessionAssign(stableId, combined, spec)
  }

  return (
    <div className={formBox}>
      {roles.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {roles.map((r) => (
            <button key={r} onClick={() => setRole(r)}
              className={`px-3 py-1 text-xs rounded border transition-colors ${
                role === r ? 'border-ac bg-ac/10 text-ac' : 'border-bd text-tx2 hover:border-ac'}`}>
              {r}
            </button>
          ))}
        </div>
      )}
      <input value={alias} onChange={(e) => setAlias(e.target.value)}
        placeholder="设备名称" className={inputCls} />
      {alias.trim() && (
        <p className="text-2xs text-tx2">名称预览: {role ? `${alias.trim()}_${role}` : alias.trim()}</p>
      )}
      <button onClick={submit} disabled={!alias.trim() || (roles.length > 0 && !role)}
        className="px-3 py-1 text-xs bg-ac text-white rounded disabled:opacity-40">确认分配</button>
    </div>
  )
}

function CameraAssignForm({ stableId }: { stableId: string }) {
  const { sessionAssign } = useSetup()
  const [alias, setAlias] = useState('')

  return (
    <div className={formBox}>
      <input value={alias} onChange={(e) => setAlias(e.target.value)}
        placeholder="摄像头名称" className={inputCls} />
      <button onClick={() => { if (alias.trim()) sessionAssign(stableId, alias.trim(), 'opencv') }}
        disabled={!alias.trim()}
        className="px-3 py-1 text-xs bg-ac text-white rounded disabled:opacity-40">确认分配</button>
    </div>
  )
}

function IdentifyStep() {
  const { t } = useI18n()
  const {
    catalog, selectedCategory, selectedModel,
    scannedPorts, scannedCameras, assignments,
    startMotion, stopMotion, goToStep,
  } = useSetup()
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => { startMotion(); return () => { stopMotion() } }, [])

  const roles = catalog?.models[selectedCategory]?.find((m) => m.name === selectedModel)?.roles ?? []
  const assignedIds = new Set(assignments.map((a) => a.interface_stable_id))
  const freePorts = scannedPorts.filter((p) => !assignedIds.has(p.stable_id))
  const freeCams = scannedCameras.filter((c) => !assignedIds.has(c.stable_id))

  return (
    <div className="space-y-4">
      <p className="text-sm text-tx2">{t('moveArmPrompt')}</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Unassigned */}
        <div>
          <h4 className="text-xs text-tx2 uppercase tracking-wider font-medium mb-3">未分配设备</h4>
          <div className="space-y-2">
            {freePorts.map((port) => (
              <div key={port.stable_id}>
                <div onClick={() => setActiveId(activeId === port.stable_id ? null : port.stable_id)}
                  className="cursor-pointer">
                  <DeviceNode id={`port:${port.stable_id}`} kind="port"
                    label={deviceLabel(port)} sublabel={`${port.motor_ids.length} motors`} moved={port.moved} />
                </div>
                {activeId === port.stable_id && port.moved && (
                  <PortAssignForm stableId={port.stable_id} roles={roles} model={selectedModel} />
                )}
              </div>
            ))}
            {freeCams.map((cam) => (
              <div key={cam.stable_id}>
                <div onClick={() => setActiveId(activeId === cam.stable_id ? null : cam.stable_id)}
                  className="cursor-pointer">
                  <DeviceNode id={`camera:${cam.stable_id}`} kind="camera"
                    label={deviceLabel(cam)} sublabel={`${cam.width}×${cam.height}`} previewUrl={cam.preview_url} />
                </div>
                {activeId === cam.stable_id && <CameraAssignForm stableId={cam.stable_id} />}
              </div>
            ))}
            {freePorts.length === 0 && freeCams.length === 0 && (
              <p className="text-sm text-tx2">所有设备已分配</p>
            )}
          </div>
        </div>
        {/* Assigned */}
        <div>
          <h4 className="text-xs text-tx2 uppercase tracking-wider font-medium mb-3">已分配设备</h4>
          <div className="space-y-2">
            {assignments.map((a) => (
              <div key={a.alias} className="flex items-center gap-2 bg-sf border border-gn/30 rounded-lg px-3 py-2">
                <span className="w-2 h-2 rounded-full bg-gn" />
                <span className="text-sm font-medium text-tx flex-1">{a.alias}</span>
                <span className="text-2xs text-tx2">{a.spec_name}</span>
              </div>
            ))}
            {assignments.length === 0 && <p className="text-sm text-tx2">暂无已分配设备</p>}
          </div>
        </div>
      </div>
      <div className="flex justify-between pt-2">
        <button onClick={async () => { await stopMotion(); goToStep('scan') }} className={btnBack}>返回</button>
        <button onClick={async () => { await stopMotion(); goToStep('review') }}
          disabled={assignments.length === 0} className={btnPrimary}>完成分配</button>
      </div>
    </div>
  )
}

// -- Step 4: Review ----------------------------------------------------------

function ReviewStep() {
  const { assignments, sessionUnassign, sessionCommit, goToStep } = useSetup()

  return (
    <div className="space-y-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-tx2 text-xs border-b border-bd">
            <th className="py-2 font-medium">名称</th>
            <th className="py-2 font-medium">规格</th>
            <th className="py-2 font-medium">接口</th>
            <th className="py-2 font-medium w-16" />
          </tr>
        </thead>
        <tbody>
          {assignments.map((a) => (
            <tr key={a.alias} className="border-b border-bd/50">
              <td className="py-2 text-tx">{a.alias}</td>
              <td className="py-2 text-tx2">{a.spec_name}</td>
              <td className="py-2 text-tx2 text-2xs truncate max-w-[200px]">{a.interface_stable_id}</td>
              <td className="py-2">
                <button onClick={() => sessionUnassign(a.alias)} className="text-2xs text-rd hover:text-rd/80">
                  移除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {assignments.length === 0 && (
        <p className="text-sm text-tx2 text-center py-4">暂无分配，请返回添加设备</p>
      )}
      <div className="flex justify-between pt-2">
        <button onClick={() => goToStep('identify')} className={btnBack}>返回修改</button>
        <button onClick={sessionCommit} disabled={assignments.length === 0} className={btnPrimary}>
          确认提交
        </button>
      </div>
    </div>
  )
}

// -- Main Wizard -------------------------------------------------------------

export default function DiscoveryWizard() {
  const { wizardStep, error } = useSetup()

  return (
    <div className="rounded-xl border border-bd bg-bg p-6 space-y-4">
      {error && (
        <div className="rounded-lg border border-rd/30 bg-rd/5 p-3 text-sm text-rd">{error}</div>
      )}
      <StepIndicator current={wizardStep} />
      {wizardStep === 'select' && <ModelSelect />}
      {wizardStep === 'scan' && <ScanStep />}
      {wizardStep === 'identify' && <IdentifyStep />}
      {wizardStep === 'review' && <ReviewStep />}
    </div>
  )
}
