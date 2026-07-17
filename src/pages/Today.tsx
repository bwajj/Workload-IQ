import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import type { Overview, ScoredPlayer, RiskTier } from '../types';
import { Section, Kpi, RiskCell, TierPill, Loading, ErrorBanner, PlayerPhoto, TeamLogo } from '../ui';

const TIERS: Array<RiskTier | 'All'> = ['All', 'High', 'Moderate', 'Low'];

export default function Today() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [players, setPlayers] = useState<ScoredPlayer[]>([]);
  const [teams, setTeams] = useState<string[]>([]);
  const [team, setTeam] = useState('All');
  const [tier, setTier] = useState<RiskTier | 'All'>('All');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [loadingPlayers, setLoadingPlayers] = useState(true);
  const nav = useNavigate();

  useEffect(() => {
    api.overview().then(setOverview).catch((e) => setError(e.message));
    api.teams().then(setTeams).catch(() => {});
  }, []);

  useEffect(() => {
    setLoadingPlayers(true);
    api.players(team)
      .then(setPlayers)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingPlayers(false));
  }, [team]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return players
      .filter((p) => tier === 'All' || p.riskTier === tier)
      .filter((p) => !q || p.playerName.toLowerCase().includes(q) || p.team.toLowerCase().includes(q));
  }, [players, tier, search]);

  if (error) return <ErrorBanner message={error} />;
  if (!overview) return <Loading what="today’s picture" />;

  const injuredShown = players.filter((p) => p.available === false).length;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Who’s at risk today</h1>
          <p className="page-lede">
            Every monitored player, ranked by 14-day injury risk from rolling workload 
            acute:chronic ratio, rest and fixture congestion.
          </p>
        </div>
      </div>

      <div className="kpis">
        <Kpi value={overview.counts.players} label="Players monitored" />
        <Kpi value={overview.counts.teams} label="Clubs" />
        <Kpi value={overview.counts.games.toLocaleString()} label="Box scores" />
        <Kpi value={overview.riskTiers.High} label="High risk now" tone="High" />
        <Kpi value={overview.riskTiers.Moderate} label="Moderate risk" tone="Moderate" />
        <Kpi value={overview.counts.activeInjuries} label="Currently injured" />
      </div>

      <Section
        label="Squad risk — ranked"
        aside={`${filtered.length} of ${players.length} players${team !== 'All' ? ` · ${team}` : ''}${injuredShown ? ` · ${injuredShown} injured` : ''}`}
      >
        <div className="controls" style={{ margin: '18px 0 6px' }}>
          <input
            className="input search"
            placeholder="Search player or club…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select className="input" value={team} onChange={(e) => setTeam(e.target.value)}>
            <option>All</option>
            {teams.map((t) => <option key={t}>{t}</option>)}
          </select>
          <div className="seg">
            {TIERS.map((t) => (
              <button key={t} className={tier === t ? 'on' : ''} onClick={() => setTier(t)}>
                {t}
              </button>
            ))}
          </div>
        </div>

        {loadingPlayers ? (
          <Loading what="players" />
        ) : filtered.length === 0 ? (
          <div className="empty">No players match your filters.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th className="rank">#</th>
                <th>Player</th>
                <th>Pos</th>
                <th className="r">ACWR</th>
                <th className="r">Acute 7d</th>
                <th className="r">Rest</th>
                <th className="r">Fatigue</th>
                <th className="r">Form</th>
                <th className="r">Risk</th>
                <th>Tier</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p, i) => (
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
                  <td className={`r ${p.acwr >= 1.5 ? 'danger-text' : p.acwr >= 1.3 ? 'warn-text' : ''}`}>{p.acwr}</td>
                  <td className="r">{p.acute7}′</td>
                  <td className="r">{p.restDays}d</td>
                  <td className={`r ${(p.fatigue ?? 0) >= 70 ? 'danger-text' : (p.fatigue ?? 0) >= 45 ? 'warn-text' : ''}`}>
                    {p.fatigue ?? '—'}
                  </td>
                  <td className="r">{p.form != null ? p.form.toFixed(1) : '—'}</td>
                  <td className="r"><RiskCell score={p.riskScore} tier={p.riskTier} /></td>
                  <td><TierPill tier={p.riskTier} /></td>
                  <td>
                    {p.available === false
                      ? <span className="pill high">Injured</span>
                      : <span className="pill neutral">Fit</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <p className="footnote" style={{ marginTop: 16 }}>
          {overview.model.modelType === 'rules'
            ? <>Risk is scored with the validated ACWR rule set (workload spikes, short rest, congestion, age).</>
            : <>Risk combines a gradient-boosted model (AUC {overview.model.auc}) predicting soft-tissue injuries, with ACWR rules.</>}
          {overview.model.note && <> {overview.model.note}</>}
          {' '}See <a href="/evidence" onClick={(e) => { e.preventDefault(); nav('/evidence'); }}>Evidence</a> for the full methodology.
        </p>
      </Section>
    </div>
  );
}
