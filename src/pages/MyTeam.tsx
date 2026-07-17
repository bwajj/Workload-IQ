import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import type { FplSquad, ScoredPlayer } from '../types';
import { Section, Loading, ErrorBanner, PlayerPhoto, tierClass } from '../ui';

const confClass = (s: number) => (s >= 60 ? 'low' : s >= 45 ? 'moderate' : 'high');
const ROWS = ['FWD', 'MID', 'DEF', 'GK'] as const;
const MIN = { GK: 1, DEF: 3, MID: 2, FWD: 1 } as const;
const MAX = { GK: 1, DEF: 5, MID: 5, FWD: 3 } as const;
type Mode = 'import' | 'build';

const best = (a: ScoredPlayer, b: ScoredPlayer) => (b.confidence ?? 0) - (a.confidence ?? 0);
const fmtPrice = (p?: number | null) => (p != null ? `£${p.toFixed(1)}m` : '');

export default function MyTeam() {
  const [mode, setMode] = useState<Mode>('import');
  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">My Team</h1>
          <p className="page-lede">
            Load your real Fantasy Premier League squad by Team ID, or build one from scratch —
            then see each player's injury risk, <strong>start confidence</strong> and price. Drag a
            bench player onto a starter (same position) to swap.
          </p>
        </div>
        <div className="seg">
          <button className={mode === 'import' ? 'on' : ''} onClick={() => setMode('import')}>Import FPL</button>
          <button className={mode === 'build' ? 'on' : ''} onClick={() => setMode('build')}>Build from scratch</button>
        </div>
      </div>
      {mode === 'import' ? <ImportMode /> : <BuildMode />}
    </div>
  );
}

/* ---------------- Import via FPL Team ID ---------------- */

