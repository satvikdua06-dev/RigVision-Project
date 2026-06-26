import { useEffect, useRef } from 'react'
import Scene3D from './components/Scene3D.jsx'
import Sidebar from './components/Sidebar.jsx'
import TopBar from './components/TopBar.jsx'
import { useSimulation } from './hooks/useSimulation.js'
import { useRigStore } from './stores/useRigStore.js'

// Clock tick to force TopBar re-render every second
function useClockTick() {
  const [, setTick] = [null, () => {}]
  useEffect(() => {
    const id = setInterval(() => {
      document.querySelector('[data-clock]') &&
        (document.querySelector('[data-clock]').textContent =
          new Date().toLocaleTimeString('en-IN', { hour12: false }) + ' IST')
    }, 1000)
    return () => clearInterval(id)
  }, [])
}

export default function App() {
  // 1. Pull the connection function from your store
  const connectToBackend = useRigStore(s => s.connectToBackend)

  // 2. Start the real-time stream as soon as the app mounts
  useEffect(() => {
    connectToBackend()
  }, [connectToBackend])

  // 3. Comment out the old static simulation so they don't conflict
  // useSimulation()

  return (
    <div style={{ width:'100vw', height:'100vh', display:'flex', flexDirection:'column', overflow:'hidden' }}>
      <TopBar />
      <div style={{ flex:1, display:'flex', overflow:'hidden' }}>
        <Sidebar />
        
        {/* 3D Canvas takes remaining space */}
        <div style={{ flex:1, position:'relative' }}>
          <Scene3D />

          {/* Corner watermark */}
          <div style={{
            position:'absolute', bottom:16, left:16, pointerEvents:'none',
            fontFamily:"'Share Tech Mono'", fontSize:10, color:'rgba(0,180,255,0.25)',
            letterSpacing:2,
          }}>
            RigVision · LNMIIT · RIGVISION-3D · PHASE 1
          </div>

          {/* Controls hint */}
          <div style={{
            position:'absolute', bottom:16, right:80,
            fontFamily:"'Share Tech Mono'", fontSize:9.5,
            color:'rgba(90,138,170,0.6)', pointerEvents:'none',
            textAlign:'right', lineHeight:1.8, letterSpacing:1,
          }}>
            ORBIT: drag · ZOOM: scroll · PAN: right-drag<br/>
            CLICK zone/person to inspect
          </div>
        </div>
      </div>
    </div>
  )
}