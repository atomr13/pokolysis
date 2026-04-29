import { useState } from 'react'
import TopBar from './components/TopBar'
import MatchFeed from './components/MatchFeed'
import AnalysisPane from './components/AnalysisPane'
import './App.css'

export default function App() {
  const [selectedMatch, setSelectedMatch] = useState(null)

  return (
    <div className="app-root">
      <TopBar />
      <div className="app-layout">
        <MatchFeed onSelectMatch={setSelectedMatch} selectedMatchId={selectedMatch?.match_id} />
        <AnalysisPane match={selectedMatch} onClose={() => setSelectedMatch(null)} />
      </div>
    </div>
  )
}
