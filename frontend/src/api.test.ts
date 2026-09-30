import { beforeEach, describe, expect, it } from 'vitest';
import { api, applySessionSecurity, clearObsoleteBearerTokens } from './api';

describe('secure browser API session', () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie = 'tradebot_csrf=csrf-value; path=/';
  });

  it('clears obsolete bearer tokens and uses credentials with CSRF', async () => {
    localStorage.setItem('token', 'legacy-secret');
    clearObsoleteBearerTokens();
    expect(localStorage.getItem('token')).toBeNull();
    expect(api.defaults.withCredentials).toBe(true);

    const config = applySessionSecurity({ method: 'post', headers: {} });
    expect(config?.headers?.['X-CSRF-Token']).toBe('csrf-value');
    expect(config?.headers?.Authorization).toBeUndefined();
  });
});
