import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from '../router';
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
  availability: string;
  enabled: boolean;
  accepts_credentials: boolean;
  live_trading_enabled: boolean;
  summary: string;
  evidence_reviewed_at: string;
};

type TopstepAccount = { provider_account_id: string; display_label: string; can_trade: boolean; is_visible: boolean };
type TopstepStatus = {
  integration_id?: number;
  connection_state: string;
  approval_state: string;
  lifecycle_version?: number;
  approved_account_label?: string;
  approval_expiration?: string;
  credentials_require_replacement?: boolean;
};
type HostedPolicy = { state: string; policy_version?: number; required_consent_version?: string;
  allowed_strategies?: string[]; allowed_instruments?: string[]; max_order_quantity?: number;
  max_open_position?: number; max_orders_per_session?: number; max_orders_per_day?: number;
  max_consecutive_losses?: number; max_daily_realized_loss?: number; max_session_loss?: number;
  max_stale_data_seconds?: number; cooldown_seconds?: number; trading_schedule?: Record<string, unknown>;
  dry_run_enabled?: boolean;
  provider_order_execution_enabled?: boolean };
type DryRunStatus = { id: string; state: string; result_classification?: string;
  risk_checks?: { check: string; passed: boolean; classification?: string }[];
  proposal?: { id: string; status: 'dry_run_only'; strategy_signal: string; rationale: string;
    instrument: string; side: string; quantity: number; order_type: string } | null;
  provider_order_submitted: false; message: string };

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
  provider: 'TRADINGVIEW',
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
  const [topstepStatus, setTopstepStatus] = useState<TopstepStatus | null>(null);
  const [topstepAccounts, setTopstepAccounts] = useState<TopstepAccount[]>([]);
  const [topstepUsername, setTopstepUsername] = useState('');
  const [topstepApiKey, setTopstepApiKey] = useState('');
  const [selectedTopstepAccount, setSelectedTopstepAccount] = useState('');
  const [combineAccepted, setCombineAccepted] = useState(false);
  const [hostedPolicy, setHostedPolicy] = useState<HostedPolicy | null>(null);
  const [dryRun, setDryRun] = useState<DryRunStatus | null>(null);
  const [hostedConsentAccepted, setHostedConsentAccepted] = useState(false);
  const connectIdempotencyKey = useRef(crypto.randomUUID());
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

  const loadTopstepStatus = async () => {
    const response = await api.get<TopstepStatus>('/integrations/topstepx/status');
    setTopstepStatus(response.data);
    if (response.data.integration_id) {
      const accounts = await api.get<{ accounts: TopstepAccount[] }>('/integrations/topstepx/accounts', {
        params: { integration_id: response.data.integration_id }
      });
      setTopstepAccounts(accounts.data.accounts);
      const policy = await api.get<HostedPolicy>('/integrations/topstepx/risk-policy', {
        params: { integration_id: response.data.integration_id }
      }).catch(() => ({ data: { state: 'unavailable' } as HostedPolicy }));
      setHostedPolicy(policy.data);
      setHostedConsentAccepted(false);
    } else {
      setTopstepAccounts([]);
      setHostedPolicy(null);
      setHostedConsentAccepted(false);
    }
  };

  useEffect(() => {
    loadIntegrations();
    loadProviders();
    loadTopstepStatus().catch(() => setTopstepStatus({ connection_state: 'unavailable', approval_state: 'none' }));
    refreshActiveIntegration();
  }, [refreshActiveIntegration]);

  const submitTopstepCredentials = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const credentials = { username: topstepUsername, api_key: topstepApiKey,
      expected_lifecycle_version: topstepStatus?.lifecycle_version };
    try {
      if (topstepStatus?.integration_id) {
        await api.put('/integrations/topstepx/credentials', credentials, {
          params: { integration_id: topstepStatus.integration_id }
        });
      } else {
        await api.post('/integrations/topstepx/connect', credentials, {
          headers: { 'Idempotency-Key': connectIdempotencyKey.current }
        });
        connectIdempotencyKey.current = crypto.randomUUID();
      }
      await loadTopstepStatus();
    } catch {
      setError('TopstepX credentials could not be validated. No secret details were retained or returned.');
    } finally {
      setTopstepUsername('');
      setTopstepApiKey('');
    }
  };

  const submitCombineAttestation = async () => {
    if (!topstepStatus?.integration_id) return;
    try {
      await api.post('/integrations/topstepx/attest', {
        integration_id: topstepStatus.integration_id,
        provider_account_id: selectedTopstepAccount,
        accepted: combineAccepted,
        attestation_version: 'topstep-combine-v1',
        expected_lifecycle_version: topstepStatus.lifecycle_version
      });
      setCombineAccepted(false);
      await loadTopstepStatus();
    } catch {
      setError('The attestation could not be recorded for this discovered account.');
    }
  };

  const acceptHostedConsent = async () => {
    if (!topstepStatus?.integration_id || !selectedTopstepAccount || !hostedPolicy?.policy_version) return;
    try {
      await api.post('/integrations/topstepx/consent', {
        integration_id: topstepStatus.integration_id, provider_account_id: selectedTopstepAccount,
        policy_version: hostedPolicy.policy_version, consent_version: hostedPolicy.required_consent_version,
        accepted: true
      });
      setHostedConsentAccepted(true);
      setError(null);
    } catch {
      setError('Current administrator approval and risk policy are required before consent is recorded.');
    }
  };

  const startHostedDryRun = async () => {
    if (!topstepStatus?.integration_id || !selectedTopstepAccount || !hostedPolicy?.policy_version) return;
    try {
      const response = await api.post<{ dry_run: { id: string } }>('/integrations/topstepx/dry-runs', {
        integration_id: topstepStatus.integration_id, provider_account_id: selectedTopstepAccount,
        policy_version: hostedPolicy.policy_version
      }, { headers: { 'Idempotency-Key': crypto.randomUUID() } });
      const status = await api.get<DryRunStatus>(`/integrations/topstepx/dry-runs/${response.data.dry_run.id}`);
      setDryRun(status.data);
    } catch {
      setError('Dry run could not be queued. No order was submitted.');
    }
  };

  useEffect(() => {
    if (!dryRun || !['requested', 'eligibility_checking', 'market_data_loading', 'evaluating', 'risk_evaluating'].includes(dryRun.state)) return;
    const timer = window.setTimeout(() => {
      api.get<DryRunStatus>(`/integrations/topstepx/dry-runs/${dryRun.id}`)
        .then(response => setDryRun(response.data)).catch(() => undefined);
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [dryRun]);

  const disconnectTopstep = async (permanent: boolean) => {
    if (!topstepStatus?.integration_id) return;
    try {
      const config = { params: { integration_id: topstepStatus.integration_id,
        expected_lifecycle_version: topstepStatus.lifecycle_version } };
      if (permanent) await api.delete('/integrations/topstepx', config);
      else await api.post('/integrations/topstepx/disconnect', undefined, config);
      setTopstepAccounts([]);
      setSelectedTopstepAccount('');
      await loadTopstepStatus();
    } catch {
      setError('The integration lifecycle request could not be completed.');
    }
  };

  const providerMeta = (provider: string) =>
    providerInfo.find(item => item.provider === provider) ?? {
      provider,
      capabilities: [],
      implemented_capabilities: [],
      roadmap_capabilities: [],
      availability: 'ROADMAP',
      enabled: false,
      accepts_credentials: false,
      live_trading_enabled: false,
      summary: 'Provider availability is still loading.',
      evidence_reviewed_at: 'unknown'
    };

  const selectedProvider = providerMeta(form.provider);
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

  const logout = async () => {
    await api.post('/auth/logout').catch(() => undefined);
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

      <section className="card" aria-labelledby="topstep-combine-heading">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Invite-only hosted beta</p>
            <h2 id="topstep-combine-heading">Topstep Trading Combine</h2>
          </div>
          <span className="pill warning">No funded or live accounts</span>
        </div>
        <p className="muted">
          Use a dedicated TopstepX API key. Automated actions can affect your Combine evaluation and subscription value.
          Saved credentials are never displayed again.
        </p>
        <p className="muted tiny">
          State: {topstepStatus?.connection_state ?? 'loading'} / Approval: {topstepStatus?.approval_state ?? 'none'}
          {topstepStatus?.approved_account_label ? ` / ${topstepStatus.approved_account_label}` : ''}
        </p>
        <form className="integration-form" onSubmit={submitTopstepCredentials} autoComplete="off">
          <label htmlFor="topstep-username">TopstepX platform username</label>
          <input id="topstep-username" name="topstep-beta-username" value={topstepUsername}
            onChange={event => setTopstepUsername(event.target.value)} autoComplete="off" required />
          <label htmlFor="topstep-api-key">Dedicated TopstepX API key</label>
          <input id="topstep-api-key" name="topstep-beta-api-key" type="password" value={topstepApiKey}
            onChange={event => setTopstepApiKey(event.target.value)} autoComplete="new-password" required />
          <button className="primary" type="submit">
            {topstepStatus?.integration_id ? 'Validate replacement credentials' : 'Connect and discover accounts'}
          </button>
        </form>
        {topstepAccounts.length > 0 && (
          <div className="integration-form">
            <label htmlFor="topstep-account">Discovered account</label>
            <select id="topstep-account" value={selectedTopstepAccount}
              onChange={event => { setSelectedTopstepAccount(event.target.value); setHostedConsentAccepted(false); setDryRun(null); }}>
              <option value="">Select an account</option>
              {topstepAccounts.filter(account => account.can_trade && account.is_visible).map(account => (
                <option key={account.provider_account_id} value={account.provider_account_id}>{account.display_label}</option>
              ))}
            </select>
            <label>
              <input type="checkbox" checked={combineAccepted}
                onChange={event => setCombineAccepted(event.target.checked)} />
              I attest this is a Trading Combine, not an Express Funded or Live Funded Account, and authorize
              automated actions only within configured limits.
            </label>
            <p className="muted tiny">Attestation does not enable trading. An administrator must approve this exact account.</p>
            <button type="button" className="primary" disabled={!selectedTopstepAccount || !combineAccepted}
              onClick={submitCombineAttestation}>Submit attestation</button>
          </div>
        )}
        <div className="integration-form" aria-label="Hosted Combine dry run">
          <h3>Risk policy and dry run</h3>
          {hostedPolicy?.state === 'active' ? <>
            <p className="muted tiny">Policy v{hostedPolicy.policy_version}; strategies: {hostedPolicy.allowed_strategies?.join(', ') || 'none'};
              instruments: {hostedPolicy.allowed_instruments?.join(', ') || 'none'}; maximum quantity: {hostedPolicy.max_order_quantity ?? 'unset'}.
            </p>
            <p className="muted tiny">Open positions: {hostedPolicy.max_open_position ?? 'unset'}; orders/session: {hostedPolicy.max_orders_per_session ?? 'unset'};
              orders/day: {hostedPolicy.max_orders_per_day ?? 'unset'}; daily loss: {hostedPolicy.max_daily_realized_loss ?? 'unset'};
              session loss: {hostedPolicy.max_session_loss ?? 'unset'}; stale-data max: {hostedPolicy.max_stale_data_seconds ?? 'unset'} seconds.
            </p>
            <p className="muted tiny">I represent this is a Trading Combine, not Express Funded or Live Funded. Automated analysis may affect decisions;
              this dry run submits no orders. Any future separately enabled execution could affect evaluation results. I remain responsible for Topstep rules
              and monitoring, may disconnect and revoke my key, and emergency controls may suspend activity without notice. This is not a waiver of application security obligations.</p>
            <button type="button" className="ghost compact" disabled={!selectedTopstepAccount || topstepStatus?.approval_state !== 'approved'}
              onClick={acceptHostedConsent}>Accept current dry-run consent</button>
            <button type="button" className="primary" disabled={!hostedConsentAccepted || !selectedTopstepAccount || topstepStatus?.approval_state !== 'approved' || !hostedPolicy.dry_run_enabled}
              onClick={startHostedDryRun}>Start read-only dry run</button>
          </> : <p className="muted">Awaiting administrator risk policy. Missing policy denies dry-run readiness.</p>}
          {dryRun && <div role="status">
            <p><strong>{dryRun.state}</strong> — {dryRun.message}</p>
            {dryRun.proposal && <p>{dryRun.proposal.side} {dryRun.proposal.quantity} {dryRun.proposal.instrument} — dry-run only. {dryRun.proposal.rationale}</p>}
            {dryRun.risk_checks?.map(check => <p className="muted tiny" key={check.check}>{check.check}: {check.passed ? 'pass' : 'not ready'}</p>)}
          </div>}
        </div>
        {topstepStatus?.integration_id && (
          <div className="integration-actions">
            <button type="button" className="ghost compact" onClick={() => disconnectTopstep(false)}>Disconnect</button>
            <button type="button" className="ghost compact danger" onClick={() => disconnectTopstep(true)}>
              Delete stored integration
            </button>
          </div>
        )}
        <p className="muted tiny">
          Deleting this integration does not revoke the key at Topstep. Revoke the dedicated key in TopstepX after testing
          or immediately if compromise is suspected.
        </p>
      </section>

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
                <option
                  key={option.value}
                  value={option.value}
                  disabled={!providerMeta(option.value).enabled}
                >
                  {option.label}{providerMeta(option.value).enabled ? '' : ' — roadmap/unavailable'}
                </option>
              ))}
            </select>
            {!selectedProvider.enabled && (
              <div className="inline-alert warning">
                {selectedProvider.summary}
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
            <p className="muted tiny">Provider evidence reviewed: {selectedProvider.evidence_reviewed_at}</p>

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

            {selectedProvider.accepts_credentials && <div className="form-divider">Credentials</div>}
            {hasStoredCredentials && <p className="muted tiny">Credentials are stored. Enter new values to rotate.</p>}
            {selectedProvider.accepts_credentials && form.provider === 'TRADINGVIEW' && (
              <>
                <label htmlFor="webhookSecret">Webhook secret</label>
                <input
                  id="webhookSecret"
                  type="password"
                  value={form.webhookSecret}
                  onChange={e => setForm({ ...form, webhookSecret: e.target.value })}
                  placeholder="stored securely"
                />
                <p className="muted tiny">Webhook signal source only. TradingView is not used as a market-data API or broker.</p>
              </>
            )}

            {!selectedProvider.accepts_credentials && (
              <div className="inline-alert warning">
                Credential entry is disabled. {selectedProvider.summary}
              </div>
            )}

            <button type="submit" className="primary" disabled={isLoading || !selectedProvider.enabled}>
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
