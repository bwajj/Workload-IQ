import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ComposedChart, Bar, Cell, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { api } from '../api';
import type { ScoredPlayer, PlayerDetail } from '../types';
import { Section, Loading, ErrorBanner, PlayerPhoto, TeamLogo, tierClass, useChartTheme } from '../ui';

const seasonLabel = (y: number) => `${y}/${String((y + 1) % 100).padStart(2, '0')}`;
const shortDate = (iso: string) => new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });

const STATS: { key: keyof ScoredPlayer; label: string; fmt?: (v: number) => string; lowerBetter?: boolean }[] = [
  { key: 'riskScore', label: 'Injury risk', fmt: (v) => `${v}%`, lowerBetter: true },
  { key: 'confidence', label: 'Start confidence' },
  { key: 'form', label: 'Form', fmt: (v) => v.toFixed(1) },
  { key: 'acwr', label: 'ACWR', fmt: (v) => v.toFixed(2) },
  { key: 'fatigue', label: 'Fatigue', fmt: (v) => `${v}`, lowerBetter: true },
  { key: 'restDays', label: 'Rest (days)' },
  { key: 'matches14', label: 'Matches · 14d' },
  { key: 'priorInjuries', label: 'Injuries · 1yr', lowerBetter: true },
  { key: 'price', label: 'Price', fmt: (v) => `£${v.toFixed(1)}m` },
];

