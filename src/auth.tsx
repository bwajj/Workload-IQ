import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, setToken, getToken } from './api';

export interface User {
  email: string;
  name: string;
  fplTeamId?: string | null;
}

// Public demo account — also shown on the login screen.
export const DEMO_EMAIL = 'demo@workloadiq.app';
export const DEMO_PASSWORD = 'matchday2024';

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  guest: () => Promise<void>;
  saveFplTeam: (teamId: string) => Promise<void>;
  logout: () => void;
}

const AuthCtx = createContext<AuthState>({
  user: null,
  ready: false,
  login: async () => {},
  register: async () => {},
  guest: async () => {},
  saveFplTeam: async () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  // Re-validate a stored token on boot.
  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    api.me()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);

  // The API layer fires this when any request comes back 401.
  useEffect(() => {
    const onExpired = () => {
      setToken(null);
      setUser(null);
    };
    window.addEventListener('wiq:unauthorized', onExpired);
    return () => window.removeEventListener('wiq:unauthorized', onExpired);
  }, []);

  const login = async (email: string, password: string) => {
    const res = await api.login(email, password);
    setToken(res.token);
    setUser(res.user);
  };

  const register = async (name: string, email: string, password: string) => {
    const res = await api.register(name, email, password);
    setToken(res.token);
    setUser(res.user);
  };

  const guest = () => login(DEMO_EMAIL, DEMO_PASSWORD);

  const saveFplTeam = async (teamId: string) => {
    const { fplTeamId } = await api.saveFplTeam(teamId);
    setUser((u) => (u ? { ...u, fplTeamId } : u));
  };

  const logout = () => {
    setToken(null);
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, ready, login, register, guest, saveFplTeam, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  return useContext(AuthCtx);
}
