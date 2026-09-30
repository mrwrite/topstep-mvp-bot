import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RouterProvider } from '../router';
import Integrations from './Integrations';
import { api } from '../api';

const providerResponse = {
  providers: [
    {
      provider: 'TOPSTEPX',
      capabilities: ['MARKET_DATA', 'ACCOUNT_INFO'],
      implemented_capabilities: ['MARKET_DATA', 'ACCOUNT_INFO'],
      roadmap_capabilities: [],
      availability: 'UNSUITABLE_HOSTED_BETA',
      enabled: false,
      accepts_credentials: false,
      live_trading_enabled: false,
      summary: 'Unavailable for hosted beta.',
      evidence_reviewed_at: '2026-07-26'
    },
    {
      provider: 'TRADINGVIEW',
      capabilities: ['SIGNALS'],
      implemented_capabilities: ['SIGNALS'],
      roadmap_capabilities: [],
      availability: 'SIGNAL_ONLY',
      enabled: true,
      accepts_credentials: true,
      live_trading_enabled: false,
      summary: 'Signal webhook source only.',
      evidence_reviewed_at: '2026-07-26'
    }
  ]
};

vi.mock('../api', () => ({
  api: {
    get: vi.fn((path: string) => {
      if (path === '/integrations/providers') return Promise.resolve({ data: providerResponse });
      if (path === '/integrations/active') return Promise.resolve({ data: { active: null } });
      if (path === '/integrations/topstepx/status') {
        return Promise.resolve({ data: { connection_state: 'not_connected', approval_state: 'none' } });
      }
      return Promise.resolve({ data: [] });
    }),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}));

const refreshActiveIntegration = vi.fn(() => Promise.resolve());
const setActiveIntegrationAndLoadContracts = vi.fn();

vi.mock('../hooks/useActiveIntegrationContracts', () => ({
  useActiveIntegrationContracts: () => ({
    activeIntegration: null,
    refreshActiveIntegration,
    setActiveIntegrationAndLoadContracts
  })
}));

afterEach(() => cleanup());

describe('provider availability UI', () => {
  it('disables TopstepX credential onboarding and identifies TradingView as signals only', async () => {
    render(<RouterProvider><Integrations /></RouterProvider>);
    await waitFor(() => expect(screen.getByText(/Webhook signal source only/)).toBeInTheDocument());
    expect(screen.getByRole('option', { name: /TopStepX.*unavailable/ })).toBeDisabled();
    expect(screen.queryByLabelText('Username')).not.toBeInTheDocument();
    expect(screen.getByText(/not used as a market-data API or broker/)).toBeInTheDocument();
  });

  it('uses a masked dedicated Combine form, clears secrets, and displays revocation guidance', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { integration_id: 1 } });
    render(<RouterProvider><Integrations /></RouterProvider>);
    const username = await screen.findByLabelText('TopstepX platform username');
    const apiKey = screen.getByLabelText('Dedicated TopstepX API key');
    expect(apiKey).toHaveAttribute('type', 'password');
    fireEvent.change(username, { target: { value: 'platform-user' } });
    fireEvent.change(apiKey, { target: { value: 'secret-api-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect and discover accounts' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/integrations/topstepx/connect',
      expect.objectContaining({ username: 'platform-user', api_key: 'secret-api-key' }),
      expect.objectContaining({ headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }) })));
    await waitFor(() => expect(apiKey).toHaveValue(''));
    expect(username).toHaveValue('');
    expect(screen.getByText(/does not revoke the key at Topstep/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /enable order/i })).not.toBeInTheDocument();
  });
});
