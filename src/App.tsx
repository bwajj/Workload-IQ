import { useEffect, useState } from 'react';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { api } from './api';
import Today from './pages/Today';
import Selection from './pages/Selection';
import Picks from './pages/Picks';
import MyTeam from './pages/MyTeam';
import Fixtures from './pages/Fixtures';
import Compare from './pages/Compare';
import Evidence from './pages/Evidence';
import PlayerDetail from './pages/PlayerDetail';
import Login from './pages/Login';
import Landing from './pages/Landing';
import { useAuth } from './auth';
import { ThemeToggle } from './ui';

const tab = ({ isActive }: { isActive: boolean }) => (isActive ? 'tab active' : 'tab');

function relativeTime(iso: string): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function App() {
  const { user, ready, logout } = useAuth();
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  useEffect(() => {
    if (user) api.health().then((h) => setLastRefresh(h.lastRefresh ?? null)).catch(() => {});
  }, [user]);

  if (!ready) return null;
  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Landing />} />
      </Routes>
    );
  }

  return (
    <>
      <header className="masthead">
        <div className="masthead-inner">
          <NavLink to="/" className="wordmark">
            <span className="wordmark-dot" />
            Workload IQ
          </NavLink>
          <nav>
            <NavLink to="/" end className={tab}>Today</NavLink>
            <NavLink to="/selection" className={tab}>Selection</NavLink>
            <NavLink to="/picks" className={tab}>Picks</NavLink>
            <NavLink to="/fixtures" className={tab}>Fixtures</NavLink>
            <NavLink to="/compare" className={tab}>Compare</NavLink>
            <NavLink to="/my-team" className={tab}>My Team</NavLink>
            <NavLink to="/evidence" className={tab}>Evidence</NavLink>
          </nav>
          <div className="masthead-right">
            <div className="masthead-meta">
              <div className="micro">Premier League 2025–26</div>
              <div className="small muted">
                {lastRefresh ? `Updated ${relativeTime(lastRefresh)}` : 'via API-Football'}
              </div>
            </div>
            <ThemeToggle />
            <div className="user-chip" title={user.email}>
              <span className="user-name">{user.name || user.email}</span>
              <button className="linklike" onClick={logout}>Sign out</button>
            </div>
          </div>
        </div>
      </header>

      <main className="page">
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/selection" element={<Selection />} />
          <Route path="/picks" element={<Picks />} />
          <Route path="/fixtures" element={<Fixtures />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/my-team" element={<MyTeam />} />
          <Route path="/evidence" element={<Evidence />} />
          <Route path="/player/:id" element={<PlayerDetail />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
          {/* Legacy paths from the previous layout */}
          <Route path="/risk" element={<Navigate to="/" replace />} />
          <Route path="/rotation" element={<Navigate to="/selection" replace />} />
          <Route path="/correlations" element={<Navigate to="/evidence" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}
