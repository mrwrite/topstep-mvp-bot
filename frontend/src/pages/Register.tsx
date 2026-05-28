import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, API_BASE_URL } from '../api';

const MIN_PASSWORD_LENGTH = 10;

function Register() {
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    confirm: ''
  });
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const validate = () => {
    if (form.password.length < MIN_PASSWORD_LENGTH) {
      return 'Password must be at least 10 characters.';
    }
    if (form.password !== form.confirm) {
      return 'Passwords do not match.';
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsLoading(true);

    try {
      await api.post('/auth/register', {
        username: form.username,
        email: form.email,
        password: form.password
      });

      const body = new URLSearchParams();
      body.append('username', form.username);
      body.append('password', form.password);
      body.append('grant_type', 'password');

      const tokenResponse = await api.post('/auth/token', body, {
        baseURL: API_BASE_URL,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      const token = tokenResponse.data?.access_token ?? tokenResponse.data?.token;
      if (!token) {
        setError('Registration succeeded, but login failed. Please sign in.');
        setIsLoading(false);
        return;
      }
      localStorage.setItem('token', token);
      navigate('/integrations', { replace: true });
    } catch (err) {
      console.error('Registration failed', err);
      setError('Registration failed. Please check your details and try again.');
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
            <h1>Create account</h1>
            <p className="muted">Set up your credentials and connect integrations.</p>
          </div>
          <span className="pill status success">New</span>
        </div>
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
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={form.email}
            onChange={e => setForm({ ...form, email: e.target.value })}
            placeholder="you@example.com"
            autoComplete="email"
            required
            disabled={isLoading}
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={form.password}
            onChange={e => setForm({ ...form, password: e.target.value })}
            placeholder="Strong password"
            autoComplete="new-password"
            required
            disabled={isLoading}
          />
          <label htmlFor="confirm">Confirm password</label>
          <input
            id="confirm"
            type="password"
            value={form.confirm}
            onChange={e => setForm({ ...form, confirm: e.target.value })}
            placeholder="Re-enter password"
            autoComplete="new-password"
            required
            disabled={isLoading}
          />
          <button type="submit" className="primary" disabled={isLoading}>
            {isLoading ? 'Creating account…' : 'Create account'}
          </button>
        </form>
        <p className="tiny muted">API: {API_BASE_URL}</p>
        <p className="tiny muted">
          Already have an account? <Link to="/">Sign in</Link>
        </p>
      </div>
    </div>
  );
}

export default Register;
