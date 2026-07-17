import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import type { FixtureTicker, Gameweek } from '../types';
import { Section, Loading, ErrorBanner, TeamLogo } from '../ui';

const DIFF_LABEL = ['', 'Very easy', 'Easy', 'Even', 'Hard', 'Very hard'];
const diffClass = (d: number | null) =>
  d == null ? '' : d >= 4 ? 'diff-hard' : d === 3 ? 'diff-mid' : 'diff-easy';

export default function Fixtures() {
  const [gws, setGws] = useState<Gameweek[]>([]);
  const [from, setFrom] = useState<number | null>(null);
  const [data, setData] = useState<FixtureTicker | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  useEffect(() => {
    api.gameweeks().then((g) => {
      setGws(g);
      if (g.length) setFrom((cur) => cur ?? g[0].round);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (from == null) return;
    setLoading(true);
    api.fixtureTicker(from, 6)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [from]);

  if (error) return <ErrorBanner message={error} />;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Fixture ticker</h1>
          <p className="page-lede">
            The next six gameweeks by difficulty, easiest run at the top. Green = kind
            fixtures (plan your captains and transfers around them), red = brutal.
          </p>
        </div>
        {gws.length > 0 && from != null && (
          <select className="input" value={from} onChange={(e) => setFrom(Number(e.target.value))}>
            {gws.map((g) => <option key={g.round} value={g.round}>From GW {g.round}</option>)}
          </select>
        )}
      </div>

      {loading || !data ? <Loading what="fixtures" /> : (
        <Section label="Difficulty grid" aside="sorted easiest → hardest">
          <div className="ticker-wrap">
            <table className="ticker">
              <thead>
                <tr>
                  <th className="ticker-team">Team</th>
                  {data.rounds.map((r) => <th key={r}>GW{r}</th>)}
                  <th className="r">Avg</th>
                </tr>
              </thead>
              <tbody>
                {data.teams.map((t) => (
                  <tr key={t.team}>
                    <td className="ticker-team">
                      <TeamLogo team={t.team} size={18} />{t.team}
                    </td>
                    {data.rounds.map((r) => {
                      const fx = t.fixtures.find((f) => f.round === r);
                      return (
                        <td key={r} className={`ticker-cell ${fx ? diffClass(fx.difficulty) : ''}`}
                          title={fx ? `${fx.home ? 'vs' : '@'} ${fx.opponent} — ${DIFF_LABEL[fx.difficulty ?? 0]}` : ''}>
                          {fx ? (
                            <>
                              <TeamLogo team={fx.opponent} size={16} />
                              <span className="ticker-ha">{fx.home ? 'H' : 'A'}</span>
                            </>
                          ) : '—'}
                        </td>
                      );
                    })}
                    <td className="r ticker-avg">{t.avgDifficulty ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="footnote" style={{ marginTop: 12 }}>
            Difficulty is the opponent's strength (league position + home/away), 1 (easiest)
            to 5 (hardest). Hover a cell for the opponent. {' '}
            <button className="linklike" onClick={() => nav('/picks')}>See this week's picks →</button>
          </p>
        </Section>
      )}
    </div>
  );
}
