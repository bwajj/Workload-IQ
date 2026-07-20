import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import type { Picks as PicksData, Gameweek } from '../types';
import { Section, Loading, ErrorBanner, PlayerPhoto, TeamLogo, tierClass } from '../ui';

const confClass = (score: number) => (score >= 60 ? 'low' : score >= 45 ? 'moderate' : 'high');
const DIFF_LABEL = ['', 'Very easy', 'Easy', 'Even', 'Hard', 'Very hard'];
const diffClass = (d: number) => (d >= 4 ? 'danger-text' : d === 3 ? 'warn-text' : 'ok-text');

function shortDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

export default function Picks() {
  const [gws, setGws] = useState<Gameweek[]>([]);
  const [gw, setGw] = useState<number | null>(null);
  const [data, setData] = useState<PicksData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [digest, setDigest] = useState<{ busy: boolean; msg: string; ok: boolean }>({ busy: false, msg: '', ok: true });
  const nav = useNavigate();

  const emailDigest = async () => {
    setDigest({ busy: true, msg: '', ok: true });
    try {
      const r = await api.sendDigest(gw ?? undefined);
      const note = r.mailStatus === 'smtp' ? `Sent to ${r.to}` : `Saved to dev outbox (no SMTP configured)`;
      setDigest({ busy: false, msg: note, ok: true });
    } catch (e) {
      setDigest({ busy: false, msg: (e as Error).message, ok: false });
    }
  };

  useEffect(() => {
    api.gameweeks().then((g) => {
      setGws(g);
      if (g.length) setGw((cur) => cur ?? g[g.length - 1].round);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (gw == null) return;
    setLoading(true);
    api.picks(gw)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [gw]);

  if (error) return <ErrorBanner message={error} />;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Picks</h1>
          <p className="page-lede">
            Who to trust this gameweek. Every fit regular is ranked by <strong>start
            confidence</strong> — injury risk, form, fatigue and fixture difficulty fused into
            one number — so you can spot the safe captains and the players to sit.
          </p>
        </div>
        {gws.length > 0 && gw != null && (
          <div className="controls">
            <button className="btn" onClick={emailDigest} disabled={digest.busy}>
              {digest.busy ? 'Sending…' : '✉ Email me this digest'}
            </button>
            <select className="input" value={gw} onChange={(e) => setGw(Number(e.target.value))}>
              {gws.map((g) => (
                <option key={g.round} value={g.round}>Gameweek {g.round} · {shortDate(g.start)}</option>
              ))}
            </select>
          </div>
        )}
      </div>
      {digest.msg && (
        <p className={`footnote ${digest.ok ? 'ok-text' : 'danger-text'}`} style={{ marginTop: -8 }}>
          {digest.ok ? '✓ ' : ''}{digest.msg}
        </p>
      )}

      {loading || !data ? <Loading what="picks" /> : (
        <div className="cols-2">
          <Section label="Captain shortlist" aside={`${data.ranked} regulars ranked`}>
            <div className="table-scroll" style={{ marginTop: 12 }}>
            <table className="table">
              <thead>
                <tr>
                  <th className="rank">#</th>
                  <th>Player</th>
                  <th>Pos</th>
                  <th>Fixture</th>
                  <th className="r">Form</th>
                  <th className="r">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {data.captainPicks.map((p, i) => (
                  <tr key={p.playerId} className="clickable" onClick={() => nav(`/player/${p.playerId}`)}>
                    <td className="rank num">{i + 1}</td>
                    <td>
                      <div className="player-flex">
                        <PlayerPhoto id={p.playerId} name={p.playerName} size={30} />
                        <div>
                          <div className="player-cell">{p.playerName}</div>
                          <div className="sub"><TeamLogo team={p.team} size={13} />{p.team}</div>
                        </div>
                      </div>
                    </td>
                    <td>{p.position}</td>
                    <td>
                      <span className="fixture-mini">
                        {p.home ? 'v' : '@'} <TeamLogo team={p.opponent} size={14} />
                        {p.difficulty != null && (
                          <span className={`diff-chip ${diffClass(p.difficulty)}`} title={DIFF_LABEL[p.difficulty]}>
                            {p.difficulty}
                          </span>
                        )}
                      </span>
                    </td>
                    <td className="r">{p.form != null ? p.form.toFixed(1) : '—'}</td>
                    <td className="r">
                      <span className={`conf-inline ${confClass(p.confidence)}`}>{p.confidence}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            <p className="footnote" style={{ marginTop: 12 }}>
              Confidence favours reliable, in-form starters with soft fixtures — the low-variance
              captain picks, not the boom-or-bust punts.
            </p>
          </Section>

          <Section label="Sit / injury risks" aside={`${data.avoid.length} flagged`}>
            {data.avoid.length === 0 ? (
              <p className="footnote" style={{ marginTop: 14 }}>No high-risk regulars this gameweek.</p>
            ) : (
              <ul className="rows">
                {data.avoid.map((p) => (
                  <li key={p.playerId} className="clickable" onClick={() => nav(`/player/${p.playerId}`)}>
                    <div className="who player-flex">
                      <PlayerPhoto id={p.playerId} name={p.playerName} size={30} />
                      <div>
                        <strong className="link">{p.playerName}</strong>{' '}
                        <span className="muted small">{p.position} · {p.home ? 'v' : '@'} {p.opponent}</span>
                        <div className="why">{p.reasons[0]}</div>
                      </div>
                    </div>
                    <span className="risk-num"><span className={`dot ${tierClass(p.riskTier)}`} />{p.riskScore}%</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="footnote" style={{ marginTop: 12 }}>
              These regulars carry an elevated 14-day injury risk (workload spikes, short rest, or
              just back from injury) — think twice before starting or captaining them.
            </p>
          </Section>
        </div>
      )}
    </div>
  );
}
