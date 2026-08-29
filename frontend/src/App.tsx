import { Routes, Route, Link, Navigate } from 'react-router-dom'
import RefinedDemo from './pages/RefinedDemo'
import Welcome from './pages/Welcome'
import Tutorial from './pages/Tutorial'
import PoseTester from './pages/PoseTester'
import SubjectSelect from './pages/SubjectSelect'
import TestFunctionality from './pages/TestFunctionality'
import ConnectionStatus from './components/ConnectionStatus'
import './App.css'

function App() {
  const mainView = (
    <div className="app launcher">
      <div className="launcher-card">
        <h1 className="launcher-logo">
          coral<span>.</span>
        </h1>
        <Link to="/welcome" className="start-demo-banner">
          ✨ Start Demo Here
        </Link>
        <div className="launcher-actions">
          <Link to="/welcome" className="launcher-btn primary">
            ✨ Refined Demo
          </Link>
          <Link to="/subject-select" className="launcher-btn">
            🔒 Subject Select
          </Link>
          <Link to="/pose-tester" className="launcher-btn">
            🦿 Pose Tester
          </Link>
        </div>
        <ConnectionStatus />
        <div className="launcher-footer">
          <Link to="/test" className="launcher-footer-link">
            Test functionality
          </Link>
        </div>
      </div>
    </div>
  )

  return (
    <Routes>
      <Route path="/" element={mainView} />
      <Route path="/welcome" element={<Welcome />} />
      <Route path="/home" element={<RefinedDemo />} />
      <Route path="/tutorial" element={<Tutorial />} />
      <Route path="/pose-tester" element={<PoseTester />} />
      <Route path="/subject-select" element={<SubjectSelect />} />
      <Route path="/test" element={<TestFunctionality />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
