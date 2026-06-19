// App root — the demo is driven by the Director over rosbridge, so the whole
// UI is the Demo view. (The old WebSocket-to-:8000 chat/sim app was removed in
// the ROS reorg.)
import Demo from './pages/Demo'

export default function App() {
  return <Demo />
}
