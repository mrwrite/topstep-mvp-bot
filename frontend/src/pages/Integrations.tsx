import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useActiveIntegrationContracts } from '../hooks/useActiveIntegrationContracts';

type Integration = {
  id: number;
  display_name: string;
  provider: string;
  status: string;
  metadata?: Record<string, string>;
  created_at: string;
  updated_at: string;
  has_credentials: boolean;
};

type ProviderInfo = {
  provider: string;
  capabilities: string[];
  implemented_capabilities: string[];
  roadmap_capabilities: string[];
};

type FormState = {
  display_name: string;
  provider: string;
  status: string;
  environment: string;
  accountId: string;
  baseUrl: string;
  apiKey: string;
  apiSecret: string;
  refreshToken: string;
  userName: string;
  webhookSecret: string;
};

const PROVIDERS = [
  { value: 'TOPSTEPX', label: 'TopStepX' },
  { value: 'TRADOVATE', label: 'Tradovate' },
  { value: 'NINJATRADER', label: 'NinjaTrader' },
  { value: 'TRADINGVIEW', label: 'TradingView' },
  { value: 'IBKR', label: 'Interactive Brokers' },
  { value: 'ETX', label: 'ETX' }
];

const emptyForm: FormState = {
  display_name: '',
  provider: 'TOPSTEPX',
  status: 'active',
  environment: 'paper',
  accountId: '',
  baseUrl: '',
  apiKey: '',
  apiSecret: '',
  refreshToken: '',
  userName: '',
  webhookSecret: ''
};

const capabilityLabel = (capability: string) => {
  if (capability === 'BROKER_TRADING') return 'Broker';
  if (capability === 'MARKET_DATA') return 'Market data';
  if (capability === 'ACCOUNT_INFO') return 'Accounts';
  if (capability === 'SIGNALS') return 'Signals';
  return capability;
};

