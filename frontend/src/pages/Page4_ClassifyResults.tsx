import { DummyFrame } from './DummyStream'
import type { PageProps } from './TestUIRouter'

export default function Page4_ClassifyResults({ state }: PageProps) {
  const result = state.classifyResult

  return (
    <div className="tui-page p4-layout">
      {/* Full-screen captured frame (real photo when available). */}
      {result?.imageB64 ? (
        <img
          src={`data:image/jpeg;base64,${result.imageB64}`}
          alt="Captured pose"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
        />
      ) : (
        <DummyFrame style={{ position: 'absolute', inset: 0 }} />
      )}

      {/* Caption overlay — no class probabilities; Coral just mirrors the pose. */}
      <div className="p4-result-bar">
        <div className="p4-class-name">
          {result ? '📸 Now I\'ll copy your pose!' : 'Reading your pose…'}
        </div>
      </div>
    </div>
  )
}
