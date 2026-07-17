import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { ThemeToggle } from '../ui';

type Mode = 'signin' | 'register';

export default function Login() {
  const { login, register, guest } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<Mode>('signin');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      if (mode === 'signin') await login(email, password);
      else await register(name, email, password);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const continueAsGuest = async () => {
    setError('');
    setBusy(true);
    try {
      await guest();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <ThemeToggle className="login-theme" />

      <div className="login-panel">
        <div
          className="wordmark"
          style={{ marginBottom: 30, cursor: 'pointer' }}
          onClick={() => nav('/')}
          title="Back to the tour"
        >
          <span className="wordmark-dot" />
          Workload IQ
        </div>

        <h1 className="login-title">
          {mode === 'signin' ? 'Sign in' : 'Create an account'}
        </h1>
        <p className="muted small" style={{ margin: '6px 0 22px' }}>
          Injury-risk analytics for the Premier League.
        </p>

        <button className="btn btn-guest" onClick={continueAsGuest} disabled={busy}>
          {busy ? 'One moment…' : 'Continue as guest →'}
        </button>
        <div className="login-divider"><span>or {mode === 'signin' ? 'sign in' : 'sign up'}</span></div>

        <form onSubmit={submit}>
          {mode === 'register' && (
            <label className="field">
              <span className="micro">Name</span>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Mikel Arteta"
                autoComplete="name"
              />
            </label>
          )}
          <label className="field">
            <span className="micro">Email</span>
            <input
              className="input"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@club.com"
              autoComplete="email"
            />
          </label>
          <label className="field">
            <span className="micro">Password</span>
            <input
              className="input"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'register' ? 'At least 8 characters' : '••••••••••'}
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            />
          </label>

          {error && <p className="login-error">{error}</p>}

          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? 'One moment…' : mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p className="small muted" style={{ marginTop: 18 }}>
          {mode === 'signin' ? (
            <>New here?{' '}
              <button className="linklike" onClick={() => { setMode('register'); setError(''); }}>
                Create an account
              </button>
            </>
          ) : (
            <>Already have an account?{' '}
              <button className="linklike" onClick={() => { setMode('signin'); setError(''); }}>
                Sign in
              </button>
            </>
          )}
        </p>

        <div className="demo-hint">
          <div className="micro" style={{ marginBottom: 6 }}>Demo access</div>
          <div className="small">
            <code>demo@workloadiq.app</code> · <code>matchday2024</code>
          </div>
        </div>
      </div>
    </div>
  );
}