function Integrations() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [hasStoredCredentials, setHasStoredCredentials] = useState(false);
  const [activationNotice, setActivationNotice] = useState<string>('');
  const [providerInfo, setProviderInfo] = useState<ProviderInfo[]>([]);
  const navigate = useNavigate();
  const { activeIntegration, refreshActiveIntegration, setActiveIntegrationAndLoadContracts } =
    useActiveIntegrationContracts();

  const loadIntegrations = async () => {
    try {
      const res = await api.get('/integrations');
      setIntegrations(res.data ?? []);
    } catch (err) {
      console.error('Failed to load integrations', err);
      setError('Unable to load integrations. Sign in again if your session expired.');
    }
  };

  const loadProviders = async () => {
    try {
      const res = await api.get<{ providers: ProviderInfo[] }>('/integrations/providers');
      setProviderInfo(res.data.providers ?? []);
    } catch (err) {
      console.error('Failed to load providers', err);
    }
  };

  useEffect(() => {
    loadIntegrations();
    loadProviders();
    refreshActiveIntegration();
  }, [refreshActiveIntegration]);

  const providerMeta = (provider: string) =>
    providerInfo.find(item => item.provider === provider) ?? {
      provider,
      capabilities: [],
      implemented_capabilities: [],
      roadmap_capabilities: []
    };

  const selectedProvider = providerMeta(form.provider);
  const roadmapOnly =
    selectedProvider.roadmap_capabilities.length > 0 &&
    selectedProvider.implemented_capabilities.length === 0;

  const startCreate = () => {
    setForm(emptyForm);
    setEditingId(null);
    setHasStoredCredentials(false);
    setError(null);
  };

  const startEdit = (integration: Integration) => {
    setEditingId(integration.id);
    setHasStoredCredentials(integration.has_credentials);
    setForm({
      display_name: integration.display_name,
      provider: integration.provider,
      status: integration.status,
      environment: integration.metadata?.environment ?? 'paper',
      accountId: integration.metadata?.account_id ?? integration.metadata?.accountId ?? '',
      baseUrl: integration.metadata?.baseUrl ?? '',
      apiKey: '',
      apiSecret: '',
      refreshToken: '',
      userName: '',
      webhookSecret: ''
    });
  };

  const buildMetadata = () => {
    const metadata: Record<string, string> = {};
    if (form.environment) metadata.environment = form.environment;
    if (form.accountId) metadata.account_id = form.accountId;
    if (form.baseUrl) metadata.baseUrl = form.baseUrl;
    return metadata;
  };

  const buildCredentials = () => {
    const credentials: Record<string, string> = {};
    if (form.provider === 'TOPSTEPX') {
      if (form.userName) credentials.userName = form.userName;
      if (form.apiKey) credentials.apiKey = form.apiKey;
    } else if (form.provider === 'TRADINGVIEW') {
      if (form.webhookSecret) credentials.webhookSecret = form.webhookSecret;
    } else {
      if (form.apiKey) credentials.apiKey = form.apiKey;
      if (form.apiSecret) credentials.apiSecret = form.apiSecret;
      if (form.refreshToken) credentials.refreshToken = form.refreshToken;
    }
    return Object.keys(credentials).length ? credentials : null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    const payload = {
      display_name: form.display_name,
      provider: form.provider,
      status: form.status,
      metadata: buildMetadata(),
      credentials: buildCredentials()
    };

    try {
      if (editingId) {
        const updatePayload = { ...payload };
        if (!updatePayload.credentials) {
          delete updatePayload.credentials;
        }
        await api.put(`/integrations/${editingId}`, updatePayload);
      } else {
        await api.post('/integrations', payload);
      }
      await loadIntegrations();
      await refreshActiveIntegration();
      startCreate();
    } catch (err) {
      console.error('Failed to save integration', err);
      setError('Could not save integration. Check the form and try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (integrationId: number) => {
    setError(null);
    try {
      await api.delete(`/integrations/${integrationId}`);
      await loadIntegrations();
      await refreshActiveIntegration();
      if (editingId === integrationId) startCreate();
    } catch (err) {
      console.error('Failed to delete integration', err);
      setError('Could not delete integration.');
    }
  };

  const activateIntegration = async (integrationId: number) => {
    try {
      await setActiveIntegrationAndLoadContracts(integrationId);
      setActivationNotice('Active integration updated. Provider contracts refreshed.');
      window.setTimeout(() => setActivationNotice(''), 2500);
    } catch (err) {
      console.error('Failed to activate integration', err);
      setError('Unable to activate integration. It may not support provider contracts yet.');
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/', { replace: true, state: { loggedOut: true } });
  };

  const integrationsEmpty = useMemo(() => integrations.length === 0, [integrations]);
  const activeId = activeIntegration?.id;
  const formatCapabilities = (caps: string[]) => caps.map(capabilityLabel).join(' / ');

  return (
    <div className="dashboard-shell">
      <header className="topbar">
        <div className="topbar-left">
          <div>
            <p className="eyebrow">Trading workspace</p>
            <div className="app-title">Broker Integrations</div>
          </div>
          <span className="pill warning">Paper setup</span>
        </div>
        <div className="topbar-center">
          <Link to="/dashboard" className="badge link">
            Back to dashboard
          </Link>
        </div>
        <div className="topbar-right">
          <div className="topbar-actions">
            <button type="button" className="ghost compact" onClick={logout}>
              Log out
            </button>
          </div>
        </div>
      </header>

      <div className="mode-banner">
        <div>
          <p className="eyebrow">Onboarding</p>
          <h2>Connect a broker or signal source</h2>
        </div>
        <p className="muted">
          Integrations are used for paper-session context, account lookup, contracts, and signal intake.
          Live execution remains disabled.
        </p>
      </div>

      <div className="layout integrations-layout">
        <aside className="panel card">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Broker setup</p>
              <h2>{editingId ? 'Edit integration' : 'Add integration'}</h2>
            </div>
            <button type="button" className="ghost compact" onClick={startCreate}>
              New
            </button>
          </div>
          {error && <div className="inline-alert danger" role="alert">{error}</div>}
          {activationNotice && <div className="inline-alert" role="status">{activationNotice}</div>}

          <form className="integration-form" onSubmit={handleSubmit}>
            <label htmlFor="display_name">Display name</label>
            <input
              id="display_name"
              value={form.display_name}
              onChange={e => setForm({ ...form, display_name: e.target.value })}
              placeholder="Broker - Paper"
              required
            />

            <label htmlFor="provider">Provider</label>
            <select
              id="provider"
              value={form.provider}
              onChange={e => setForm({ ...form, provider: e.target.value })}
              disabled={Boolean(editingId)}
            >
              {PROVIDERS.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {roadmapOnly && (
              <div className="inline-alert warning">
                This provider is a setup preview. Execution remains unavailable until an adapter is implemented and tested.
              </div>
            )}

            <div className="capability-strip">
              <span className="pill subtle">
                Implemented: {formatCapabilities(selectedProvider.implemented_capabilities) || 'None'}
              </span>
              <span className="pill subtle">
                Roadmap: {formatCapabilities(selectedProvider.roadmap_capabilities) || 'None'}
              </span>
            </div>

            <label htmlFor="status">Status</label>
            <select id="status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })}>
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
              <option value="error">Error</option>
            </select>

            <div className="form-divider">Paper context</div>
            <label htmlFor="environment">Environment</label>
            <input
              id="environment"
              value={form.environment}
              onChange={e => setForm({ ...form, environment: e.target.value })}
              placeholder="paper / demo / sandbox"
            />
            <label htmlFor="accountId">Saved account ID</label>
            <input
              id="accountId"
              value={form.accountId}
              onChange={e => setForm({ ...form, accountId: e.target.value })}
              placeholder="Paper account or provider account id"
            />
            <label htmlFor="baseUrl">Base URL</label>
            <input
              id="baseUrl"
              value={form.baseUrl}
              onChange={e => setForm({ ...form, baseUrl: e.target.value })}
              placeholder="https://api.provider.com"
            />

            <div className="form-divider">Credentials</div>
            {hasStoredCredentials && <p className="muted tiny">Credentials are stored. Enter new values to rotate.</p>}
            {form.provider === 'TOPSTEPX' && (
              <>
                <label htmlFor="userName">Username</label>
                <input
                  id="userName"
                  value={form.userName}
                  onChange={e => setForm({ ...form, userName: e.target.value })}
                  placeholder="account username"
                />
                <label htmlFor="apiKey">API key</label>
                <input
                  id="apiKey"
                  type="password"
                  value={form.apiKey}
                  onChange={e => setForm({ ...form, apiKey: e.target.value })}
                  placeholder="stored securely"
                />
              </>
            )}

            {form.provider === 'TRADINGVIEW' && (
              <>
                <label htmlFor="webhookSecret">Webhook secret</label>
                <input
                  id="webhookSecret"
                  type="password"
                  value={form.webhookSecret}
                  onChange={e => setForm({ ...form, webhookSecret: e.target.value })}
                  placeholder="stored securely"
                />
                <p className="muted tiny">Signals only. No broker credentials required.</p>
              </>
            )}

            {form.provider !== 'TOPSTEPX' && form.provider !== 'TRADINGVIEW' && (
              <>
                <p className="muted tiny">Roadmap provider. Saved credentials will not enable execution.</p>
                <label htmlFor="apiKey">API key</label>
                <input id="apiKey" type="password" value={form.apiKey} onChange={e => setForm({ ...form, apiKey: e.target.value })} placeholder="stored securely" />
                <label htmlFor="apiSecret">API secret</label>
                <input id="apiSecret" type="password" value={form.apiSecret} onChange={e => setForm({ ...form, apiSecret: e.target.value })} placeholder="stored securely" />
                <label htmlFor="refreshToken">Refresh token</label>
                <input id="refreshToken" type="password" value={form.refreshToken} onChange={e => setForm({ ...form, refreshToken: e.target.value })} placeholder="stored securely" />
              </>
            )}

            <button type="submit" className="primary" disabled={isLoading}>
              {isLoading ? 'Saving...' : editingId ? 'Update integration' : 'Save integration'}
            </button>
          </form>
        </aside>

        <section className="card integrations-list">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Linked integrations</p>
              <h2>Integrations</h2>
            </div>
            <span className="pill">{integrations.length}</span>
          </div>

          {integrationsEmpty ? (
            <div className="empty-state">
              <h3>No integrations yet</h3>
              <p className="muted">Add a broker or signal integration to enable paper sessions and alerts.</p>
              <button type="button" className="primary" onClick={startCreate}>
                Add integration
              </button>
            </div>
          ) : (
            <div className="integration-cards">
              {integrations.map(integration => {
                const info = providerMeta(integration.provider);
                const isRoadmapOnly =
                  info.roadmap_capabilities.length > 0 && info.implemented_capabilities.length === 0;
                return (
                  <div key={integration.id} className="integration-card">
                    <div>
                      <div className="card-title-row">
                        <h3>{integration.display_name}</h3>
                        {isRoadmapOnly && <span className="pill warning">Roadmap</span>}
                      </div>
                      <p className="muted tiny">
                        {integration.provider} / {integration.status}
                      </p>
                      <p className="muted tiny">
                        Implemented: {formatCapabilities(info.implemented_capabilities) || 'None'}
                      </p>
                      <p className="muted tiny">
                        Roadmap: {formatCapabilities(info.roadmap_capabilities) || 'None'}
                      </p>
                      <div className="meta-row">
                        <span>Environment:</span>
                        <strong>{integration.metadata?.environment ?? '-'}</strong>
                      </div>
                      <div className="meta-row">
                        <span>Saved account:</span>
                        <strong>{integration.metadata?.account_id ?? integration.metadata?.accountId ?? '-'}</strong>
                      </div>
                      <div className="meta-row">
                        <span>Credentials:</span>
                        <strong>{integration.has_credentials ? 'Stored' : 'Missing'}</strong>
                      </div>
                    </div>
                    <div className="integration-actions">
                      {activeId === integration.id ? (
                        <span className="pill subtle">Active</span>
                      ) : (
                      <button type="button" className="ghost compact" onClick={() => activateIntegration(integration.id)} aria-label={`Set ${integration.display_name} as active integration`}>
                        Set active
                      </button>
                    )}
                      <button type="button" className="ghost compact" onClick={() => startEdit(integration)} aria-label={`Edit ${integration.display_name}`}>
                        Edit
                      </button>
                      <button type="button" className="ghost compact danger" onClick={() => handleDelete(integration.id)} aria-label={`Delete ${integration.display_name}`}>
                        Delete
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default Integrations;