export default function Compare() {
  const [all, setAll] = useState<ScoredPlayer[]>([]);
  const [ids, setIds] = useState<number[]>([]);
  const [details, setDetails] = useState<Record<number, PlayerDetail>>({});
  const [q, setQ] = useState('');
  const [season, setSeason] = useState<number | null>(null);
  const [error, setError] = useState('');
  const nav = useNavigate();
  const ct = useChartTheme();

  useEffect(() => { api.players('All').then(setAll).catch((e) => setError(e.message)); }, []);

  useEffect(() => {
    ids.forEach((id) => {
      if (!details[id]) api.player(id).then((d) => setDetails((m) => ({ ...m, [id]: d }))).catch(() => {});
    });
  }, [ids]); // eslint-disable-line

  const byId = useMemo(() => new Map(all.map((p) => [p.playerId, p])), [all]);
  const selected = ids.map((id) => byId.get(id)).filter(Boolean) as ScoredPlayer[];
  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    return all.filter((p) => !ids.includes(p.playerId) &&
      (p.playerName.toLowerCase().includes(s) || p.team.toLowerCase().includes(s))).slice(0, 8);
  }, [q, all, ids]);

  const seasons = useMemo(() => {
    const set = new Set<number>();
    ids.forEach((id) => details[id]?.timeline.forEach((t) => t.season != null && set.add(t.season)));
    return [...set].sort();
  }, [details, ids]);
  const activeSeason = season ?? seasons[seasons.length - 1] ?? null;

  const add = (id: number) => { if (ids.length < 3) { setIds([...ids, id]); setQ(''); } };
  const remove = (id: number) => setIds(ids.filter((x) => x !== id));

  // best value per stat row (for highlighting)
  const bestFor = (stat: typeof STATS[number]) => {
    const vals = selected.map((p) => p[stat.key]).filter((v): v is number => typeof v === 'number');
    if (vals.length < 2) return null;
    return stat.lowerBetter ? Math.min(...vals) : Math.max(...vals);
  };

  if (error) return <ErrorBanner message={error} />;
  if (!all.length) return <Loading what="players" />;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Compare players</h1>
          <p className="page-lede">
            Put two or three players head to head — injury risk, workload, form, confidence
            and price side by side, with each one's season timeline.
          </p>
        </div>
        <div style={{ position: 'relative', minWidth: 240 }}>
          <input className="input" style={{ width: '100%' }} placeholder="Add a player…"
            value={q} onChange={(e) => setQ(e.target.value)} disabled={ids.length >= 3} />
          {results.length > 0 && (
            <div className="search-pop">
              {results.map((p) => (
                <button key={p.playerId} className="search-opt" onClick={() => add(p.playerId)}>
                  <PlayerPhoto id={p.playerId} name={p.playerName} size={24} />
                  <span>{p.playerName}</span>
                  <span className="muted small">{p.position} · {p.team}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {selected.length === 0 ? (
        <p className="footnote" style={{ marginTop: 16 }}>Add up to three players to compare.</p>
      ) : (
        <>
          <div className="compare-grid" style={{ gridTemplateColumns: `160px repeat(${selected.length}, 1fr)` }}>
            {/* header row */}
            <div className="compare-corner" />
            {selected.map((p) => (
              <div key={p.playerId} className="compare-head">
                <button className="linklike compare-x" onClick={() => remove(p.playerId)}>✕</button>
                <PlayerPhoto id={p.playerId} name={p.playerName} size={48} />
                <div className="compare-name link" onClick={() => nav(`/player/${p.playerId}`)}>{p.playerName}</div>
                <div className="sub"><TeamLogo team={p.team} size={13} />{p.team} · {p.position}</div>
                <div className={`big ${tierClass(p.riskTier)}`} style={{ fontSize: 30 }}>{p.riskScore}%</div>
              </div>
            ))}
            {/* stat rows */}
            {STATS.map((stat) => {
              const best = bestFor(stat);
              return (
                <div key={String(stat.key)} className="compare-row">
                  <div className="compare-label">{stat.label}</div>
                  {selected.map((p) => {
                    const v = p[stat.key];
                    const num = typeof v === 'number' ? v : null;
                    const isBest = best != null && num === best;
                    return (
                      <div key={p.playerId} className={`compare-val ${isBest ? 'compare-best' : ''}`}>
                        {num == null ? '—' : stat.fmt ? stat.fmt(num) : num}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>

          <Section
            label="Workload timeline"
            aside={seasons.length > 1 ? (
              <span className="seg">
                {seasons.map((s) => (
                  <button key={s} className={activeSeason === s ? 'on' : ''} onClick={() => setSeason(s)}>{seasonLabel(s)}</button>
                ))}
              </span>
            ) : undefined}
          >
            <div className="compare-charts">
              {selected.map((p) => {
                const tl = (details[p.playerId]?.timeline ?? [])
                  .filter((t) => activeSeason == null || t.season === activeSeason)
                  .map((t) => ({ ...t, label: shortDate(t.date) }));
                return (
                  <div key={p.playerId} className="compare-chart">
                    <div className="micro" style={{ marginBottom: 6 }}>{p.playerName.split(' ').slice(-1)[0]}</div>
                    {!details[p.playerId] ? <Loading what="" /> : (
                      <div style={{ height: 180 }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <ComposedChart data={tl} margin={{ top: 6, right: 4, bottom: 0, left: -22 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} vertical={false} />
                            <XAxis dataKey="label" tick={ct.axis} interval="preserveStartEnd" axisLine={{ stroke: ct.axisLine }} tickLine={false} />
                            <YAxis yAxisId="m" tick={ct.axis} domain={[0, 100]} axisLine={false} tickLine={false} />
                            <YAxis yAxisId="a" orientation="right" tick={ct.axis} domain={[0, 2.5]} hide />
                            <Tooltip contentStyle={ct.tooltip} />
                            <Bar yAxisId="m" dataKey="minutes" name="Min" radius={[2, 2, 0, 0]} maxBarSize={10}>
                              {tl.map((d, i) => <Cell key={i} fill={d.competition !== 'Premier League' ? ct.euroBar : ct.neutralBar} />)}
                            </Bar>
                            <Line yAxisId="a" type="monotone" dataKey="acwr" name="ACWR" stroke={ct.ink} strokeWidth={1.6} dot={false} />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
