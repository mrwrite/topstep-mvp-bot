import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { api, API_BASE_URL } from '../api';

function Login() {
  const [form, setForm] = useState({ username: '', password: '' });
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const expired = (location.state as { expired?: boolean } | null)?.expired;
  const loggedOut = (location.state as { loggedOut?: boolean } | null)?.loggedOut;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    const body = new URLSearchParams();
    body.append('username', form.username);
    body.append('password', form.password);
    body.append('grant_type', 'password');

    try {
      const res = await api.post('/auth/token', body, {
        baseURL: API_BASE_URL,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      const token = res.data?.access_token ?? res.data?.token;
      if (!token) {
        setError('Login failed: unexpected server response.');
        setIsLoading(false);
        return;
      }
      localStorage.setItem('token', token);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      console.error('Login failed', err);
      setError('Login failed. Please check your username and password.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="login-panel">
        <div className="login-header">
          <div>
            <p className="eyebrow">Trading Bot</p>
            <h1>Sign in</h1>
            <p className="muted">Connect to monitor the RSI bot and manage sessions.</p>
          </div>
          <span className="pill status success">Secure</span>
        </div>
        {loggedOut && (
          <div className="inline-alert" role="status" aria-live="polite">
            You have been logged out.
          </div>
        )}
        {expired && (
          <div className="inline-alert warning" role="alert" aria-live="polite">
            Your session expired. Please log in again.
          </div>
        )}
        {error && (
          <div className="inline-alert danger" role="alert" aria-live="assertive">
            {error}
          </div>
        )}
        <form onSubmit={handleSubmit} className="login-form">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            value={form.username}
            onChange={e => setForm({ ...form, username: e.target.value })}
            placeholder="Username"
            autoComplete="username"
            required
            disabled={isLoading}
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={form.password}
            onChange={e => setForm({ ...form, password: e.target.value })}
            placeholder="Password"
            autoComplete="current-password"
            required
            disabled={isLoading}
          />
          <button type="submit" className="primary" disabled={isLoading}>
            {isLoading ? 'Logging in…' : 'Login'}
          </button>
        </form>
        <p className="tiny muted">API: {API_BASE_URL}</p>
        <p className="tiny muted">
          New here? <Link to="/register">Create an account</Link>
        </p>
      </div>
    </div>
  );
}

export default Login;
