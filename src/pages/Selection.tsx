import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import type { RotationPlan, ScoredPlayer, Position, Gameweek } from '../types';
import { Section, Loading, ErrorBanner, tierClass, PlayerPhoto, TeamLogo } from '../ui';

const ROWS: Position[] = ['FWD', 'MID', 'DEF', 'GK'];
const POS_LABEL: Record<Position, string> = {
  GK: 'Goalkeepers', DEF: 'Defenders', MID: 'Midfielders', FWD: 'Forwards',
};

/** A pending swap source — either a drag in progress or a clicked player. */
interface Grab {
  id: number;
  position: Position;
  from: 'xi' | 'bench';
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
}

function shortDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

const DIFF_LABEL = ['', 'Very favourable', 'Favourable', 'Standard', 'Tough', 'Very tough'];
const diffClass = (d: number) => (d >= 4 ? 'danger-text' : d === 3 ? 'warn-text' : 'ok-text');

/** Colour a start-confidence score: green = start, amber = toss-up, red = bench. */
const confClass = (score: number) => (score >= 60 ? 'low' : score >= 45 ? 'moderate' : 'high');

function ordinal(n: number) {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] ?? s[v] ?? 'th');
}

export default function Selection() {
  const nav = useNavigate();
  const [teams, setTeams] = useState<string[]>([]);
  const [team, setTeam] = useState('');
  const [gws, setGws] = useState<Gameweek[]>([]);
  const [gw, setGw] = useState<number | null>(null);
  const [plan, setPlan] = useState<RotationPlan | null>(null);
  const [squad, setSquad] = useState<ScoredPlayer[]>([]);
  const [xiIds, setXiIds] = useState<number[]>([]);
  const [recIds, setRecIds] = useState<number[]>([]);
  const [grab, setGrab] = useState<Grab | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.teams().then((t) => {
      setTeams(t);
      if (t.length) setTeam(t[0]);
    }).catch((e) => setError(e.message));
    api.gameweeks().then((g) => {
      setGws(g);
      if (g.length) setGw((cur) => cur ?? g[g.length - 1].round);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!team) return;
    setLoading(true);
    setGrab(null);
    api.rotation(team, gw ?? undefined)
      .then((p) => {
        setPlan(p);
        setSquad(p.squad ?? []);
        const ids = p.recommendedXI.map((x) => x.playerId);
        setXiIds(ids);
        setRecIds(ids);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [team, gw]);

  const byId = useMemo(() => new Map(squad.map((p) => [p.playerId, p])), [squad]);
  const injuryById = useMemo(
    () => new Map((plan?.unavailable ?? []).map((p) => [p.playerId, p.injuryType])),
    [plan],
  );

  const xi = xiIds.map((id) => byId.get(id)).filter(Boolean) as ScoredPlayer[];
  const bench = squad.filter((p) => !xiIds.includes(p.playerId));

  const avgOf = (ids: number[]) => {
    const ps = ids.map((id) => byId.get(id)).filter(Boolean) as ScoredPlayer[];
    return ps.length ? Math.round(ps.reduce((s, p) => s + p.riskScore, 0) / ps.length) : 0;
  };
  const avg = avgOf(xiIds);
  const recAvg = avgOf(recIds);
  const delta = avg - recAvg;

  const formOf = (ids: number[]) => {
    const fs = ids
      .map((id) => byId.get(id)?.form)
      .filter((f): f is number => f != null);
    return fs.length ? fs.reduce((s, f) => s + f, 0) / fs.length : null;
  };
  const avgForm = formOf(xiIds);
  const recForm = formOf(recIds);
  const formDelta = avgForm != null && recForm != null ? +(avgForm - recForm).toFixed(1) : 0;

  const confOf = (ids: number[]) => {
    const cs = ids.map((id) => byId.get(id)?.confidence).filter((c): c is number => c != null);
    return cs.length ? Math.round(cs.reduce((s, c) => s + c, 0) / cs.length) : null;
  };
  const avgConf = confOf(xiIds);

  const customized = xiIds.some((id) => !recIds.includes(id));
  const highInXI = xi.filter((p) => p.riskTier === 'High');

  const swap = (benchId: number, xiId: number) => {
    setXiIds((ids) => ids.map((id) => (id === xiId ? benchId : id)));
    setGrab(null);
  };

  /** Would dropping the current grab on this player be a valid swap? */
  const isTarget = (p: ScoredPlayer, side: 'xi' | 'bench') =>
    grab != null && grab.from !== side && grab.position === p.position &&
    (side === 'xi' || p.available !== false);

  const resolveSwap = (target: ScoredPlayer, side: 'xi' | 'bench') => {
    if (!grab || !isTarget(target, side)) return;
    if (side === 'xi') swap(grab.id, target.playerId);   // bench player comes in for the starter
    else swap(target.playerId, grab.id);                  // starter goes out for the bench player
  };

  if (error) return <ErrorBanner message={error} />;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Selection</h1>
          <p className="page-lede">
            Start from the lowest-risk XI, then test your own ideas. Drag a bench player onto
            a starter in the same position (or click one, then the other) and watch the lineup
            respond. <strong>Start confidence</strong> (0–100) blends injury risk, form, fatigue
            and fixture difficulty into one number; essentially a risk vs. reward metric for each player.
          </p>
        </div>
        <div className="controls">
          {gws.length > 0 && gw != null && (
            <select className="input" value={gw} onChange={(e) => setGw(Number(e.target.value))}>
              {gws.map((g) => (
                <option key={g.round} value={g.round}>
                  Gameweek {g.round} · {shortDate(g.start)}
                </option>
              ))}
            </select>
          )}
          <select className="input" value={team} onChange={(e) => setTeam(e.target.value)}>
            {teams.map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
      </div>

      {loading || !plan ? <Loading what="selection" /> : (
        <>
          {plan.fixture && (
            <>
              <div className="fixture">
                <div className="fixture-cell">
                  <div className="micro">Next fixture</div>
                  <div className="fixture-match">
                    <TeamLogo team={plan.team} size={22} />{plan.team}
                    <span className="vs">{plan.fixture.home ? 'vs' : '@'}</span>
                    <TeamLogo team={plan.fixture.opponent} size={22} />{plan.fixture.opponent}
                  </div>
                  {plan.european && (
                    <div className="small muted" style={{ marginTop: 3 }}>
                      Also competing in the {plan.european}
                    </div>
                  )}
                </div>
                <div className="fixture-cell">
                  <div className="micro">Date</div>
                  <div><strong>{formatDate(plan.fixture.date)}</strong></div>
                </div>
                {plan.fixture.difficulty != null && (
                  <div className="fixture-cell">
                    <div className="micro">
                      Difficulty{plan.fixture.opponentRank ? ` · opponent ${ordinal(plan.fixture.opponentRank)}` : ''}
                    </div>
                    <div>
                      <strong className={`num ${diffClass(plan.fixture.difficulty)}`}>
                        {plan.fixture.difficulty}/5
                      </strong>
                      {' '}· {DIFF_LABEL[plan.fixture.difficulty]}
                    </div>
                  </div>
                )}
                <div className="fixture-cell">
                  <div className="micro">Your XI · avg risk / avg form</div>
                  <div>
                    <strong className="num">{avg}%</strong>
                    {customized && delta !== 0 && (
                      <span className={`small ${delta > 0 ? 'danger-text' : 'ok-text'}`}>
                        {' '}{delta > 0 ? `+${delta}` : delta}%
                      </span>
                    )}
                    <span className="muted"> / </span>
                    <strong className="num">{avgForm != null ? avgForm.toFixed(1) : '—'}</strong>
                    {customized && formDelta !== 0 && (
                      <span className={`small ${formDelta > 0 ? 'ok-text' : 'danger-text'}`}>
                        {' '}{formDelta > 0 ? `+${formDelta}` : formDelta}
                      </span>
                    )}
                  </div>
                </div>
                {avgConf != null && (
                  <div className="fixture-cell">
                    <div className="micro">XI start confidence</div>
                    <div><strong className={`num ${confClass(avgConf) === 'low' ? 'ok-text' : confClass(avgConf) === 'moderate' ? 'warn-text' : 'danger-text'}`}>{avgConf}</strong> <span className="muted">/ 100</span></div>
                  </div>
                )}
              </div>
              {plan.fixture.difficulty != null && (
                <p className="footnote" style={{ marginTop: 10 }}>
                  {plan.fixture.difficulty <= 2
                    ? 'A favourable fixture: a good spot to rest fatigued or high-risk starters and still expect a result.'
                    : plan.fixture.difficulty >= 4
                      ? 'A tough fixture: fielding in-form starters may be worth some extra risk. Weigh each swap’s form against its risk.'
                      : 'A standard fixture: balance form and risk player by player.'}
                  {plan.asOf && (
                    <> Risk, fatigue, form and availability are computed as of{' '}
                    <strong>{shortDate(plan.asOf)}</strong> — the eve of this gameweek.</>
                  )}
                  {gws.length > 0 && (
                    <>{' '}<button className="linklike" onClick={() => nav('/evidence')}>
                      See how these scores fared in the backtest →
                    </button></>
                  )}
                </p>
              )}
            </>
          )}

          <div className="cols-2" style={{ marginTop: 8 }}>
            <Section
              label={customized ? 'Your XI' : 'Recommended XI'}
              aside={customized
                ? <button className="linklike" onClick={() => { setXiIds(recIds); setGrab(null); }}>Reset to recommended</button>
                : '4-3-3 · lowest risk per position'}
            >
              <div className="pitch" style={{ marginTop: 18 }}>
                {ROWS.map((row) => (
                  <div className="pitch-row" key={row}>
                    {xi.filter((p) => p.position === row).map((p) => (
                      <Token
                        key={p.playerId}
                        p={p}
                        grabbed={grab?.id === p.playerId}
                        droppable={isTarget(p, 'xi')}
                        onGrab={() => setGrab(grab?.id === p.playerId ? null : { id: p.playerId, position: p.position, from: 'xi' })}
                        onDrop={() => resolveSwap(p, 'xi')}
                        onDragStart={() => setGrab({ id: p.playerId, position: p.position, from: 'xi' })}
                        onDragEnd={() => setGrab(null)}
                        onView={() => nav(`/player/${p.playerId}`)}
                      />
                    ))}
                  </div>
                ))}
              </div>
              {highInXI.length > 0 && (
                <p className="footnote" style={{ marginTop: 12 }}>
                  <span className="danger-text">⚠ High risk in this XI:</span>{' '}
                  {highInXI.map((p) => `${p.playerName} (${p.riskScore}%)`).join(' · ')}
                </p>
              )}
              <p className="footnote" style={{ marginTop: 6 }}>
                Swaps are position-for-position, so the shape holds. Injured players can’t be selected.
              </p>
            </Section>

            <Section label={`Bench — full squad · ${bench.length}`}>
              {ROWS.slice().reverse().map((pos) => {
                const group = bench
                  .filter((p) => p.position === pos)
                  .sort((a, b) =>
                    (a.available === false ? 1 : 0) - (b.available === false ? 1 : 0) ||
                    (b.confidence ?? 0) - (a.confidence ?? 0));
                if (group.length === 0) return null;
                return (
                  <div key={pos} style={{ marginTop: 16 }}>
                    <span className="micro">{POS_LABEL[pos]}</span>
                    <ul className="rows">
                      {group.map((p) => {
                        const out = p.available === false;
                        return (
                          <li
                            key={p.playerId}
                            className={[
                              out ? 'out' : 'draggable',
                              grab?.id === p.playerId ? 'grabbed' : '',
                              isTarget(p, 'bench') ? 'drop-ok' : '',
                            ].filter(Boolean).join(' ')}
                            draggable={!out}
                            onDragStart={(e) => {
                              e.dataTransfer.setData('text/plain', String(p.playerId));
                              setGrab({ id: p.playerId, position: p.position, from: 'bench' });
                            }}
                            onDragEnd={() => setGrab(null)}
                            onDragOver={(e) => { if (isTarget(p, 'bench')) e.preventDefault(); }}
                            onDrop={(e) => { e.preventDefault(); resolveSwap(p, 'bench'); }}
                            onClick={() => {
                              if (isTarget(p, 'bench')) resolveSwap(p, 'bench');
                              else if (!out) setGrab(grab?.id === p.playerId ? null : { id: p.playerId, position: p.position, from: 'bench' });
                            }}
                          >
                            <div className="who player-flex">
                              <PlayerPhoto id={p.playerId} name={p.playerName} size={30} />
                              <div>
                                <strong
                                  className="link"
                                  title={`View ${p.playerName}`}
                                  onClick={(e) => {
                                    if (isTarget(p, 'bench')) { resolveSwap(p, 'bench'); }
                                    else { e.stopPropagation(); nav(`/player/${p.playerId}`); }
                                  }}
                                >
                                  {p.playerName}
                                </strong>
                                {out && <span className="pill high" style={{ marginLeft: 8 }}>Out</span>}
                                <div className="why">
                                  {out
                                    ? (injuryById.get(p.playerId) ?? 'Injured')
                                    : [
                                        `Risk ${p.riskScore}%`,
                                        p.form != null ? `Form ${p.form.toFixed(1)}` : null,
                                        p.fatigue != null ? `Fatigue ${p.fatigue}` : null,
                                        p.confidenceDriver,
                                      ].filter(Boolean).join(' · ')}
                                </div>
                              </div>
                            </div>
                            {out ? (
                              <span className="risk-num"><span className="dot high" />{p.riskScore}%</span>
                            ) : (
                              <div className="conf-badge" title="Start confidence — risk, form, fatigue & fixture combined">
                                <span className={`conf-score ${confClass(p.confidence ?? 0)}`}>{p.confidence ?? '—'}</span>
                                <span className="conf-label">{p.confidenceLabel}</span>
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })}
            </Section>
          </div>
        </>
      )}
    </div>
  );
}

function Token({ p, grabbed, droppable, onGrab, onDrop, onDragStart, onDragEnd, onView }: {
  p: ScoredPlayer;
  grabbed: boolean;
  droppable: boolean;
  onGrab: () => void;
  onDrop: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onView: () => void;
}) {
  const t = tierClass(p.riskTier);
  const tip = [
    p.number != null ? `#${p.number}` : null,
    p.confidence != null ? `Start confidence ${p.confidence} (${p.confidenceLabel})` : null,
    p.form != null ? `Form ${p.form.toFixed(1)}` : null,
    p.fatigue != null ? `Fatigue ${p.fatigue}/100` : null,
    ...p.reasons,
  ].filter(Boolean).join(' · ');
  return (
    <div
      className={['token', grabbed ? 'grabbed' : '', droppable ? 'drop-ok' : ''].filter(Boolean).join(' ')}
      title={tip}
      draggable
      onDragStart={(e) => { e.dataTransfer.setData('text/plain', String(p.playerId)); onDragStart(); }}
      onDragEnd={onDragEnd}
      onDragOver={(e) => { if (droppable) e.preventDefault(); }}
      onDrop={(e) => { e.preventDefault(); onDrop(); }}
      onClick={() => (droppable ? onDrop() : onGrab())}
    >
      <div className={`token-shirt ${t}`}>
        <PlayerPhoto id={p.playerId} name={p.playerName} size={37} />
      </div>
      <div
        className="token-name link"
        title={`View ${p.playerName}`}
        onClick={(e) => { if (droppable) { onDrop(); } else { e.stopPropagation(); onView(); } }}
      >
        {p.playerName.split(' ').slice(-1)[0]}
      </div>
      <div className="token-meta">
        <span className={`token-risk ${t}`}>{p.riskScore}%</span>
        {p.form != null && <span className="token-form">{p.form.toFixed(1)}</span>}
      </div>
      {p.startWarning && <div className="token-warn" title={p.startWarning}>⚠</div>}
    </div>
  );
}
