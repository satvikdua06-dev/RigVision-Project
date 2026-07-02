import { useEffect, useState } from 'react'
import Scene3D from './components/Scene3D.jsx'
import Sidebar from './components/Sidebar.jsx'
import TopBar from './components/TopBar.jsx'
import { useRigStore } from './stores/useRigStore.js'
import CameraFeeds from './components/CameraFeeds.jsx'
import DiagnosticsModal from './components/DiagnosticsModal.jsx'
import SensorConsole from './components/SensorConsole.jsx'
import NotificationAlert from './components/NotificationAlert.jsx'

export default function App() {
  const connectToBackend = useRigStore(s => s.connectToBackend)
  const [route, setRoute] = useState(window.location.hash)

  useEffect(() => {
    const onHash = () => setRoute(window.location.hash)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    connectToBackend()
  }, [connectToBackend])

  // Routing: the sensor console is served on its own dev port (5174) so it can sit
  // on a second screen alongside the 3D dashboard (5173). Hash route still works too.
  const isConsolePort = window.location.port === '5174'
  if (isConsolePort || route === '#/sensors') return <SensorConsole />

  return (
    <div style={{ width:'100vw', height:'100vh', display:'flex', flexDirection:'column', overflow:'hidden' }}>
      <TopBar />
      <div style={{ flex:1, display:'flex', overflow:'hidden' }}>
        <Sidebar />

        {/* 3D Canvas takes remaining space */}
        <div style={{ flex:1, position:'relative' }}>
          <Scene3D />

          {/* Overlay for Camera Feeds */}
          <CameraFeeds />

          {/* Corner watermark */}
          <div style={{
            position:'absolute', bottom:16, left:16, pointerEvents:'none',
            fontFamily:'var(--font-mono)', fontSize:10, color:'var(--text-dim)',
            letterSpacing:1,
          }}>
            RigVision · LNMIIT · RIGVISION-3D · PHASE 1
          </div>

          {/* Controls hint */}
          <div style={{
            position:'absolute', bottom:16, right:80,
            fontFamily:'var(--font-mono)', fontSize:9.5,
            color:'var(--text-dim)', pointerEvents:'none',
            textAlign:'right', lineHeight:1.8, letterSpacing:0.5,
          }}>
            ORBIT: drag · ZOOM: scroll · PAN: right-drag<br/>
            CLICK zone/person to inspect
          </div>
        </div>
      </div>

      {/* Diagnostics Modal Window rendered at root level */}
      <DiagnosticsModal />

      {/* Real-time Anomaly Notification Toast Overlay */}
      <NotificationAlert />
    </div>
  )
}
