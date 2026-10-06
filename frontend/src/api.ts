import axios from 'axios';

// Production browser traffic stays on the Vercel origin and is forwarded to
// Railway by vercel.json. This keeps the HttpOnly session and readable CSRF
// cookies first-party instead of relying on third-party cookie support.
export const API_BASE_URL = import.meta.env.PROD
  ? '/api'
  : import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
});

const obsoleteKeys = ['token', 'access_token', 'refresh_token'];
export const clearObsoleteBearerTokens = () =>
  obsoleteKeys.forEach(key => localStorage.removeItem(key));
clearObsoleteBearerTokens();

export const csrfToken = () => {
  const prefix = 'tradebot_csrf=';
  return document.cookie
    .split(';')
    .map(value => value.trim())
    .find(value => value.startsWith(prefix))
    ?.slice(prefix.length);
};

export const applySessionSecurity = <T extends { method?: string; headers?: any }>(config: T) => {
  const method = (config.method ?? 'get').toLowerCase();
  const csrf = csrfToken();
  if (csrf && !['get', 'head', 'options'].includes(method)) {
    config.headers = config.headers ?? {};
    config.headers['X-CSRF-Token'] = decodeURIComponent(csrf);
  }
  return config;
};

api.interceptors.request.use(config => applySessionSecurity(config));
