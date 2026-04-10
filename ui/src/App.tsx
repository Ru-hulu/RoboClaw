import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ControlView from './views/ControlView'
import DataView from './views/DataView'
import LogView from './views/LogView'
import ChatView from './views/ChatView'
import SettingsView from './views/SettingsView'
import Layout from './components/Layout'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/control" replace />} />
          <Route path="control" element={<ControlView />} />
          <Route path="data" element={<DataView />} />
          <Route path="settings" element={<SettingsView />} />
          <Route path="logs" element={<LogView />} />
          <Route path="chat" element={<ChatView />} />
          <Route path="dashboard" element={<Navigate to="/control" replace />} />
          <Route path="setup" element={<Navigate to="/settings" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
