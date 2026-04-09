import { useState, useEffect } from 'react'
import './PrimitivesTest.css'

interface Primitive {
  name: string
  description: string
  joints: { [key: string]: number }
  category: string
  speed?: number
}

interface Gesture {
  name: string
  description: string
  category: string
  keyframe_count: number
  total_duration: number
  tags: string[]
}

interface ItemStatus {
  tested: boolean
  working: boolean | null // null = untested, true = working, false = broken
}

interface Props {
  onBack: () => void
  isConnected: boolean
}

const CATEGORY_ORDER = [
  'rest',
  'arms_out',
  'arms_forward',
  'elbow',
  'head',
  'torso',
]

const CATEGORY_LABELS: { [key: string]: string } = {
  rest: 'NEUTRAL / REST',
  arms_out: 'ARMS OUT (Abduction)',
  arms_forward: 'ARMS FORWARD (Flexion)',
  elbow: 'ELBOW',
  head: 'HEAD',
  torso: 'TORSO',
}

const GESTURE_CATEGORY_ORDER = ['greeting', 'head', 'emotion', 'attention', 'conversational']

const GESTURE_CATEGORY_LABELS: { [key: string]: string } = {
  greeting: 'GREETINGS',
  head: 'HEAD GESTURES',
  emotion: 'EMOTIONAL',
  attention: 'ATTENTION',
  conversational: 'CONVERSATIONAL',
}

