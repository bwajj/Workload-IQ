import type {
  Overview, ScoredPlayer, Correlation, PlayerDetail, RotationPlan, Injury, Gameweek, Backtest,
  PublicStats, BacktestSummary, Simulation, SimMatch, Picks, FplSquad, FixtureTicker,
  TransferSuggestions,
} from './types';

const TOKEN_KEY = 'wiq_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

// In production the API lives on a different host (set VITE_API_URL at build);
// in dev it's empty and Vite proxies /api to the local Flask server.
export const API_BASE = import.meta.env.VITE_API_URL ?? '';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(API_BASE + url, { ...options, headers });

  if (res.status === 401 && !url.startsWith('/api/auth/')) {
    // Session expired or revoked — tell the auth layer to reset.
    window.dispatchEvent(new Event('wiq:unauthorized'));
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.error) message = body.error;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

const get = <T,>(url: string) => request<T>(url);
const post = <T,>(url: string, body?: unknown) =>
  request<T>(url, { method: 'POST', body: body == null ? undefined : JSON.stringify(body) });

const teamQuery = (team?: string) =>
  team && team !== 'All' ? `?team=${encodeURIComponent(team)}` : '';

interface Session {
  token: string;
  user: { email: string; name: string };
}

export const api = {
  // Auth
  login: (email: string, password: string) => post<Session>('/api/auth/login', { email, password }),
  register: (name: string, email: string, password: string) =>
    post<Session>('/api/auth/register', { name, email, password }),
  me: () => get<{ email: string; name: string; fplTeamId?: string | null }>('/api/auth/me'),
  saveFplTeam: (teamId: string) => post<{ fplTeamId: string | null }>('/api/auth/fpl-team', { teamId }),

  // Data
  publicStats: () => get<PublicStats>('/api/public/stats'),
  health: () => get<{ status: string; mongoConnected: boolean; lastRefresh?: string | null }>('/api/health'),
  overview: () => get<Overview>('/api/overview'),
  teams: () => get<string[]>('/api/teams'),
  players: (team?: string) => get<ScoredPlayer[]>(`/api/players${teamQuery(team)}`),
  player: (id: number) => get<PlayerDetail>(`/api/players/${id}`),
  correlation: () => get<Correlation>('/api/correlation'),
  rotation: (team: string, gameweek?: number) =>
    get<RotationPlan>(`/api/rotation/${encodeURIComponent(team)}${gameweek != null ? `?gameweek=${gameweek}` : ''}`),
  gameweeks: () => get<Gameweek[]>('/api/gameweeks'),
  picks: (gameweek?: number) =>
    get<Picks>(`/api/picks${gameweek != null ? `?gameweek=${gameweek}` : ''}`),
  fplSquad: (teamId: string) => post<FplSquad>('/api/fpl', { teamId }),
  fixtureTicker: (fromRound?: number, n = 6) =>
    get<FixtureTicker>(`/api/fixture-ticker?n=${n}${fromRound != null ? `&fromRound=${fromRound}` : ''}`),
  transfers: (playerId: number, exclude: number[] = []) =>
    get<TransferSuggestions>(`/api/transfers?playerId=${playerId}${exclude.length ? `&exclude=${exclude.join(',')}` : ''}`),
  sendDigest: (gameweek?: number) =>
    post<{ gameweek: number; to: string; mailStatus: string; captains: number; risks: number }>(
      '/api/digest/send', { gameweek }),
  backtest: (gameweek?: number) =>
    get<Backtest>(`/api/backtest${gameweek != null ? `?gameweek=${gameweek}` : ''}`),
  backtestSummary: () => get<BacktestSummary>('/api/backtest/summary'),
  simulate: (id: number, extraMatches: SimMatch[]) =>
    post<Simulation>(`/api/players/${id}/simulate`, { extraMatches }),
  injuries: (team?: string) => get<Injury[]>(`/api/injuries${teamQuery(team)}`),
};
