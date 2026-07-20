import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import type { PublicStats } from '../types';
import { ThemeToggle, tierClass, PlayerPhoto, TeamLogo } from '../ui';

/** Ease-out count-up for the live stats strip. */
function useCountUp(target: number, duration = 1100) {
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (!target) {
      setVal(target);
      return;
    }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setVal(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      setVal(Math.round(target * (1 - (1 - p) ** 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return val;
}

function Stat({ value, label }: { value: number; label: string }) {
  const v = useCountUp(value);
  return (
    <div className="kpi">
      <div className="kpi-value">{v.toLocaleString()}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

export default function Landing() {
  const nav = useNavigate();
  const { guest } = useAuth();
  const [stats, setStats] = useState<PublicStats | null>(null);
  const [enteringDemo, setEnteringDemo] = useState(false);

  useEffect(() => {
    api.publicStats().then(setStats).catch(() => {});
  }, []);

  const enterDemo = async () => {
    setEnteringDemo(true);
    try {
      await guest();  // signs in as the demo account and drops straight into the app
    } catch {
      nav('/login');  // fall back to the form if the demo login is unavailable
    } finally {
      setEnteringDemo(false);
    }
  };

  return (
    <>
      <header className="masthead">
        <div className="masthead-inner">
          <span className="wordmark">
            <span className="wordmark-dot" />
            Workload IQ
          </span>
          <div className="masthead-right">
            <ThemeToggle />
            <button className="btn" onClick={() => nav('/login')}>Sign in</button>
          </div>
        </div>
      </header>

      <main className="landing">
        <section className="landing-hero">
          <div className="micro">Premier League · injury-risk analytics</div>
          <h1>See the injury coming before the team sheet does.</h1>
          <p className="lede">
            Workload IQ turns real Premier League match data — minutes, congestion,
            European trips, rest into a injury risk for every player, then helps
            you pick a lineup that balances risk against form and fixture difficulty.
          </p>
          <div className="cta-row">
            <button className="btn btn-primary btn-hero" onClick={enterDemo} disabled={enteringDemo}>
              {enteringDemo ? 'Entering…' : 'Enter as guest →'}
            </button>
            <button className="btn btn-hero" onClick={() => nav('/login')}>
              Sign in
            </button>
          </div>
        </section>

        <div className="hero-chart" aria-hidden="true">
          <svg viewBox="0 0 720 150" width="100%" height="150" preserveAspectRatio="none">
            {/* 0.8–1.3 safe zone */}
            <rect x="0" y="58" width="720" height="34" className="hc-band" />
            {/* injury marker where the spike peaks */}
            <line x1="512" y1="8" x2="512" y2="142" className="hc-injury" />
            <text x="520" y="18" className="hc-injury-label">injury</text>
            {/* ACWR line: steady → spike → break down */}
            <path
              className="hc-line"
              pathLength={1}
              d="M0,84 C40,80 70,74 105,76 S170,88 205,84 S268,70 300,72 S356,60 385,50
                 S448,22 480,18 S508,16 512,22 C520,40 540,96 570,104 S650,96 720,88"
            />
            <circle cx="720" cy="88" r="4" className="hc-dot" />
          </svg>
          <p className="footnote" style={{ marginTop: 6 }}>
            A player’s acute:chronic workload ratio. The shaded band is the safe zone —
            spikes above it are where injuries cluster.
          </p>
        </div>

        {stats && stats.players > 0 && (
          <>
            <section className="section">
              <div className="section-label">
                <h2><span className="live-dot" />Live from the dataset</h2>
                <span className="aside">
                  {stats.season ? `season ${stats.season}–${(stats.season + 1) % 100}` : ''} · real
                  data via API-Football
                </span>
              </div>
              <div className="kpis" style={{ borderTop: 'none', marginTop: 0 }}>
                <Stat value={stats.players} label="Players monitored" />
                <Stat value={stats.teams} label="Clubs" />
                <Stat value={stats.games} label="Match performances" />
                <Stat value={stats.injuries} label="Injury episodes tracked" />
                <Stat value={stats.europeanClubs} label="Clubs also playing in Europe" />
              </div>
            </section>

            {stats.topRisk.length > 0 && (
              <section className="section">
                <div className="section-label">
                  <h2>On the board right now</h2>
                  <span className="aside">{stats.riskTiers.High ?? 0} players currently flagged high-risk</span>
                </div>
                <div className="table-scroll" style={{ marginTop: 8 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Player</th>
                      <th className="r">Workload spike (ACWR)</th>
                      <th className="r">14-day risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.topRisk.map((p) => (
                      <tr key={p.playerName}>
                        <td>
                          <div className="player-flex">
                            <PlayerPhoto id={p.playerId} name={p.playerName} size={32} />
                            <div>
                              <div className="player-cell">{p.playerName}</div>
                              <div className="sub"><TeamLogo team={p.team} size={13} />{p.team}</div>
                            </div>
                          </div>
                        </td>
                        <td className="r danger-text">{p.acwr}</td>
                        <td className="r">
                          <span className="risk-num">
                            <span className={`dot ${tierClass(p.riskTier)}`} />{p.riskScore}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
                <p className="footnote" style={{ marginTop: 12 }}>
                  <button className="linklike" onClick={() => nav('/login')}>
                    Sign in to see all {stats.players} players →
                  </button>
                </p>
              </section>
            )}
          </>
        )}

        <section className="section">
          <div className="section-label"><h2>What’s inside</h2></div>
          <div className="landing-grid">
            <div className="feature">
              <div className="micro">Today</div>
              <h3>Every player, ranked</h3>
              <p>
                A league-wide risk board: workload spike, rest, fatigue and form for all
                monitored players ; all searchable and filterable
              </p>
            </div>
            <div className="feature">
              <div className="micro">Selection</div>
              <h3>A lineup sandbox</h3>
              <p>
                Start from the lowest-risk XI, then drag players in and out and watch risk
                and form respond. Fixture difficulty and gameweek rotation included.
              </p>
            </div>
            <div className="feature">
              <div className="micro">Evidence</div>
              <h3>The receipts</h3>
              <p>
                Predictions are backtested against the injuries that actually happened —
                and the misses are shown as plainly as the hits.
              </p>
            </div>
          </div>
        </section>

        <footer className="landing-foot">
          <span className="muted small">
            React · Flask · MongoDB · scikit-learn — real data via API-Football
          </span>
          <button className="linklike" onClick={() => nav('/login')}>Sign in</button>
        </footer>
      </main>
    </>
  );
}
