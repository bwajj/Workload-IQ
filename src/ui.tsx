import { useEffect, useState, type ReactNode } from 'react';
import type { RiskTier } from './types';
import { useTheme } from './theme';

/** API-Football's public media CDN — keyed by the same player ids we store. */
export function playerPhotoUrl(playerId: number) {
  return `https://media.api-sports.io/football/players/${playerId}.png`;
}

/** Team name → API-Football id, fetched once and shared by every TeamLogo. */
let teamMapPromise: Promise<Map<string, number>> | null = null;
function getTeamMap(): Promise<Map<string, number>> {
  if (!teamMapPromise) {
    teamMapPromise = fetch('/api/teams/meta')
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: { id: number; name: string }[]) => new Map(rows.map((t) => [t.name, t.id])))
      .catch(() => new Map<string, number>());
  }
  return teamMapPromise;
}

/** Club crest, resolved by team name. Renders nothing when unknown (e.g. simulated data). */
export function TeamLogo({ team, size = 15 }: { team: string; size?: number }) {
  const [id, setId] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    getTeamMap().then((m) => { if (live) setId(m.get(team) ?? null); });
    return () => { live = false; };
  }, [team]);
  if (id == null || failed) return null;
  return (
    <img
      className="team-logo"
      src={`https://media.api-sports.io/football/teams/${id}.png`}
      alt={team}
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

/** Circular player headshot with an initials fallback (e.g. simulated data). */
export function PlayerPhoto({ id, name, size = 28 }: { id: number; name: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const initials = name.split(' ').filter(Boolean).slice(0, 2).map((w) => w[0]).join('');
  if (failed) {
    return (
      <span className="avatar avatar-fallback" style={{ width: size, height: size, fontSize: size * 0.36 }}>
        {initials}
      </span>
    );
  }
  return (
    <img
      className="avatar"
      src={playerPhotoUrl(id)}
      alt={name}
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

export function tierClass(tier: RiskTier): string {
  return tier.toLowerCase();
}

const TIER_COLOR: Record<RiskTier, string> = {
  Low: '#0e7a43',
  Moderate: '#b45309',
  High: '#d1242f',
};

export function tierColor(tier: RiskTier): string {
  return TIER_COLOR[tier];
}

export function TierPill({ tier }: { tier: RiskTier }) {
  return (
    <span className={`pill ${tierClass(tier)}`}>
      <span className={`dot ${tierClass(tier)}`} style={{ marginRight: 0 }} />
      {tier}
    </span>
  );
}

export function RiskCell({ score, tier }: { score: number; tier: RiskTier }) {
  return (
    <span className="risk-num">
      <span className={`dot ${tierClass(tier)}`} />
      {score}%
    </span>
  );
}

export function Section({ label, aside, children }: {
  label: string; aside?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="section">
      <div className="section-label">
        <h2>{label}</h2>
        {aside && <span className="aside">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

export function Kpi({ value, label, unit, tone }: {
  value: ReactNode; label: string; unit?: string; tone?: RiskTier;
}) {
  return (
    <div className="kpi">
      <div className={`kpi-value ${tone ? `risk-${tierClass(tone)}` : ''}`}>
        {value}
        {unit && <span className="unit"> {unit}</span>}
      </div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

export function Loading({ what = 'data' }: { what?: string }) {
  return <div className="loading">Loading {what}…</div>;
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error-banner">
      <strong>{message}</strong>
      <div style={{ marginTop: 4 }}>
        Is the backend running? Start everything with <code>npm run dev</code>.
      </div>
    </div>
  );
}

/** Theme-aware colors for Recharts (charts can't read CSS variables). */
export function useChartTheme() {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  return {
    tooltip: {
      background: dark ? '#1c1c1f' : '#ffffff',
      border: `1px solid ${dark ? '#3a3a3f' : '#d6d6d2'}`,
      borderRadius: 8,
      color: dark ? '#f2f2f0' : '#141417',
      fontSize: 12.5,
      boxShadow: dark ? '0 4px 16px rgba(0,0,0,0.4)' : '0 4px 16px rgba(20,20,23,0.08)',
    },
    axis: { fill: dark ? '#8f8f98' : '#a3a3ac', fontSize: 11.5 },
    axisStrong: { fill: dark ? '#c9c9cf' : '#34343a', fontSize: 11.5 },
    axisLine: dark ? '#3a3a3f' : '#d6d6d2',
    grid: dark ? '#26262a' : '#ececea',
    ink: dark ? '#f2f2f0' : '#141417',
    mutedText: dark ? '#8f8f98' : '#6f6f78',
    neutralBar: dark ? '#4b545f' : '#b9c2cc',
    euroBar: dark ? '#3f8a66' : '#5fa583',
    low: dark ? '#3fbf7f' : '#0e7a43',
    moderate: dark ? '#e8a04d' : '#b45309',
    amber: dark ? '#e0b34a' : '#d97706',
    high: dark ? '#f0565b' : '#d1242f',
    safeBandOpacity: dark ? 0.1 : 0.06,
  };
}

export function ThemeToggle({ className = '' }: { className?: string }) {
  const { theme, toggle } = useTheme();
  return (
    <button
      className={`icon-btn ${className}`}
      onClick={toggle}
      aria-label="Toggle dark mode"
      title={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
    >
      {theme === 'light' ? (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      ) : (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      )}
    </button>
  );
}
