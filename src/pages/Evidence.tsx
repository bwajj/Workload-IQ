import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid, LabelList, ReferenceLine,
} from 'recharts';
import { api } from '../api';
import type { Correlation, Backtest, BacktestSummary, Gameweek } from '../types';
import { Section, Loading, ErrorBanner, Kpi, TierPill, useChartTheme, tierClass, PlayerPhoto, TeamLogo } from '../ui';

const BAND_LABELS: Record<string, string> = {
  '0': '< 0.8', '0.8': '0.8–1.0', '1': '1.0–1.3',
  '1.3': '1.3–1.5', '1.5': '1.5–2.0', '2': '2.0+',
};

// Plain-English names for the model's internal feature keys.
const FEATURE_LABELS: Record<string, string> = {
  acwr: 'Workload spike (ACWR)',
  acute7: 'Recent minutes (7 days)',
  chronic28: 'Baseline load',
  restDays: 'Days of rest',
  backToBack14: 'Back-to-back games',
  matches14: 'Matches in 14 days',
  age: 'Age',
  recentReturn: 'Just back from injury',
  priorInjuries: 'Injury history (1yr)',
  daysSinceReturn: 'Days since return',
};

function shortDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

export default function Evidence() {
  const [data, setData] = useState<Correlation | null>(null);
  const [btGws, setBtGws] = useState<Gameweek[]>([]);
  const [btGw, setBtGw] = useState<number | null>(null);
  const [bt, setBt] = useState<Backtest | null>(null);
  const [summary, setSummary] = useState<BacktestSummary | null>(null);
  const [error, setError] = useState('');
  const ct = useChartTheme();
  const nav = useNavigate();

  const bandColor = (id: string): string => {
    if (id === '1' || id === '0.8') return ct.low;      // sweet spot
    if (id === '1.3') return ct.moderate;
    if (id === '0') return ct.amber;                     // undertraining
    return ct.high;                                      // spike zone
  };

  useEffect(() => {
    api.correlation().then(setData).catch((e) => setError(e.message));
    api.gameweeks().then((g) => {
      const testable = g.filter((x) => x.backtestable);
      setBtGws(testable);
      if (testable.length) setBtGw(testable[testable.length - 1].round);
    }).catch(() => {});
    api.backtestSummary().then(setSummary).catch(() => {});
  }, []);

  useEffect(() => {
    if (btGw == null) return;
    api.backtest(btGw).then(setBt).catch(() => {});
  }, [btGw]);

  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Loading what="evidence" />;

  const buckets = data.acwrBuckets
    .filter((b) => b._id !== 'other')
    .map((b) => ({
      band: BAND_LABELS[String(b._id)] ?? String(b._id),
      id: String(b._id),
      rate: +(b.injuryRate * 100).toFixed(1),
      samples: b.samples,
    }));

  const coeffs = data.coefficients.map((c) => ({
    label: FEATURE_LABELS[c.feature] ?? c.feature,
    weight: c.weight,
  }));

  const bodyParts = data.bodyParts.map((b) => ({
    name: b._id,
    count: b.count,
    avgDaysOut: Math.round(b.avgDaysOut),
    avgAcwr: +b.avgAcwrAtOnset.toFixed(2),
  }));

  const steady = buckets.find((b) => b.id === '0.8')?.rate;
  const spike = buckets.find((b) => b.id === '2')?.rate;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">The evidence</h1>
          <p className="page-lede">
            Why the risk scores look the way they do and how workload relates to injuries in
            the data, and which factors move a player’s score the most.
          </p>
        </div>
      </div>

      {bt && (
        <Section
          label="Did the scores work? — predictions vs reality"
          aside={btGws.length > 1 && (
            <select className="input" value={btGw ?? ''} onChange={(e) => setBtGw(Number(e.target.value))}>
              {[...btGws].sort((a, b) => a.round - b.round).map((g) => (
                <option key={g.round} value={g.round}>Gameweek {g.round}</option>
              ))}
            </select>
          )}
        >
          <p className="chart-caption" style={{ marginTop: 16 }}>
            Every fit player was scored on <strong>{shortDate(bt.asOf)}</strong>, the eve of
            gameweek {bt.gameweek}, using only information available then and we watched the
            next {bt.windowDays} days. Predictions on the left, reality on the right.
          </p>

          <div className="kpis" style={{ marginTop: 6 }}>
            <Kpi value={bt.summary.totalInjured} label={`New injuries in ${bt.windowDays} days`} />
            <Kpi
              value={`${bt.summary.flagged} of ${bt.summary.totalInjured}`}
              label="Flagged Moderate/High beforehand"
            />
            <Kpi
              value={`${((bt.tierStats.find((t) => t.tier === 'High')?.rate ?? 0) * 100).toFixed(1)}%`}
              label="High-tier injury rate"
              tone="High"
            />
            <Kpi
              value={`${((bt.tierStats.find((t) => t.tier === 'Low')?.rate ?? 0) * 100).toFixed(1)}%`}
              label="Low-tier injury rate"
              tone="Low"
            />
          </div>

          <div className="cols-2" style={{ marginTop: 8 }}>
            <div>
              <table className="table" style={{ marginTop: 16 }}>
                <thead>
                  <tr>
                    <th>What we said</th>
                    <th className="r">Players</th>
                    <th className="r">Got injured</th>
                    <th className="r">Injury rate</th>
                  </tr>
                </thead>
                <tbody>
                  {bt.tierStats.map((t) => (
                    <tr key={t.tier}>
                      <td><TierPill tier={t.tier} /></td>
                      <td className="r">{t.players}</td>
                      <td className="r">{t.injured}</td>
                      <td className="r risk-num">{(t.rate * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="footnote" style={{ marginTop: 14 }}>
                {bt.summary.lift != null && bt.summary.lift >= 1.5 ? (
                  <>High-tier players were injured at <strong>{bt.summary.lift}×</strong> the rate
                  of Low-tier players this gameweek — the flags carried real signal.</>
                ) : bt.summary.lift != null && bt.summary.lift < 1 ? (
                  <>This gameweek the flags <strong>didn’t work</strong> — High-tier players were
                  actually injured less often than Low-tier ones ({bt.summary.lift}×). Injury is
                  noisy and samples are small; we show the misses as plainly as the hits.</>
                ) : (
                  <>High- and Low-tier injury rates were similar this gameweek
                  {bt.summary.lift != null && <> ({bt.summary.lift}×)</>} — no clear separation
                  on this sample.</>
                )}
                {bt.truncated && (
                  <> Note: the {bt.windowDays}-day window runs past the season’s end, so late
                  injuries may be under-reported.</>
                )}
              </p>
            </div>

            <div>
              <table className="table" style={{ marginTop: 16 }}>
                <thead>
                  <tr>
                    <th>Actually injured</th>
                    <th>We said</th>
                    <th>What happened</th>
                    <th className="r">Out</th>
                  </tr>
                </thead>
                <tbody>
                  {bt.injured.map((x) => (
                    <tr key={x.playerId} className="clickable" onClick={() => nav(`/player/${x.playerId}`)}>
                      <td>
                        <div className="player-flex">
                          <PlayerPhoto id={x.playerId} name={x.playerName} size={28} />
                          <div>
                            <div className="player-cell">{x.playerName}</div>
                            <div className="sub"><TeamLogo team={x.team} size={13} />{x.team}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className="risk-num">
                          <span className={`dot ${tierClass(x.riskTier)}`} />{x.riskScore}%
                        </span>
                      </td>
                      <td>{x.injuryType}</td>
                      <td className="r">{x.daysOut}d</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </Section>
      )}

      {summary && summary.calibration.length > 0 && (
        <Section
          label="Are the scores calibrated? — the report card"
          aside={`${summary.gameweeks.map((g) => `GW${g}`).join(' + ')} pooled · ${summary.observations} predictions`}
        >
          <p className="chart-caption" style={{ marginTop: 16 }}>
            Pooling every prediction across the backtested gameweeks and grading them like a
            classifier. A well-calibrated score means players we rated “20% risk” actually got
            injured about 20% of the time — so each bar pair below should be roughly level.
          </p>

          <div className="kpis" style={{ marginTop: 6 }}>
            <Kpi value={summary.auc ?? '—'} label="Out-of-sample AUC (0.5 = coin flip)" />
            <Kpi
              value={summary.recall != null ? `${Math.round(summary.recall * 100)}%` : '—'}
              label="Injuries we flagged (recall)"
            />
            <Kpi
              value={summary.lift != null ? `${summary.lift}×` : '—'}
              label="High-tier vs Low-tier rate (lift)"
            />
            <Kpi value={summary.injuries} label={`Injuries across ${summary.observations} predictions`} />
          </div>

          <div className="cols-2" style={{ marginTop: 8 }}>
            <div>
              <p className="micro" style={{ margin: '18px 0 4px' }}>Predicted risk vs. what actually happened</p>
              <div style={{ height: 260 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={summary.calibration} margin={{ top: 24, right: 8, bottom: 4, left: -18 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} vertical={false} />
                    <XAxis dataKey="label" tick={ct.axis} axisLine={{ stroke: ct.axisLine }} tickLine={false} />
                    <YAxis tick={ct.axis} unit="%" axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={ct.tooltip}
                      formatter={(v: number, n: string) => [`${v}%`, n]}
                      labelFormatter={(l, p: any) => `Predicted ${l} · ${p?.[0]?.payload?.n ?? 0} players`}
                    />
                    <Bar dataKey="predicted" name="Predicted risk" fill={ct.neutralBar} radius={[3, 3, 0, 0]} maxBarSize={34} />
                    <Bar dataKey="actual" name="Actual injury rate" fill={ct.high} radius={[3, 3, 0, 0]} maxBarSize={34} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="footnote">
                Grey = what we predicted, red = what actually happened.
              </p>
            </div>

            <div>
              <table className="table" style={{ marginTop: 34 }}>
                <thead>
                  <tr>
                    <th>Predicted band</th>
                    <th className="r">Players</th>
                    <th className="r">Predicted</th>
                    <th className="r">Actual</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.calibration.map((c) => (
                    <tr key={c.label}>
                      <td className="player-cell">{c.label}</td>
                      <td className="r">{c.n}</td>
                      <td className="r">{c.predicted}%</td>
                      <td className={`r ${c.actual < c.predicted - 3 ? 'warn-text' : ''}`}>{c.actual}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="footnote" style={{ marginTop: 14 }}>
                {summary.auc != null && summary.auc <= 0.55 ? (
                  <>An out-of-sample AUC of <strong>{summary.auc}</strong> means the scores rank injured
                  vs. healthy players only slightly better than chance, and the bands above are
                  <strong> over-confident</strong> — predicted rates sit well above actual ones. This is
                  the honest limit of ~6 gameweeks of data; a full season is what the model needs to
                  sharpen. The interpretable ACWR rules are shipped precisely because of this.</>
                ) : (
                  <>Out-of-sample AUC <strong>{summary.auc}</strong>; the scores separate injured from
                  healthy players and the predicted bands broadly track reality.</>
                )}
              </p>
            </div>
          </div>
        </Section>
      )}

      <Section label="Do workload spikes really lead to injuries?">
        <div className="explainer">
          <span><span className="term">Workload spike (ACWR)</span> compares a player’s minutes in the
            last 7 days to their recent 28-day average.</span>
          <span><span className="term">≈ 1.0</span> steady</span>
          <span><span className="term">above 1.3</span> ramping up fast</span>
          <span><span className="term">below 0.8</span> eased right off</span>
        </div>
        <p className="chart-caption" style={{ marginTop: 16 }}>
          For every match a player featured in, we checked whether they got injured within the
          next 14 days — then grouped those matches by how spiked the player’s workload was.
        </p>
        <div style={{ height: 300 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={buckets} margin={{ top: 26, right: 8, bottom: 4, left: -18 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} vertical={false} />
              <XAxis dataKey="band" tick={ct.axis} axisLine={{ stroke: ct.axisLine }} tickLine={false} />
              <YAxis tick={ct.axis} unit="%" axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={ct.tooltip}
                formatter={(v: number, _n, item: any) => [`${v}% injured within 14 days (${item.payload.samples} matches)`, 'Injury rate']}
                labelFormatter={(l) => `Workload spike ${l}`}
              />
              <Bar dataKey="rate" radius={[4, 4, 0, 0]} maxBarSize={72}>
                <LabelList dataKey="rate" position="top" fill={ct.ink} fontSize={12} fontWeight={600} formatter={(v: number) => `${v}%`} />
                {buckets.map((b) => <Cell key={b.id} fill={bandColor(b.id)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        {steady != null && spike != null && (
          <p className="takeaway">
            <strong>The takeaway:</strong> injury rates are lowest when a player’s load holds
            steady (~{steady}%) and climb at both extremes — a big spike above their norm
            (~{spike}%) or a sharp drop below it. Steady beats spiky.
          </p>
        )}
      </Section>

      <div className="cols-2-even">
        <Section label="What raises and lowers risk">
          <p className="chart-caption" style={{ marginTop: 16 }}>
            How much each factor pushes a player’s risk score up or down. Longer bar = bigger effect.
          </p>
          <div className="dir-legend">
            <span className="lo">← lowers risk</span>
            <span className="hi">raises risk →</span>
          </div>
          <div style={{ height: 270 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart layout="vertical" data={coeffs} margin={{ left: 12, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} horizontal={false} />
                <XAxis type="number" tick={ct.axis} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="label" width={134} tick={ct.axisStrong} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={ct.tooltip}
                  formatter={(v: number) => [`${v >= 0 ? '+' : ''}${v} · ${v >= 0 ? 'raises' : 'lowers'} risk`, 'Effect']}
                />
                <ReferenceLine x={0} stroke={ct.axisLine} />
                <Bar dataKey="weight" radius={[2, 2, 2, 2]} maxBarSize={16}>
                  {coeffs.map((c) => <Cell key={c.label} fill={c.weight >= 0 ? ct.high : ct.low} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          {data.modelAuc != null ? (
            <p className="footnote">Model accuracy (cross-validated AUC): <strong>{data.modelAuc}</strong>.</p>
          ) : (
            <div className="note">
              On this slice of the season the learned model didn’t beat a simple baseline, so risk
              scores fall back to the trusted ACWR rules above. A full season of data would give it
              more to learn from.
            </div>
          )}
        </Section>

        <Section label="Where injuries land, and for how long">
          <p className="chart-caption" style={{ marginTop: 16 }}>
            The body parts hit most this season, and how long players were typically sidelined.
          </p>
          <table className="table" style={{ marginTop: 4 }}>
            <thead>
              <tr>
                <th>Body part</th>
                <th className="r">Injuries</th>
                <th className="r">Avg time out</th>
              </tr>
            </thead>
            <tbody>
              {bodyParts.map((b) => (
                <tr key={b.name}>
                  <td className="player-cell">{b.name}</td>
                  <td className="r">{b.count}</td>
                  <td className="r">{b.avgDaysOut} days</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>

      <Section label="How the numbers are built">
        <p className="footnote" style={{ marginTop: 14, maxWidth: 760 }}>
          For each match a player featured in, we measure their <strong>recent load</strong> (minutes
          in the last 7 days), their <strong>baseline load</strong> (weekly average over 28 days), the
          ratio between them (the <strong>workload spike, or ACWR</strong>), plus rest days,
          back-to-back games and matches in the last fortnight. Every match is then labelled with
          whether an injury followed within 14 days. A model learns from those labelled matches, and
          is only used if it beats a simple baseline in testing — otherwise scoring falls back to the
          workload rules shown above. Injury spells are reconstructed from clubs’ missed-match reports.
        </p>
      </Section>
    </div>
  );
}
