import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ComposedChart, Bar, Cell, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine, ReferenceArea, Legend,
} from 'recharts';
import { api } from '../api';
import type { PlayerDetail as PD, SimMatch, Simulation } from '../types';
import { Section, Loading, ErrorBanner, TierPill, tierClass, useChartTheme, PlayerPhoto, TeamLogo } from '../ui';

function shortDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

function acwrClass(v: number) {
  return v >= 1.5 ? 'danger-text' : v >= 1.3 ? 'warn-text' : 'ok-text';
}

const seasonLabel = (y: number) => `${y}/${String((y + 1) % 100).padStart(2, '0')}`;

export default function PlayerDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState<PD | null>(null);
  const [error, setError] = useState('');
  const [season, setSeason] = useState<number | null>(null);
  const ct = useChartTheme();

  useEffect(() => {
    if (!id) return;
    setError('');
    setData(null);
    api.player(Number(id)).then(setData).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Loading what="player" />;

  const { player, risk, timeline, injuries } = data;

  // One season on the chart at a time — a 4-season timeline is unreadable.
  const seasons = [...new Set(timeline.map((t) => t.season).filter((s): s is number => s != null))].sort();
  const activeSeason = season ?? seasons[seasons.length - 1] ?? null;
  const seasonTimeline = activeSeason == null ? timeline : timeline.filter((t) => t.season === activeSeason);
  const chartData = seasonTimeline.map((t) => ({ ...t, label: shortDate(t.date) }));

  const injuryMarks = injuries.map((inj) => {
    const onset = new Date(inj.dateInjured).getTime();
    let best: string | undefined;
    for (const p of chartData) {
      if (new Date(p.date).getTime() <= onset) best = p.label;
    }
    // only mark injuries that fall inside the shown season's date range
    const first = chartData[0] && new Date(chartData[0].date).getTime();
    const last = chartData[chartData.length - 1] && new Date(chartData[chartData.length - 1].date).getTime();
    const inRange = first != null && last != null && onset >= first && onset <= last;
    return { label: best, type: inj.type, inRange };
  }).filter((m) => m.label && m.inRange);

  return (
    <div>
      <button className="btn" onClick={() => nav(-1)}>← Back</button>

      <div className="player-head" style={{ marginTop: 22 }}>
        <div className="player-flex" style={{ gap: 20 }}>
          <PlayerPhoto id={player._id} name={player.name} size={76} />
          <div>
            <h1 className="page-title">{player.name}</h1>
            <p className="page-lede">
              <TeamLogo team={player.team} size={16} />{player.team} · {player.position}
              {player.number ? <> · #{player.number}</> : null}
              {player.age != null ? <> · {player.age} yrs</> : null}
            </p>
          </div>
        </div>
        {risk && (
          <div className="risk-callout">
            <div className={`big ${tierClass(risk.riskTier)}`}>{risk.riskScore}%</div>
            <div style={{ marginTop: 6 }}><TierPill tier={risk.riskTier} /></div>
            <div className="small muted" style={{ marginTop: 4 }}>14-day injury risk</div>
          </div>
        )}
      </div>

      {risk && (
        <div className="statline">
          <Stat value={risk.acwr} label="ACWR" flag={risk.acwr >= 1.5} mild={risk.acwr >= 1.3} />
          <Stat value={`${risk.acute7}′`} label="Acute load · 7d" />
          <Stat value={`${risk.chronic28}′`} label="Chronic · weekly avg" />
          <Stat value={`${risk.restDays}d`} label="Rest since last match" flag={risk.restDays <= 3} />
          <Stat value={risk.matches14} label="Matches · 14d" mild={risk.matches14 >= 3} />
          <Stat
            value={risk.fatigue ?? '—'}
            label="Fatigue · 0–100"
            flag={(risk.fatigue ?? 0) >= 70}
            mild={(risk.fatigue ?? 0) >= 45}
          />
          <Stat value={risk.form != null ? risk.form.toFixed(1) : '—'} label="Form · avg rating" />
          <Stat
            value={risk.daysSinceReturn != null && risk.daysSinceReturn < 400 ? `${risk.daysSinceReturn}d` : '—'}
            label="Since injury return"
            flag={(risk.daysSinceReturn ?? 400) <= 21}
            mild={(risk.daysSinceReturn ?? 400) <= 45}
          />
          <Stat
            value={risk.priorInjuries ?? 0}
            label="Injuries · last year"
            mild={(risk.priorInjuries ?? 0) >= 2}
          />
        </div>
      )}

      <Section
        label="Workload timeline vs injury events"
        aside={seasons.length > 1 ? (
          <span className="seg">
            {seasons.map((s) => (
              <button key={s} className={activeSeason === s ? 'on' : ''} onClick={() => setSeason(s)}>
                {seasonLabel(s)}
              </button>
            ))}
          </span>
        ) : `${timeline.length} matches on record`}
      >
        <p className="chart-caption" style={{ marginTop: 16 }}>
          {seasons.length > 1 && <><strong>{seasonLabel(activeSeason!)}</strong> · {chartData.length} matches. </>}
          Bars are minutes per match — <strong>green bars are non-league games</strong> (domestic
          cups, Europe, internationals); the line is the acute:chronic workload ratio (right axis).
          The shaded band is the 0.8–1.3 safe zone; dashed markers are injury onsets.
        </p>
        <div style={{ height: 340 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 14, right: 6, bottom: 4, left: -14 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} vertical={false} />
              <XAxis dataKey="label" tick={ct.axis} interval="preserveStartEnd" axisLine={{ stroke: ct.axisLine }} tickLine={false} />
              <YAxis yAxisId="min" tick={ct.axis} domain={[0, 100]} axisLine={false} tickLine={false} />
              <YAxis yAxisId="acwr" orientation="right" tick={ct.axis} domain={[0, 2.5]} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={ct.tooltip}
                labelFormatter={(label, payload: any) => {
                  const d = payload?.[0]?.payload;
                  return d ? `${label} · ${d.home ? 'vs' : '@'} ${d.opponent} · ${d.competition}` : label;
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: ct.mutedText }} />
              <ReferenceArea yAxisId="acwr" y1={0.8} y2={1.3} fill={ct.low} fillOpacity={ct.safeBandOpacity} />
              <Bar yAxisId="min" dataKey="minutes" name="Minutes" fill={ct.neutralBar} radius={[3, 3, 0, 0]} maxBarSize={16}>
                {chartData.map((d, i) => (
                  <Cell key={i} fill={d.competition !== 'Premier League' ? ct.euroBar : ct.neutralBar} />
                ))}
              </Bar>
              <Line yAxisId="acwr" type="monotone" dataKey="acwr" name="ACWR" stroke={ct.ink} strokeWidth={2} dot={{ r: 2.5, fill: ct.ink }} />
              {injuryMarks.map((m, i) => (
                <ReferenceLine
                  key={i}
                  yAxisId="acwr"
                  x={m.label}
                  stroke={ct.high}
                  strokeDasharray="4 3"
                  label={{ value: 'injury', position: 'top', fontSize: 11, fill: ct.high }}
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Section>

      {risk && <WhatIfSimulator playerId={player._id} name={player.name.split(' ').slice(-1)[0]} />}

      <div className="cols-2-even">
        <Section label="Risk assessment">
          {risk ? (
            <ul className="reasons">
              {risk.reasons.map((r, i) => (
                <li key={i}>
                  <span className={`dot ${tierClass(risk.riskTier)}`} style={{ marginTop: 5 }} />
                  {r}
                </li>
              ))}
            </ul>
          ) : (
            <p className="footnote" style={{ marginTop: 14 }}>No current workload data for this player.</p>
          )}
        </Section>

        <Section label={`Injury history · ${injuries.length}`}>
          {injuries.length === 0 ? (
            <p className="footnote" style={{ marginTop: 14 }}>No injuries recorded this season.</p>
          ) : (
            <table className="table" style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Severity</th>
                  <th className="r">Date</th>
                  <th className="r">Out</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {injuries.map((inj) => (
                  <tr key={inj._id}>
                    <td className="player-cell">{inj.type}</td>
                    <td>{inj.severity}</td>
                    <td className="r">{shortDate(inj.dateInjured)}</td>
                    <td className="r">{inj.daysOut}d</td>
                    <td>
                      {inj.status === 'Active'
                        ? <span className="pill high">Active</span>
                        : <span className="pill neutral">Recovered</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      </div>
    </div>
  );
}

function Stat({ value, label, flag, mild }: {
  value: React.ReactNode; label: string; flag?: boolean; mild?: boolean;
}) {
  return (
    <div className="stat">
      <div className={`stat-value ${flag ? 'flag' : mild ? 'mild' : ''}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

const PRESETS: { label: string; matches: SimMatch[] }[] = [
  { label: 'One start (90′)', matches: [{ minutes: 90, daysFromNow: 3 }] },
  { label: 'Congested week (2× 90′)', matches: [{ minutes: 90, daysFromNow: 3 }, { minutes: 90, daysFromNow: 6 }] },
  { label: 'Three in a week', matches: [{ minutes: 90, daysFromNow: 3 }, { minutes: 60, daysFromNow: 6 }, { minutes: 30, daysFromNow: 9 }] },
];

function WhatIfSimulator({ playerId, name }: { playerId: number; name: string }) {
  const [matches, setMatches] = useState<SimMatch[]>([]);
  const [sim, setSim] = useState<Simulation | null>(null);
  const [busy, setBusy] = useState(false);
  const [mins, setMins] = useState(90);
  const [days, setDays] = useState(3);

  useEffect(() => {
    setBusy(true);
    api.simulate(playerId, matches)
      .then(setSim)
      .catch(() => {})
      .finally(() => setBusy(false));
  }, [playerId, matches]);

  const active = matches.length > 0;
  const b = sim?.baseline;
  const p = sim?.projected;

  return (
    <Section label="What-if · workload simulator" aside={busy ? 'computing…' : undefined}>
      <p className="chart-caption" style={{ marginTop: 16 }}>
        Add hypothetical upcoming matches and see the risk {name} would carry <em>into each
        one</em> — recomputed by the same model that scores every player. Congestion raises risk
        for a normally-loaded player; for someone returning from a spell out, regular minutes
        rebuild their base load and the spike eases — but they still have to survive the first
        match at peak risk.
      </p>

      <div className="sim-controls">
        <span className="micro">Quick scenarios</span>
        {PRESETS.map((preset) => (
          <button
            key={preset.label}
            className={`btn ${JSON.stringify(matches) === JSON.stringify(preset.matches) ? 'btn-on' : ''}`}
            onClick={() => setMatches(preset.matches)}
          >
            {preset.label}
          </button>
        ))}
        {active && <button className="linklike" onClick={() => setMatches([])}>Reset</button>}
      </div>

      <div className="sim-controls" style={{ marginTop: 10 }}>
        <span className="micro">Or build your own</span>
        <select className="input" value={mins} onChange={(e) => setMins(Number(e.target.value))}>
          {[90, 75, 60, 45, 30].map((m) => <option key={m} value={m}>{m}′</option>)}
        </select>
        <span className="muted small">in</span>
        <input
          className="input" type="number" min={1} max={14} value={days}
          onChange={(e) => setDays(Math.max(1, Math.min(14, Number(e.target.value) || 1)))}
          style={{ width: 64 }}
        />
        <span className="muted small">days</span>
        <button
          className="btn"
          onClick={() => setMatches((m) => [...m, { minutes: mins, daysFromNow: days }].slice(0, 5))}
        >
          + Add
        </button>
      </div>

      {active && (
        <div className="sim-matches">
          {matches.map((m, i) => (
            <span className="sim-chip" key={i}>
              {m.minutes}′ · in {m.daysFromNow}d
              <button onClick={() => setMatches((arr) => arr.filter((_, j) => j !== i))} aria-label="remove">×</button>
            </span>
          ))}
        </div>
      )}

      {active && sim && sim.path.length > 0 && (
        <ul className="rows sim-path">
          {sim.path.map((pt) => (
            <li key={pt.match}>
              <div className="who">
                <strong>Match {pt.match}</strong>{' '}
                <span className="muted small">{pt.minutes}′ · in {pt.daysFromNow} days</span>
                <div className="why">enters at ACWR {pt.acwr} · fatigue {pt.fatigue ?? '—'}</div>
              </div>
              <span className="risk-num">
                <span className={`dot ${tierClass(pt.riskTier)}`} />{pt.riskScore}%
              </span>
            </li>
          ))}
        </ul>
      )}

      {b && p && (
        <div className="sim-compare">
          <SimMetric
            label={active ? 'Peak risk in this scenario' : '14-day injury risk'}
            base={b.riskScore} proj={sim?.peakRisk ?? p.riskScore} suffix="%" active={active} worseUp
          />
          <SimMetric label="Risk after the run" base={b.riskScore} proj={p.riskScore} suffix="%" active={active} worseUp />
          <SimMetric label="ACWR · workload spike" base={b.acwr} proj={p.acwr} active={active} decimals={p.acwr < 10 ? 2 : 1} acwr />
          <SimMetric label="Fatigue" base={b.fatigue ?? 0} proj={p.fatigue ?? 0} suffix="/100" active={active} worseUp />
        </div>
      )}
      {!active && <p className="footnote" style={{ marginTop: 14 }}>Pick a scenario to project {name}’s risk forward.</p>}
    </Section>
  );
}

function SimMetric({ label, base, proj, suffix = '', active, worseUp, acwr, decimals = 0 }: {
  label: string; base: number; proj: number; suffix?: string;
  active: boolean; worseUp?: boolean; acwr?: boolean; decimals?: number;
}) {
  const delta = +(proj - base).toFixed(decimals);
  const tone = worseUp
    ? (delta > 0 ? 'danger-text' : delta < 0 ? 'ok-text' : 'muted')
    : 'muted';
  const projClass = acwr ? acwrClass(proj) : tone;
  return (
    <div className="sim-metric">
      <div className="micro">{label}</div>
      <div className="sim-values">
        <span className="sim-base num">{base}{suffix}</span>
        {active && (
          <>
            <span className="sim-arrow">→</span>
            <span className={`sim-proj num ${projClass}`}>{proj}{suffix}</span>
          </>
        )}
      </div>
      {active && delta !== 0 && (
        <span className={`small ${tone}`}>{delta > 0 ? `+${delta}` : delta}{suffix}</span>
      )}
    </div>
  );
}