function ImportMode() {
  const { user, saveFplTeam } = useAuth();
  const [teamId, setTeamId] = useState(user?.fplTeamId ?? '');
  const [squad, setSquad] = useState<FplSquad | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async (id = teamId) => {
    setError(''); setBusy(true); setSquad(null);
    try { setSquad(await api.fplSquad(id.trim())); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  // Auto-load a saved team on first visit.
  useEffect(() => { if (user?.fplTeamId) load(user.fplTeamId); /* eslint-disable-next-line */ }, []);

  const saved = user?.fplTeamId === teamId.trim() && !!teamId.trim();
  const toggleSave = () => saveFplTeam(saved ? '' : teamId.trim());

  return (
    <div>
      <div className="fixture" style={{ gap: 16, alignItems: 'center' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div className="micro">FPL Team ID</div>
          <div className="small muted">Find it in your FPL URL: fantasy.premierleague.com/entry/<strong>ID</strong>/…</div>
        </div>
        <input className="input" style={{ width: 160 }} placeholder="e.g. 1234567"
          value={teamId} onChange={(e) => setTeamId(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && teamId && load()} />
        <button className="btn btn-primary" style={{ width: 'auto', marginTop: 0 }}
          onClick={() => load()} disabled={busy || !teamId.trim()}>
          {busy ? 'Loading…' : 'Load squad'}
        </button>
        {teamId.trim() && (
          <button className="btn" style={{ marginTop: 0 }} onClick={toggleSave} title="Save to your account">
            {saved ? '★ Saved' : '☆ Save'}
          </button>
        )}
      </div>

      {error && <ErrorBanner message={error} />}

      {squad && (
        <>
          <p className="footnote" style={{ marginTop: 16 }}>
            <strong>{squad.teamName}</strong> · {squad.managerName} · GW{squad.gameweek} —
            {' '}{squad.matchedCount} of {squad.pickCount} picks have data.
            {squad.unmapped.length > 0 && <> No data for: {squad.unmapped.map((u) => u.webName).join(', ')}.</>}
          </p>
          <SquadView players={squad.players} theirCaptainId={squad.players.find((p) => p.isCaptain)?.playerId} />
        </>
      )}
    </div>
  );
}

/* ---------------- Build from scratch ---------------- */

function BuildMode() {
  const [all, setAll] = useState<ScoredPlayer[]>([]);
  const [ids, setIds] = useState<number[]>([]);
  const [q, setQ] = useState('');
  const [error, setError] = useState('');

  useEffect(() => { api.players('All').then(setAll).catch((e) => setError(e.message)); }, []);

  const byId = useMemo(() => new Map(all.map((p) => [p.playerId, p])), [all]);
  const selected = ids.map((id) => byId.get(id)).filter(Boolean) as ScoredPlayer[];
  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    return all.filter((p) => !ids.includes(p.playerId) &&
      (p.playerName.toLowerCase().includes(s) || p.team.toLowerCase().includes(s))).slice(0, 8);
  }, [q, all, ids]);

  const add = (id: number) => { if (ids.length < 15) { setIds([...ids, id]); setQ(''); } };

  if (error) return <ErrorBanner message={error} />;
  if (!all.length) return <Loading what="players" />;

  return (
    <div>
      <div className="fixture" style={{ gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 220 }}>
          <input className="input" style={{ width: '100%' }} placeholder="Search a player to add…"
            value={q} onChange={(e) => setQ(e.target.value)} disabled={ids.length >= 15} />
          {results.length > 0 && (
            <div className="search-pop">
              {results.map((p) => (
                <button key={p.playerId} className="search-opt" onClick={() => add(p.playerId)}>
                  <PlayerPhoto id={p.playerId} name={p.playerName} size={24} />
                  <span>{p.playerName}</span>
                  <span className="muted small">{p.position} · {p.team} · {fmtPrice(p.price)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="micro">{ids.length}/15 picked</div>
        {ids.length > 0 && <button className="linklike" onClick={() => setIds([])}>Clear</button>}
      </div>

      {selected.length === 0
        ? <p className="footnote" style={{ marginTop: 16 }}>Add players to build a test squad (11 form the XI, rest go to the bench).</p>
        : <SquadView key={ids.join(',')} players={selected} onRemove={(id) => setIds(ids.filter((x) => x !== id))} />}
    </div>
  );
}

/* ---------------- Auto formation for build mode ---------------- */

function autoForm(players: ScoredPlayer[]): { starters: number[]; bench: number[] } {
  if (players.length <= 11) return { starters: players.map((p) => p.playerId), bench: [] };
  const byPos: Record<string, ScoredPlayer[]> = { GK: [], DEF: [], MID: [], FWD: [] };
  players.forEach((p) => byPos[p.position]?.push(p));
  Object.values(byPos).forEach((g) => g.sort(best));

  const starters: ScoredPlayer[] = [];
  const count: Record<string, number> = { GK: 0, DEF: 0, MID: 0, FWD: 0 };
  const take = (pos: string) => { const p = byPos[pos][count[pos]]; if (p) { starters.push(p); count[pos]++; } };

  (['GK', 'DEF', 'MID', 'FWD'] as const).forEach((pos) => { for (let i = 0; i < MIN[pos]; i++) take(pos); });
  // fill to 11 with the best remaining, respecting position maxima
  const pool = players.filter((p) => !starters.includes(p)).sort(best);
  for (const p of pool) {
    if (starters.length >= 11) break;
    if (count[p.position] < MAX[p.position]) { starters.push(p); count[p.position]++; }
  }
  const startIds = new Set(starters.map((p) => p.playerId));
  return { starters: [...startIds], bench: players.filter((p) => !startIds.has(p.playerId)).map((p) => p.playerId) };
}

/* ---------------- Shared squad view (pitch + drag) ---------------- */

interface Grab { id: number; position: string; from: 'start' | 'bench'; }

function SquadView({ players, theirCaptainId, onRemove }: {
  players: ScoredPlayer[];
  theirCaptainId?: number;
  onRemove?: (id: number) => void;
}) {
  const nav = useNavigate();
  const byId = useMemo(() => new Map(players.map((p) => [p.playerId, p])), [players]);

  const [starterIds, setStarterIds] = useState<number[]>([]);
  const [benchIds, setBenchIds] = useState<number[]>([]);
  const [grab, setGrab] = useState<Grab | null>(null);

  useEffect(() => {
    const flagged = players.some((p) => 'onBench' in p);
    if (flagged) {
      setStarterIds(players.filter((p) => !(p as { onBench?: boolean }).onBench).map((p) => p.playerId));
      setBenchIds(players.filter((p) => (p as { onBench?: boolean }).onBench).map((p) => p.playerId));
    } else {
      const f = autoForm(players);
      setStarterIds(f.starters); setBenchIds(f.bench);
    }
    setGrab(null);
  }, [players]);

  const starters = starterIds.map((id) => byId.get(id)).filter(Boolean) as ScoredPlayer[];
  const bench = benchIds.map((id) => byId.get(id)).filter(Boolean) as ScoredPlayer[];
  const hasBench = bench.length > 0;

  // The pair a drop would swap: whichever of {grabbed, target} is the starter vs bench.
  const pairFor = (target: ScoredPlayer, side: 'start' | 'bench') => {
    if (!grab || grab.from === side) return null;
    const other = byId.get(grab.id);
    if (!other) return null;
    return side === 'start'
      ? { starter: target, sub: other }   // bench player dropped onto a starter
      : { starter: other, sub: target };  // starter dropped onto a bench player
  };

  // Legal FPL substitution: GK only swaps GK; outfield swaps must keep a valid
  // formation (≥3 DEF, ≥2 MID, ≥1 FWD; ≤5/5/3).
  const validSwap = (starter: ScoredPlayer, sub: ScoredPlayer) => {
    if (starter.position === 'GK' || sub.position === 'GK') return starter.position === sub.position;
    const c: Record<string, number> = { GK: 0, DEF: 0, MID: 0, FWD: 0 };
    starters.forEach((p) => { c[p.position]++; });
    c[starter.position]--; c[sub.position]++;
    return c.DEF >= 3 && c.DEF <= 5 && c.MID >= 2 && c.MID <= 5 && c.FWD >= 1 && c.FWD <= 3;
  };

  const isTarget = (p: ScoredPlayer, side: 'start' | 'bench') => {
    const pr = pairFor(p, side);
    return pr ? validSwap(pr.starter, pr.sub) : false;
  };

  const swap = (target: ScoredPlayer, side: 'start' | 'bench') => {
    const pr = pairFor(target, side);
    if (!pr || !validSwap(pr.starter, pr.sub)) { setGrab(null); return; }
    const S = pr.starter.playerId, B = pr.sub.playerId;
    setStarterIds((ids) => ids.map((id) => (id === S ? B : id)));
    setBenchIds((ids) => ids.map((id) => (id === B ? S : id)));
    setGrab(null);
  };

  const avg = (fn: (p: ScoredPlayer) => number | null | undefined) => {
    const xs = [...starters, ...bench].map(fn).filter((x): x is number => x != null);
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  };
  const avgRisk = Math.round(avg((p) => p.riskScore) ?? 0);
  const avgConf = Math.round(avg((p) => p.confidence) ?? 0);
  const totalPrice = [...starters, ...bench].reduce((s, p) => s + (p.price ?? 0), 0);
  const formationStr = `${starters.filter((p) => p.position === 'DEF').length}-${starters.filter((p) => p.position === 'MID').length}-${starters.filter((p) => p.position === 'FWD').length}`;

  const eligible = starters.filter((p) => p.available !== false);
  const modelCaptain = [...eligible].sort(best)[0];

  const token = (p: ScoredPlayer, side: 'start' | 'bench') => (
    <SquadToken key={p.playerId} p={p} nav={nav}
      isPick={modelCaptain?.playerId === p.playerId}
      grabbed={grab?.id === p.playerId}
      droppable={isTarget(p, side)}
      onGrab={() => setGrab(grab?.id === p.playerId ? null : { id: p.playerId, position: p.position, from: side })}
      onDrop={() => swap(p, side)}
      onEndGrab={() => setGrab(null)}
      onRemove={onRemove} />
  );

  return (
    <>
      <div className="kpis" style={{ marginTop: 20 }}>
        <div className="kpi"><div className={`kpi-value risk-${tierClass(avgRisk >= 40 ? 'High' : avgRisk >= 20 ? 'Moderate' : 'Low')}`}>{avgRisk}%</div><div className="kpi-label">Squad avg risk</div></div>
        <div className="kpi"><div className="kpi-value" style={{ color: `var(--${confClass(avgConf)})` }}>{avgConf}</div><div className="kpi-label">Avg start confidence</div></div>
        {totalPrice > 0 && <div className="kpi"><div className="kpi-value">£{totalPrice.toFixed(1)}m</div><div className="kpi-label">Squad value</div></div>}
        {modelCaptain && (
          <div className="kpi">
            <div className="kpi-value" style={{ fontSize: 20 }}>{modelCaptain.playerName}</div>
            <div className="kpi-label">Model captain{theirCaptainId != null && (theirCaptainId === modelCaptain.playerId ? ' ✓ matches yours' : ' — differs from yours')}</div>
          </div>
        )}
      </div>

      <Section label={hasBench ? 'Starting XI' : 'Squad'} aside={hasBench ? formationStr : undefined}>
        <div className="pitch" style={{ marginTop: 16 }}>
          {ROWS.map((pos) => {
            const row = starters.filter((p) => p.position === pos);
            if (!row.length) return null;
            return <div className="pitch-row" key={pos}>{row.map((p) => token(p, 'start'))}</div>;
          })}
        </div>
      </Section>

      {hasBench && (
        <Section label={`Bench · ${bench.length}`}>
          <div className="pitch bench-strip" style={{ marginTop: 12 }}>
            <div className="pitch-row">{bench.map((p) => token(p, 'bench'))}</div>
          </div>
        </Section>
      )}

      <TransferIdeas squad={[...starters, ...bench]} />
    </>
  );
}

function TransferIdeas({ squad }: { squad: ScoredPlayer[] }) {
  const nav = useNavigate();
  const flagged = squad.filter((p) => p.riskTier !== 'Low');
  const owned = squad.map((p) => p.playerId);
  const [ideas, setIdeas] = useState<Record<number, ScoredPlayer[]>>({});

  useEffect(() => {
    flagged.forEach((p) => {
      api.transfers(p.playerId, owned)
        .then((r) => setIdeas((m) => ({ ...m, [p.playerId]: r.suggestions })))
        .catch(() => {});
    });
  }, [squad.map((p) => p.playerId).join(',')]); // eslint-disable-line

  if (flagged.length === 0) {
    return (
      <Section label="Suggested transfers">
        <p className="footnote" style={{ marginTop: 14 }}>No elevated-risk players — squad looks healthy.</p>
      </Section>
    );
  }

  return (
    <Section label="Suggested transfers" aside={`${flagged.length} at risk`}>
      <p className="chart-caption" style={{ marginTop: 14 }}>
        For each higher-risk player, replacements at the same position within +£0.5m, ranked by
        start confidence.
      </p>
      <div className="transfer-list">
        {flagged.sort((a, b) => b.riskScore - a.riskScore).map((p) => (
          <div key={p.playerId} className="transfer-row">
            <div className="transfer-out">
              <div className="micro">Consider selling</div>
              <div className="player-flex">
                <PlayerPhoto id={p.playerId} name={p.playerName} size={30} />
                <div>
                  <strong className="link" onClick={() => nav(`/player/${p.playerId}`)}>{p.playerName}</strong>
                  <div className="why"><span className={`dot ${tierClass(p.riskTier)}`} />{p.riskScore}% · {p.position} · {p.price != null ? `£${p.price.toFixed(1)}m` : ''}</div>
                </div>
              </div>
            </div>
            <div className="transfer-arrow">→</div>
            <div className="transfer-in">
              {!ideas[p.playerId] ? <span className="muted small">finding options…</span>
                : ideas[p.playerId].length === 0 ? <span className="muted small">no cheaper, safer option</span>
                : ideas[p.playerId].map((s) => (
                  <button key={s.playerId} className="transfer-opt" onClick={() => nav(`/player/${s.playerId}`)}>
                    <PlayerPhoto id={s.playerId} name={s.playerName} size={26} />
                    <span className="transfer-optname">{s.playerName.split(' ').slice(-1)[0]}</span>
                    <span className="muted small">{s.riskScore}% risk · conf {s.confidence} · {s.price != null ? `£${s.price.toFixed(1)}m` : ''}</span>
                  </button>
                ))}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function SquadToken({ p, nav, isPick, grabbed, droppable, onGrab, onDrop, onEndGrab, onRemove }: {
  p: ScoredPlayer;
  nav: ReturnType<typeof useNavigate>;
  isPick: boolean;
  grabbed: boolean;
  droppable: boolean;
  onGrab: () => void;
  onDrop: () => void;
  onEndGrab: () => void;
  onRemove?: (id: number) => void;
}) {
  const t = tierClass(p.riskTier);
  const cap = (p as { isCaptain?: boolean }).isCaptain;
  return (
    <div
      className={['token', grabbed ? 'grabbed' : '', droppable ? 'drop-ok' : ''].filter(Boolean).join(' ')}
      title={`Risk ${p.riskScore}% · confidence ${p.confidence ?? '—'} · ${fmtPrice(p.price)}`}
      draggable
      onDragStart={(e) => { e.dataTransfer.setData('text/plain', String(p.playerId)); onGrab(); }}
      onDragEnd={onEndGrab}
      onDragOver={(e) => { if (droppable) e.preventDefault(); }}
      onDrop={(e) => { e.preventDefault(); onDrop(); }}
      onClick={() => (droppable ? onDrop() : onGrab())}
    >
      {(cap || isPick) && <div className={`token-badge ${isPick ? 'pick' : 'cap'}`}>{isPick ? '★' : 'C'}</div>}
      {p.available === false && <div className="token-warn" title="Injured">⚠</div>}
      <div className={`token-shirt ${t}`}><PlayerPhoto id={p.playerId} name={p.playerName} size={37} /></div>
      <div className="token-name link" onClick={(e) => { e.stopPropagation(); nav(`/player/${p.playerId}`); }}>
        {p.playerName.split(' ').slice(-1)[0]}
      </div>
      <div className="token-meta">
        <span className={`token-risk ${t}`}>{p.riskScore}%</span>
        <span className={`conf-inline ${confClass(p.confidence ?? 0)}`} style={{ fontSize: 12 }}>{p.confidence ?? '—'}</span>
      </div>
      {p.price != null && <div className="token-price">{fmtPrice(p.price)}</div>}
      {onRemove && <button className="linklike token-remove" onClick={(e) => { e.stopPropagation(); onRemove(p.playerId); }}>remove</button>}
    </div>
  );
}