function PrimitivesTest({ onBack, isConnected }: Props) {
  const [primitives, setPrimitives] = useState<Primitive[]>([])
  const [gestures, setGestures] = useState<Gesture[]>([])
  const [selectedItem, setSelectedItem] = useState<{ type: 'primitive' | 'gesture'; data: Primitive | Gesture } | null>(null)
  const [statuses, setStatuses] = useState<{ [key: string]: ItemStatus }>({})
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'primitives' | 'gestures'>('primitives')

  // Load primitives and gestures on mount
  useEffect(() => {
    fetchPrimitives()
    fetchGestures()
    // Load saved statuses from localStorage
    const saved = localStorage.getItem('primitiveStatuses')
    if (saved) {
      setStatuses(JSON.parse(saved))
    }
  }, [])

  // Save statuses to localStorage whenever they change
  useEffect(() => {
    if (Object.keys(statuses).length > 0) {
      localStorage.setItem('primitiveStatuses', JSON.stringify(statuses))
    }
  }, [statuses])

  const fetchPrimitives = async () => {
    try {
      const response = await fetch('http://localhost:8000/primitives')
      const data = await response.json()
      setPrimitives(data.primitives)
    } catch (err) {
      setError('Failed to fetch primitives. Is the server running?')
    }
  }

  const fetchGestures = async () => {
    try {
      const response = await fetch('http://localhost:8000/gestures')
      const data = await response.json()
      setGestures(data.gestures)
    } catch (err) {
      console.error('Failed to fetch gestures')
    }
  }

  const executePrimitive = async (name: string) => {
    if (!isConnected) {
      setError('Not connected to server')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`http://localhost:8000/test-primitive/${name}`, {
        method: 'POST',
      })
      const data = await response.json()

      if (data.success) {
        setStatuses((prev) => ({
          ...prev,
          [name]: { tested: true, working: prev[name]?.working ?? null },
        }))
        const prim = primitives.find((p) => p.name === name)
        if (prim) {
          setSelectedItem({ type: 'primitive', data: { ...prim, joints: data.joints } })
        }
      } else {
        setError(data.error || 'Failed to execute primitive')
      }
    } catch (err) {
      setError('Failed to execute primitive. Is the server running?')
    } finally {
      setIsLoading(false)
    }
  }

  const executeGesture = async (name: string) => {
    if (!isConnected) {
      setError('Not connected to server')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`http://localhost:8000/test-gesture/${name}`, {
        method: 'POST',
      })
      const data = await response.json()

      if (data.success) {
        setStatuses((prev) => ({
          ...prev,
          [name]: { tested: true, working: prev[name]?.working ?? null },
        }))
        const gesture = gestures.find((g) => g.name === name)
        if (gesture) {
          setSelectedItem({ type: 'gesture', data: gesture })
        }
      } else {
        setError(data.error || 'Failed to execute gesture')
      }
    } catch (err) {
      setError('Failed to execute gesture. Is the server running?')
    } finally {
      setIsLoading(false)
    }
  }

  const executeReset = async () => {
    if (!isConnected) return
    try {
      await fetch('http://localhost:8000/test-primitive/neutral', { method: 'POST' })
    } catch (err) {
      setError('Failed to reset')
    }
  }

  const markItem = (name: string, working: boolean) => {
    setStatuses((prev) => ({
      ...prev,
      [name]: { tested: true, working },
    }))
  }

  const clearStatuses = () => {
    setStatuses({})
    localStorage.removeItem('primitiveStatuses')
  }

  const exportVerified = () => {
    const verified = Object.entries(statuses)
      .filter(([, status]) => status.working === true)
      .map(([name]) => name)

    const data = {
      verified_primitives: verified,
      exported_at: new Date().toISOString(),
      total_count: verified.length,
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'verified_primitives.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  // Group primitives by category
  const groupedPrimitives = primitives.reduce(
    (acc, prim) => {
      const category = prim.category || 'other'
      if (!acc[category]) {
        acc[category] = []
      }
      acc[category].push(prim)
      return acc
    },
    {} as { [key: string]: Primitive[] }
  )

  // Group gestures by category
  const groupedGestures = gestures.reduce(
    (acc, gesture) => {
      const category = gesture.category || 'other'
      if (!acc[category]) {
        acc[category] = []
      }
      acc[category].push(gesture)
      return acc
    },
    {} as { [key: string]: Gesture[] }
  )

  const getStatusIcon = (name: string) => {
    const status = statuses[name]
    if (!status || !status.tested) return ''
    if (status.working === true) return ' ✓'
    if (status.working === false) return ' ⚠️'
    return ' ○'
  }

  const getButtonClass = (name: string, isGesture = false) => {
    const baseClass = isGesture ? 'gesture-btn' : 'primitive-btn'
    const status = statuses[name]
    if (!status) return baseClass
    if (status.working === true) return `${baseClass} working`
    if (status.working === false) return `${baseClass} broken`
    if (status.tested) return `${baseClass} tested`
    return baseClass
  }

  // Calculate stats
  const totalItems = primitives.length + gestures.length
  const testedCount = Object.values(statuses).filter((s) => s.tested).length
  const workingCount = Object.values(statuses).filter((s) => s.working === true).length
  const brokenCount = Object.values(statuses).filter((s) => s.working === false).length

  return (
    <div className="primitives-test">
      <div className="primitives-header">
        <h2>PRIMITIVES & GESTURES TESTING</h2>
        <div className="header-buttons">
          <button className="header-btn" onClick={executeReset} disabled={!isConnected}>
            Reset
          </button>
          <button className="header-btn" onClick={() => executePrimitive('neutral')} disabled={!isConnected}>
            Neutral
          </button>
          <button className="header-btn" onClick={onBack}>
            Back
          </button>
        </div>
      </div>

      <div className="stats-bar">
        <span className="stat">Total: {totalItems}</span>
        <span className="stat">Tested: {testedCount}</span>
        <span className="stat working">Working: {workingCount}</span>
        <span className="stat broken">Broken: {brokenCount}</span>
        <button className="small-btn" onClick={clearStatuses}>
          Clear All
        </button>
        <button className="small-btn export" onClick={exportVerified} disabled={workingCount === 0}>
          Export Verified
        </button>
      </div>

      <div className="tab-bar">
        <button
          className={`tab-btn ${activeTab === 'primitives' ? 'active' : ''}`}
          onClick={() => setActiveTab('primitives')}
        >
          Primitives ({primitives.length})
        </button>
        <button
          className={`tab-btn ${activeTab === 'gestures' ? 'active' : ''}`}
          onClick={() => setActiveTab('gestures')}
        >
          Gestures ({gestures.length})
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="primitives-content">
        <div className="primitives-list">
          {activeTab === 'primitives' ? (
            <>
              {CATEGORY_ORDER.map((category) => {
                const prims = groupedPrimitives[category]
                if (!prims || prims.length === 0) return null

                return (
                  <div key={category} className="category-section">
                    <h3>{CATEGORY_LABELS[category] || category.toUpperCase()}</h3>
                    <div className="primitive-buttons">
                      {prims.map((prim) => (
                        <button
                          key={prim.name}
                          className={getButtonClass(prim.name)}
                          onClick={() => {
                            setSelectedItem({ type: 'primitive', data: prim })
                            executePrimitive(prim.name)
                          }}
                          disabled={isLoading || !isConnected}
                          title={prim.description}
                        >
                          {prim.name.replace(/_/g, ' ')}
                          {getStatusIcon(prim.name)}
                        </button>
                      ))}
                    </div>
                  </div>
                )
              })}

              {Object.keys(groupedPrimitives)
                .filter((cat) => !CATEGORY_ORDER.includes(cat))
                .map((category) => {
                  const prims = groupedPrimitives[category]
                  if (!prims || prims.length === 0) return null

                  return (
                    <div key={category} className="category-section">
                      <h3>{category.toUpperCase()}</h3>
                      <div className="primitive-buttons">
                        {prims.map((prim) => (
                          <button
                            key={prim.name}
                            className={getButtonClass(prim.name)}
                            onClick={() => {
                              setSelectedItem({ type: 'primitive', data: prim })
                              executePrimitive(prim.name)
                            }}
                            disabled={isLoading || !isConnected}
                            title={prim.description}
                          >
                            {prim.name.replace(/_/g, ' ')}
                            {getStatusIcon(prim.name)}
                          </button>
                        ))}
                      </div>
                    </div>
                  )
                })}
            </>
          ) : (
            <>
              {GESTURE_CATEGORY_ORDER.map((category) => {
                const categoryGestures = groupedGestures[category]
                if (!categoryGestures || categoryGestures.length === 0) return null

                return (
                  <div key={category} className="category-section gesture-category">
                    <h3>{GESTURE_CATEGORY_LABELS[category] || category.toUpperCase()}</h3>
                    <div className="primitive-buttons">
                      {categoryGestures.map((gesture) => (
                        <button
                          key={gesture.name}
                          className={getButtonClass(gesture.name, true)}
                          onClick={() => {
                            setSelectedItem({ type: 'gesture', data: gesture })
                            executeGesture(gesture.name)
                          }}
                          disabled={isLoading || !isConnected}
                          title={`${gesture.description} (${gesture.keyframe_count} keyframes, ${gesture.total_duration.toFixed(1)}s)`}
                        >
                          {gesture.name.replace(/_/g, ' ')}
                          {getStatusIcon(gesture.name)}
                        </button>
                      ))}
                    </div>
                  </div>
                )
              })}

              {Object.keys(groupedGestures)
                .filter((cat) => !GESTURE_CATEGORY_ORDER.includes(cat))
                .map((category) => {
                  const categoryGestures = groupedGestures[category]
                  if (!categoryGestures || categoryGestures.length === 0) return null

                  return (
                    <div key={category} className="category-section gesture-category">
                      <h3>{category.toUpperCase()}</h3>
                      <div className="primitive-buttons">
                        {categoryGestures.map((gesture) => (
                          <button
                            key={gesture.name}
                            className={getButtonClass(gesture.name, true)}
                            onClick={() => {
                              setSelectedItem({ type: 'gesture', data: gesture })
                              executeGesture(gesture.name)
                            }}
                            disabled={isLoading || !isConnected}
                            title={gesture.description}
                          >
                            {gesture.name.replace(/_/g, ' ')}
                            {getStatusIcon(gesture.name)}
                          </button>
                        ))}
                      </div>
                    </div>
                  )
                })}
            </>
          )}
        </div>

        <div className="primitive-details">
          {selectedItem ? (
            <>
              <h3>
                SELECTED: {selectedItem.data.name}
                <span className="type-badge">{selectedItem.type}</span>
              </h3>
              <p className="description">{selectedItem.data.description}</p>

              {selectedItem.type === 'gesture' && (
                <div className="gesture-stats">
                  <span>Keyframes: {(selectedItem.data as Gesture).keyframe_count}</span>
                  <span>Duration: {(selectedItem.data as Gesture).total_duration.toFixed(1)}s</span>
                </div>
              )}

              {selectedItem.type === 'primitive' && (selectedItem.data as Primitive).speed !== 1.0 && (
                <p className="speed-info">Speed: {(selectedItem.data as Primitive).speed}x</p>
              )}

              {selectedItem.type === 'primitive' && (
                <div className="joints-display">
                  <h4>Joints:</h4>
                  <div className="joints-grid">
                    {Object.entries((selectedItem.data as Primitive).joints).map(([joint, value]) => (
                      <div key={joint} className="joint-entry">
                        <span className="joint-name">{joint}:</span>
                        <span className="joint-value">{typeof value === 'number' ? value.toFixed(2) : value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedItem.type === 'gesture' && (
                <div className="tags-display">
                  <h4>Tags:</h4>
                  <div className="tags-list">
                    {(selectedItem.data as Gesture).tags.map((tag) => (
                      <span key={tag} className="tag">{tag}</span>
                    ))}
                  </div>
                </div>
              )}

              <div className="mark-buttons">
                <button
                  className="mark-btn working"
                  onClick={() => markItem(selectedItem.data.name, true)}
                >
                  Mark as ✓ Working
                </button>
                <button
                  className="mark-btn broken"
                  onClick={() => markItem(selectedItem.data.name, false)}
                >
                  Mark as ✗ Broken
                </button>
              </div>
            </>
          ) : (
            <div className="no-selection">
              <p>Click a primitive or gesture to test it</p>
              <p className="hint">The robot will execute the motion and display details here</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default PrimitivesTest
