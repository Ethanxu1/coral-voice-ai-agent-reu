// rosbridge connection hook — the frontend talks to the Pi's rosbridge_server
// (same bus the Mac director/audio/speaker use). Set the Pi IP via VITE_ROS_HOST.
import { useEffect, useRef, useState } from 'react'
// roslib has no bundled types; see roslib.d.ts
import ROSLIB from 'roslib'

const HOST = (import.meta as any).env?.VITE_ROS_HOST || 'localhost'
const PORT = (import.meta as any).env?.VITE_ROS_BRIDGE_PORT || '9090'

export interface DemoCommand {
  action: string
  [key: string]: unknown
}

export interface DemoStateMsg {
  state: string
  [key: string]: unknown
}

export function useRosbridge() {
  const rosRef = useRef<any>(null)
  const [connected, setConnected] = useState(false)
  const [demoState, setDemoState] = useState<DemoStateMsg | null>(null)
  const [command, setCommand] = useState<DemoCommand | null>(null)

  useEffect(() => {
    const ros = new ROSLIB.Ros({ url: `ws://${HOST}:${PORT}` })
    rosRef.current = ros
    ros.on('connection', () => setConnected(true))
    ros.on('close', () => setConnected(false))
    ros.on('error', () => setConnected(false))

    const stateTopic = new ROSLIB.Topic({ ros, name: '/demo_state', messageType: 'std_msgs/String' })
    stateTopic.subscribe((m: any) => setDemoState(JSON.parse(m.data)))

    const cmdTopic = new ROSLIB.Topic({ ros, name: '/demo/command', messageType: 'std_msgs/String' })
    cmdTopic.subscribe((m: any) => setCommand(JSON.parse(m.data)))

    return () => {
      stateTopic.unsubscribe()
      cmdTopic.unsubscribe()
      ros.close()
    }
  }, [])

  // Publish the voice-adjust result back to the director after a recording.
  function publishAudioResult(result: Record<string, unknown>) {
    const topic = new ROSLIB.Topic({
      ros: rosRef.current, name: '/demo/audio_result', messageType: 'std_msgs/String',
    })
    topic.publish(new ROSLIB.Message({ data: JSON.stringify(result) }))
  }

  // Call the Mac audio node's AudioToAction service with base64 webm mic audio.
  function callAudioToAction(audioB64: string, stateJson = '{}'): Promise<any> {
    return new Promise((resolve, reject) => {
      const service = new ROSLIB.Service({
        ros: rosRef.current,
        name: '/audio/audio_to_action',
        serviceType: 'coral_demo/AudioToAction',
      })
      const req = new ROSLIB.ServiceRequest({ audio_b64: audioB64, state_json: stateJson })
      service.callService(req, resolve, reject)
    })
  }

  return { connected, demoState, command, publishAudioResult, callAudioToAction }
}
