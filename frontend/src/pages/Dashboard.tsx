import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from '../router';
import { api, API_BASE_URL } from '../api';
import { Contract } from '../api/contracts';
import { useActiveIntegrationContracts } from '../hooks/useActiveIntegrationContracts';

const DEFAULT_CONTRACTS = ['ES', 'NQ', 'YM', 'CL', 'GC'];
const RESOLUTION_LABELS: Record<string, string> = {
  '1': '1m',
  '3': '3m',
  '5': '5m',
  '15': '15m',
  '60': '1h',
  D: '1D'
};

type SessionState = 'Idle' | 'Running' | 'Error';
type User = { username: string };

type Integration = {
  id: number;
  display_name: string;
  provider: string;
  status: string;
  metadata?: Record<string, unknown>;
  has_credentials?: boolean;
};

type Account = {
  id: string | number;
  name?: string;
  active?: boolean;
};

type PaperOrder = {
  order?: {
    id: number;
    symbol: string;
    side: string;
    quantity: number;
    status: string;
    order_id?: string;
    created_at?: string;
  };
  status?: string;
  paper?: boolean;
  live?: boolean;
};

type Position = {
  id: number;
  symbol: string;
  quantity: number;
  account_id?: string;
};

type StrategySignal = {
  id: number;
  symbol: string;
  signal: string;
  status: string;
  reason?: string;
  created_at: string;
};

type StrategyMetrics = {
  paper_only: boolean;
  orders: number;
  signals: number;
  executed_signals: number;
  suppressed_signals: number;
  wins: number;
  losses: number;
  realized_pnl: number;
  assumptions?: string[];
};

type DemoStatus = {
  seeded: boolean;
  paper_only: boolean;
  live_trading_enabled: boolean;
  demo_account_id?: string | null;
  demo_contracts: string[];
  counts: {
    integrations: number;
    paper_orders: number;
    paper_positions: number;
    strategy_signals: number;
  };
  checklist: Array<{
    label: string;
    status: string;
    detail: string;
  }>;
  disclaimer: string;
  remaining_blockers: string[];
};

type RiskSettings = {
  id: number;
  enabled: boolean;
  max_quantity: number;
  max_contracts: number;
  max_daily_loss: number;
  max_open_positions: number;
  live_trading_enabled: boolean;
};

type KillSwitch = {
  id: number;
  active: boolean;
  reason?: string;
  account_id?: string | null;
};

type PaperAccount = {
  id: number;
  integration_id?: number | null;
  account_id?: string | null;
  cash_balance: number;
  equity: number;
  buying_power: number;
  realized_pnl: number;
};

type LaunchGate = {
  all_required_gates_passed: boolean;
  live_trading_available: boolean;
  live_trading_blocked_reason?: string | null;
  gates: Array<{
    code: string;
    passed: boolean;
    detail: string;
    metadata?: Record<string, unknown>;
  }>;
};

type OperationalStatus = {
  live_trading_enabled: boolean;
  execution_mode: string;
  readiness_checklist: Array<{
    code: string;
    label: string;
    passed: boolean;
    detail: string;
    priority: string;
  }>;
};

type DeviceTelemetry = {
  read_only: true;
  execution_authority: 'personal_device';
  installations: Array<{
    installation_hash: string;
    last_device_event_at: string;
    freshness_seconds: number;
    freshness: 'delayed_read_only' | 'stale';
    health: Record<string, unknown>;
    lifecycle: Record<string, unknown>;
    controls_available: false;
  }>;
};

type LegalStatus = {
  all_required_accepted: boolean;
  live_trading_enabled: boolean;
  blockers: Array<{
    code: string;
    document_type: string;
    version: string;
    detail: string;
  }>;
  documents: Array<{
    id: number;
    document_type: string;
    version: string;
    title: string;
    content_markdown: string;
    accepted: boolean;
    accepted_at?: string | null;
  }>;
};

type BetaStatus = {
  ready: boolean;
  beta_access_active: boolean;
  live_trading_enabled: boolean;
  blockers: Array<{
    code: string;
    detail: string;
    status?: string;
  }>;
  beta_access: {
    status: string;
    active: boolean;
    source?: string | null;
    waitlist?: {
      status: string;
      email: string;
    } | null;
  };
};

type OnboardingStatus = {
  required_complete: boolean;
  live_trading_enabled: boolean;
  checklist: Array<{
    code: string;
    label: string;
    complete: boolean;
    required: boolean;
    detail: string;
  }>;
  guidance: {
    integration_walkthrough: string[];
    paper_trading_setup: string[];
    strategy_setup: string[];
  };
};

type HelpTopic = {
  slug: string;
  title: string;
  summary: string;
};

type SubscriptionPlan = {
  code: string;
  name: string;
  status: string;
  billing_mode: string;
  features: string[];
  checkout_enabled: boolean;
};

type SubscriptionStatus = {
  subscription: {
    plan_code: string;
    status: string;
    billing_status: string;
  } | null;
  entitlements: string[];
  feature_gates: Array<{
    feature_code: string;
    allowed: boolean;
    reason_code: string;
    detail: string;
    live_trading_enabled: boolean;
  }>;
  billing: {
    billing_enabled: boolean;
    checkout_enabled: boolean;
    payment_collection_enabled: boolean;
    reason_code: string;
  };
  plans: SubscriptionPlan[];
  live_trading_enabled: boolean;
};

type ReadinessItem = {
  label: string;
  ready: boolean;
  detail: string;
  blocksPaper: boolean;
};

type TradePrompt = {
  side: string;
  price: number;
  symbol: string;
  quantity: number;
  idempotency_key: string;
};

type MarketStructureSnapshot = {
  divergences: any[];
  liquidity_sweeps: any[];
  fair_value_gaps: any[];
  supply_demand_zones: any[];
};

type BacktestResult = {
  trades: Array<{
    side: string;
    entry_time: string;
    exit_time: string;
    entry_price: number;
    exit_price: number;
    pnl: number;
  }>;
  total_pnl: number;
  wins: number;
  losses: number;
  signals: Record<string, number>;
  patterns: Record<string, number>;
  assumptions?: string[];
};

const unixFromLocal = (value: string) => Math.floor(new Date(value).getTime() / 1000);

const apiMessage = (err: unknown, fallback: string) => {
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: unknown } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === 'string') return message;
    }
  }
  return fallback;
};

const contractSymbol = (contract: Contract) =>
  contract.symbol ?? contract.name ?? String(contract.id ?? '');

function Dashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string>(DEFAULT_CONTRACTS[0]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>('');
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountsError, setAccountsError] = useState<string>('');
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [providerHealth, setProviderHealth] = useState<string>('Unchecked');
  const [resolution, setResolution] = useState<string>('1');
  const [buyThreshold, setBuyThreshold] = useState<number>(30);
  const [sellThreshold, setSellThreshold] = useState<number>(70);
  const [autoTrade, setAutoTrade] = useState<boolean>(false);
  const [quantity, setQuantity] = useState<number>(1);
  const [intervalSeconds, setIntervalSeconds] = useState<number>(60);
  const [logs, setLogs] = useState<string[]>([]);
  const [pendingTrade, setPendingTrade] = useState<TradePrompt | null>(null);
  const [latestOrder, setLatestOrder] = useState<PaperOrder | null>(null);
  const [openOrders, setOpenOrders] = useState<PaperOrder[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [strategySignals, setStrategySignals] = useState<StrategySignal[]>([]);
  const [strategyMetrics, setStrategyMetrics] = useState<StrategyMetrics | null>(null);
  const [demoStatus, setDemoStatus] = useState<DemoStatus | null>(null);
  const [riskSettings, setRiskSettings] = useState<RiskSettings | null>(null);
  const [killSwitches, setKillSwitches] = useState<KillSwitch[]>([]);
  const [paperAccounts, setPaperAccounts] = useState<PaperAccount[]>([]);
  const [launchGate, setLaunchGate] = useState<LaunchGate | null>(null);
  const [opsStatus, setOpsStatus] = useState<OperationalStatus | null>(null);
  const [deviceTelemetry, setDeviceTelemetry] = useState<DeviceTelemetry | null>(null);
  const [legalStatus, setLegalStatus] = useState<LegalStatus | null>(null);
  const [betaStatus, setBetaStatus] = useState<BetaStatus | null>(null);
  const [onboardingStatus, setOnboardingStatus] = useState<OnboardingStatus | null>(null);
  const [helpTopics, setHelpTopics] = useState<HelpTopic[]>([]);
  const [subscriptionStatus, setSubscriptionStatus] = useState<SubscriptionStatus | null>(null);
  const [legalBusy, setLegalBusy] = useState(false);
  const [supportBusy, setSupportBusy] = useState(false);
  const [supportForm, setSupportForm] = useState({
    category: 'paper_session',
    severity: 'normal',
    subject: '',
    message: ''
  });
  const [readinessError, setReadinessError] = useState('');
  const [demoBusy, setDemoBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [countdown, setCountdown] = useState<number>(0);
  const [sessionState, setSessionState] = useState<SessionState>('Idle');
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected'>(
    'disconnected'
  );
  const [analysisStart, setAnalysisStart] = useState<string>(() => {
    const d = new Date(Date.now() - 24 * 60 * 60 * 1000);
    return d.toISOString().slice(0, 16);
  });
  const [analysisEnd, setAnalysisEnd] = useState<string>(() => new Date().toISOString().slice(0, 16));
  const [analysisResult, setAnalysisResult] = useState<MarketStructureSnapshot | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState<string>('');
  const [analysisError, setAnalysisError] = useState<string>('');
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [backtestStatus, setBacktestStatus] = useState<string>('');
  const [backtestError, setBacktestError] = useState<string>('');
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const stored = localStorage.getItem('theme');
    return stored === 'light' ? 'light' : 'dark';
  });

  const eventSourceRef = useRef<EventSource | null>(null);
  const logContainerRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();
  const {
    activeIntegration,
    contracts,
    contractsError,
    contractsSource,
    loadingContracts,
    setActiveIntegrationAndLoadContracts,
  } = useActiveIntegrationContracts();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    return () => eventSourceRef.current?.close();
  }, []);

  const refreshTradingState = async () => {
    try {
      const [openRes, positionsRes, signalsRes, metricsRes] = await Promise.all([
        api.get('/scheduler/open-orders'),
        api.get('/scheduler/positions'),
        api.get('/scheduler/strategy-signals'),
        api.get('/scheduler/strategy-metrics')
      ]);
      setOpenOrders(openRes.data ?? []);
      setPositions(positionsRes.data ?? []);
      setStrategySignals(signalsRes.data ?? []);
      setStrategyMetrics(metricsRes.data ?? null);
    } catch (err) {
      console.error('Failed to load paper trading state', err);
    }
  };

  const refreshDemoStatus = async () => {
    try {
      const res = await api.get('/demo/status');
      setDemoStatus(res.data);
    } catch (err) {
      console.error('Failed to load demo status', err);
    }
  };

  const refreshLegalStatus = async () => {
    const res = await api.get('/legal/documents');
    setLegalStatus(res.data);
  };

  const refreshBetaStatus = async () => {
    const res = await api.get('/beta/status');
    setBetaStatus(res.data);
  };

  const refreshOnboardingStatus = async () => {
    const res = await api.get('/onboarding/status');
    setOnboardingStatus(res.data);
  };

  const refreshHelpTopics = async () => {
    const res = await api.get('/onboarding/help');
    setHelpTopics(res.data?.topics ?? []);
  };

  const refreshSubscriptionStatus = async () => {
    const res = await api.get('/subscription/status');
    setSubscriptionStatus(res.data);
  };

  const refreshDeviceTelemetry = async () => {
    const res = await api.get('/device-telemetry');
    setDeviceTelemetry(res.data);
  };

  const completeOnboardingMilestone = async (code: string) => {
    try {
      const res = await api.post('/onboarding/milestones', { code });
      setOnboardingStatus(res.data);
      setStatusMessage('Onboarding step updated. Live trading remains disabled.');
    } catch (err) {
      setStatusMessage(apiMessage(err, 'Unable to update onboarding step.'));
    }
  };

  const submitSupportRequest = async (event: React.FormEvent) => {
    event.preventDefault();
    setSupportBusy(true);
    try {
      const res = await api.post('/onboarding/support', {
        ...supportForm,
        integration_id: activeIntegration?.id,
        diagnostics: {
          selected_symbol: selectedSymbol,
          selected_account_id: selectedAccountId,
          paper_only: true
        }
      });
      setStatusMessage(`Support request ${res.data.reference_id} received.`);
      setSupportForm({ category: 'paper_session', severity: 'normal', subject: '', message: '' });
    } catch (err) {
      setStatusMessage(apiMessage(err, 'Unable to submit support request.'));
    } finally {
      setSupportBusy(false);
    }
  };

  const acceptRequiredLegalDocuments = async () => {
    setLegalBusy(true);
    setStatusMessage('');
    try {
      const res = await api.post('/legal/acceptances', {
        accept_terms_of_service: true,
        accept_privacy_policy: true,
        accept_paper_trading_disclosure: true,
        metadata: { source: 'dashboard_legal_panel' }
      });
      setLegalStatus(res.data);
      setStatusMessage('Required paper-beta documents accepted. Live trading remains disabled.');
    } catch (err) {
      setStatusMessage(apiMessage(err, 'Unable to record legal acceptance.'));
    } finally {
      setLegalBusy(false);
    }
  };

  const refreshReadinessState = async () => {
    setReadinessError('');
    const scope =
      activeIntegration?.id && selectedAccountId && selectedSymbol
        ? { integration_id: activeIntegration.id, account_id: selectedAccountId, symbol: selectedSymbol }
        : {};

    const [riskRes, killRes, accountRes, launchRes, opsRes] = await Promise.allSettled([
      api.get('/risk/settings', { params: { ...scope, trading_mode: 'paper' } }),
      api.get('/risk/kill-switches', { params: { active_only: true } }),
      api.get('/scheduler/paper-accounts'),
      api.get('/launch-gate', { params: scope }),
      api.get('/ops/status')
    ]);

    if (riskRes.status === 'fulfilled') setRiskSettings(riskRes.value.data);
    if (killRes.status === 'fulfilled') setKillSwitches(killRes.value.data ?? []);
    if (accountRes.status === 'fulfilled') setPaperAccounts(accountRes.value.data ?? []);
    if (launchRes.status === 'fulfilled') setLaunchGate(launchRes.value.data);
    if (opsRes.status === 'fulfilled') setOpsStatus(opsRes.value.data);

    const failed = [riskRes, killRes, accountRes, launchRes, opsRes].some(result => result.status === 'rejected');
    if (failed) {
      setReadinessError('Some readiness diagnostics are unavailable. Trading remains paper-only.');
    }
  };

  useEffect(() => {
    api
      .get('/auth/me')
      .then(res => {
        setUser(res.data);
        setConnectionStatus('connected');
      })
      .catch(err => {
        if (err.response && err.response.status === 401) {
          navigate('/', { replace: true, state: { expired: true } });
        } else {
          setConnectionStatus('disconnected');
        }
      });

    api
      .get('/auth/rules')
      .then(res => {
        setBuyThreshold(res.data.buy_threshold ?? 30);
        setSellThreshold(res.data.sell_threshold ?? 70);
      })
      .catch(() => {
        setBuyThreshold(30);
        setSellThreshold(70);
      });

    api
      .get('/integrations')
      .then(res => setIntegrations(res.data ?? []))
      .catch(err => {
        console.error('Failed to load integrations', err);
        setStatusMessage('Unable to load integrations. Sign in again if the session expired.');
      });

    refreshTradingState();
    refreshDemoStatus();
    refreshLegalStatus().catch(err => {
      console.error('Failed to load legal status', err);
      setReadinessError('Legal acceptance status is unavailable. Paper beta access remains blocked.');
    });
    refreshBetaStatus().catch(err => {
      console.error('Failed to load beta status', err);
      setReadinessError('Beta access status is unavailable. Paper beta access remains blocked.');
    });
    refreshOnboardingStatus().catch(err => {
      console.error('Failed to load onboarding status', err);
      setReadinessError('Onboarding status is unavailable. Paper beta access remains blocked.');
    });
    refreshHelpTopics().catch(err => console.error('Failed to load help topics', err));
    refreshSubscriptionStatus().catch(err => {
      console.error('Failed to load subscription status', err);
      setReadinessError('Subscription entitlement status is unavailable. Beta features remain gated by the backend.');
    });
    refreshDeviceTelemetry().catch(err => {
      console.error('Failed to load local device telemetry', err);
    });
  }, [navigate]);

  useEffect(() => {
    refreshReadinessState().catch(err => {
      console.error('Failed to load readiness diagnostics', err);
      setReadinessError('Readiness diagnostics are unavailable. Trading remains paper-only.');
    });
  }, [activeIntegration?.id, selectedAccountId, selectedSymbol]);

  const seedDemoPackage = async () => {
    setDemoBusy(true);
    try {
      const res = await api.post('/demo/seed');
      setDemoStatus(res.data);
      setStatusMessage('Demo package loaded. Live trading remains disabled.');
      await refreshTradingState();
      await refreshReadinessState();
      api.get('/integrations').then(integrationRes => setIntegrations(integrationRes.data ?? []));
    } catch (err) {
      setStatusMessage(apiMessage(err, 'Unable to load demo package.'));
    } finally {
      setDemoBusy(false);
    }
  };

  const resetDemoPackage = async () => {
    setDemoBusy(true);
    try {
      const res = await api.post('/demo/reset');
      setDemoStatus(res.data);
      setStatusMessage('Demo package reset.');
      await refreshTradingState();
      await refreshReadinessState();
      api.get('/integrations').then(integrationRes => setIntegrations(integrationRes.data ?? []));
    } catch (err) {
      setStatusMessage(apiMessage(err, 'Unable to reset demo package.'));
    } finally {
      setDemoBusy(false);
    }
  };

  useEffect(() => {
    const loadAccountsAndDiagnostics = async () => {
      setSelectedAccountId('');
      setAccounts([]);
      setAccountsError('');
      setProviderHealth('Unchecked');

      if (!activeIntegration?.id) return;

      const savedAccount =
        typeof activeIntegration.metadata?.account_id === 'string'
          ? activeIntegration.metadata.account_id
          : typeof activeIntegration.metadata?.accountId === 'string'
            ? activeIntegration.metadata.accountId
            : '';

      setLoadingAccounts(true);
      try {
        const [accountsRes, diagnosticsRes] = await Promise.allSettled([
          api.get(`/integrations/${activeIntegration.id}/accounts`),
          api.get(`/integrations/${activeIntegration.id}/diagnostics`)
        ]);

        if (accountsRes.status === 'fulfilled') {
          const nextAccounts = accountsRes.value.data.accounts ?? [];
          setAccounts(nextAccounts);
          if (nextAccounts.length > 0) {
            setSelectedAccountId(String(savedAccount || nextAccounts[0].id));
          }
        } else if (savedAccount) {
          setAccounts([{ id: savedAccount, name: `Saved account ${savedAccount}` }]);
          setSelectedAccountId(savedAccount);
          setAccountsError('Provider account lookup is unavailable. Using saved paper account metadata.');
        } else {
          setAccountsError(apiMessage(accountsRes.reason, 'Unable to load accounts for this integration.'));
        }

        if (diagnosticsRes.status === 'fulfilled') {
          const health = diagnosticsRes.value.data?.diagnostics?.health?.status ?? diagnosticsRes.value.data?.status;
          setProviderHealth(String(health ?? 'Unknown'));
        } else {
          setProviderHealth('Unavailable');
        }
      } finally {
        setLoadingAccounts(false);
      }
    };

    loadAccountsAndDiagnostics();
  }, [activeIntegration?.id]);

  const contractOptions = useMemo(() => {
    if (contracts.length > 0) return contracts;
    if (contractsError) return [];
    return DEFAULT_CONTRACTS.map(symbol => ({ symbol, name: symbol } as Contract));
  }, [contracts, contractsError]);

  useEffect(() => {
    if (contractOptions.length === 0) return;
    const symbols = contractOptions.map(contractSymbol).filter(Boolean);
    if (!symbols.includes(selectedSymbol)) {
      setSelectedSymbol(symbols[0]);
    }
  }, [contractOptions, selectedSymbol]);

  useEffect(() => {
    if (countdown <= 0 || sessionState !== 'Running') return;
    const timer = setInterval(() => setCountdown(prev => (prev > 0 ? prev - 1 : 0)), 1000);
    return () => clearInterval(timer);
  }, [countdown, sessionState]);

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, pendingTrade]);

  const isFallbackContracts =
    !contractsError && !loadingContracts && (contractsSource === 'fallback' || contracts.length === 0);

  const selectedIntegrationRecord = integrations.find(integration => integration.id === activeIntegration?.id);
  const gateByCode = new Map((launchGate?.gates ?? []).map(gate => [gate.code, gate]));
  const opsByCode = new Map((opsStatus?.readiness_checklist ?? []).map(item => [item.code, item]));
  const activeKillSwitch = killSwitches.find(item => item.active);
  const scopedPaperAccount = paperAccounts.find(
    account =>
      (!activeIntegration?.id || account.integration_id === activeIntegration.id) &&
      (!selectedAccountId || account.account_id === selectedAccountId)
  );

  const readinessItems: ReadinessItem[] = [
    {
      label: 'Broker integration',
      ready: Boolean(activeIntegration),
      detail: activeIntegration ? `${activeIntegration.display_name} (${activeIntegration.provider})` : 'Select an integration.',
      blocksPaper: true
    },
    {
      label: 'Credentials',
      ready: Boolean(selectedIntegrationRecord?.has_credentials),
      detail: selectedIntegrationRecord?.has_credentials
        ? 'Credentials are stored for the selected integration.'
        : 'Credentials are missing or integration metadata is unavailable.',
      blocksPaper: false
    },
    {
      label: 'Account',
      ready: Boolean(selectedAccountId),
      detail: selectedAccountId || 'Select an account.',
      blocksPaper: true
    },
    {
      label: 'Contract',
      ready: Boolean(selectedSymbol) && !contractsError && !isFallbackContracts,
      detail: contractsError
        ? contractsError
        : isFallbackContracts
          ? 'Fallback symbols are paper-only and not provider validated.'
          : selectedSymbol,
      blocksPaper: true
    },
    {
      label: 'Market data',
      ready: !contractsError && !isFallbackContracts && providerHealth !== 'Unavailable',
      detail: contractsError || (isFallbackContracts ? 'Provider contract data is not validated.' : 'Provider contract lookup is available.'),
      blocksPaper: true
    },
    {
      label: 'Beta access',
      ready: betaStatus?.beta_access_active === true,
      detail:
        betaStatus?.beta_access_active === true
          ? `Invite-only beta access active via ${betaStatus.beta_access.source ?? 'approval'}.`
          : betaStatus?.blockers.find(blocker => blocker.code === 'beta_access_required')?.detail ??
            'Redeem an invite or wait for beta approval.',
      blocksPaper: true
    },
    {
      label: 'Legal documents',
      ready: legalStatus?.all_required_accepted === true,
      detail:
        legalStatus?.all_required_accepted === true
          ? 'Terms, privacy, and paper-risk disclosure are current.'
          : legalStatus?.blockers?.[0]?.detail ?? 'Accept current beta legal documents before paper sessions.',
      blocksPaper: true
    },
    {
      label: 'Mode',
      ready: true,
      detail: 'Paper only. Live trading is disabled.',
      blocksPaper: false
    },
    {
      label: 'Provider status',
      ready: providerHealth.toLowerCase() === 'ok' || providerHealth === 'Unchecked',
      detail: providerHealth,
      blocksPaper: true
    },
    {
      label: 'Risk policy',
      ready: Boolean(riskSettings?.enabled),
      detail: riskSettings
        ? `Max qty ${riskSettings.max_quantity}, max contracts ${riskSettings.max_contracts}, live enabled: ${riskSettings.live_trading_enabled ? 'yes' : 'no'}`
        : gateByCode.get('risk_settings_exist')?.detail ?? 'Risk settings have not loaded.',
      blocksPaper: true
    },
    {
      label: 'Kill switch',
      ready: !activeKillSwitch && gateByCode.get('kill_switch_clear')?.passed !== false,
      detail: activeKillSwitch?.reason ?? gateByCode.get('kill_switch_clear')?.detail ?? 'No active kill switch reported.',
      blocksPaper: true
    },
    {
      label: 'Paper ledger',
      ready: Boolean(scopedPaperAccount) || gateByCode.get('paper_ledger_exists')?.passed === true,
      detail: scopedPaperAccount
        ? `Equity ${scopedPaperAccount.equity.toFixed(2)}, buying power ${scopedPaperAccount.buying_power.toFixed(2)}`
        : gateByCode.get('paper_ledger_exists')?.detail ?? 'No scoped paper ledger snapshot yet.',
      blocksPaper: false
    },
    {
      label: 'Order lifecycle',
      ready: opsByCode.get('order_lifecycle')?.passed !== false,
      detail: opsByCode.get('order_lifecycle')?.detail ?? 'Paper order lifecycle endpoints are available.',
      blocksPaper: false
    },
    {
      label: 'Reconciliation',
      ready: gateByCode.get('broker_reconciliation_clear')?.passed !== false,
      detail: gateByCode.get('broker_reconciliation_clear')?.detail ?? 'No reconciliation lock reported.',
      blocksPaper: true
    },
    {
      label: 'Acknowledgement',
      ready: gateByCode.get('legal_risk_acknowledgement_current')?.passed === true,
      detail: gateByCode.get('legal_risk_acknowledgement_current')?.detail ?? 'Current scoped acknowledgement is missing.',
      blocksPaper: false
    },
    {
      label: 'Migrations',
      ready: opsByCode.get('migrations')?.passed !== false && gateByCode.get('production_config_valid')?.passed !== false,
      detail: opsByCode.get('migrations')?.detail ?? gateByCode.get('production_config_valid')?.detail ?? 'Migration status unavailable outside production.',
      blocksPaper: false
    }
  ];

  const blockers = readinessItems.filter(item => !item.ready && item.blocksPaper);
  const liveBlockers = readinessItems.filter(item => !item.ready);
  const canStartPaperSession = blockers.length === 0 && !loadingAccounts && !loadingContracts;

  const startStream = async () => {
    if (!canStartPaperSession) {
      setStatusMessage(`Resolve setup first: ${blockers.map(item => item.label).join(', ')}`);
      return;
    }

    eventSourceRef.current?.close();
    eventSourceRef.current = null;

    let sessionId = '';
    try {
      const sessionRes = await api.post('/scheduler/bot-sessions', {
        symbol: selectedSymbol,
        buy_threshold: buyThreshold ?? 30,
        sell_threshold: sellThreshold ?? 70,
        auto_trade: autoTrade,
        quantity,
        interval_seconds: intervalSeconds,
        bar_interval_minutes: Number(resolution) || 1,
        integration_id: activeIntegration?.id,
        account_id: selectedAccountId,
        trading_mode: 'paper'
      });
      sessionId = sessionRes.data.session_id;
      setStatusMessage('Paper strategy session created.');
      refreshTradingState();
    } catch (err) {
      console.error('Failed to create bot session', err);
      setStatusMessage(apiMessage(err, 'Unable to create a paper bot session.'));
      setSessionState('Error');
      return;
    }

    const streamParams = new URLSearchParams({
      session_id: sessionId,
      symbol: selectedSymbol,
      buy_threshold: String(buyThreshold ?? 30),
      sell_threshold: String(sellThreshold ?? 70),
      auto_trade: String(autoTrade),
      quantity: String(quantity),
      interval_seconds: String(intervalSeconds),
      integration_id: String(activeIntegration?.id)
    });
    const es = new EventSource(`${API_BASE_URL}/scheduler/run-bot?${streamParams.toString()}`, {
      withCredentials: true
    });
    eventSourceRef.current = es;
    setLogs([]);
    setPendingTrade(null);
    setSessionState('Running');
    setCountdown(intervalSeconds);

    es.onopen = () => setConnectionStatus('connected');
    es.onmessage = e => {
      const msg = e.data;
      try {
        const obj = JSON.parse(msg);
        if (obj.type === 'prompt') {
          setPendingTrade(obj);
          return;
        }
      } catch {
        // Non-JSON bot log line.
      }
      setLogs(prev => [...prev, msg].slice(-200));
      if (msg.includes('Fetching data')) {
        setCountdown(intervalSeconds);
      }
      if (msg.includes('Paper trade response')) {
        refreshTradingState();
      }
    };
    es.onerror = err => {
      console.error('EventSource failed:', err);
      setSessionState('Error');
      setConnectionStatus('disconnected');
      setStatusMessage('Paper bot stream disconnected.');
      es.close();
      eventSourceRef.current = null;
    };
  };

  const stopStream = () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    api.post('/scheduler/stop-bot').catch(err => console.error('Failed to stop bot', err));
    setSessionState('Idle');
    setCountdown(0);
    setStatusMessage('Paper session stopped.');
  };

  const activateEmergencyStop = async () => {
    stopStream();
    try {
      await api.post('/risk/kill-switches', {
        integration_id: activeIntegration?.id,
        account_id: selectedAccountId || undefined,
        reason: 'Emergency stop activated from dashboard.'
      });
      setStatusMessage('Emergency stop is active. New paper orders are blocked for this scope.');
      await refreshReadinessState();
    } catch (err) {
      setStatusMessage(apiMessage(err, 'Unable to activate emergency stop.'));
    }
  };

  const logout = async () => {
    stopStream();
    await api.post('/auth/logout').catch(() => undefined);
    navigate('/', { replace: true, state: { loggedOut: true } });
  };

  const approveTrade = () => {
    if (!pendingTrade) return;
    api
      .post('/scheduler/execute-trade', {
        ...pendingTrade,
        integration_id: activeIntegration?.id,
        account_id: selectedAccountId,
        trading_mode: 'paper'
      })
      .then(res => {
      setLatestOrder(res.data);
      setLogs(prev => [...prev, 'Paper trade filled. No live order was placed.']);
      refreshTradingState();
      refreshReadinessState();
      })
      .catch(err => {
        console.error('Manual trade failed', err);
        setLogs(prev => [...prev, apiMessage(err, 'Manual paper trade failed.')]);
      });
    setPendingTrade(null);
  };

  const runAnalysis = () => {
    if (!analysisStart || !analysisEnd) {
      setAnalysisError('Please select a start and end time.');
      return;
    }
    setAnalysisError('');
    setAnalysisStatus('Loading market structure...');
    api
      .post('/analysis/market-analysis', {
        symbol: selectedSymbol,
        resolution,
        start: unixFromLocal(analysisStart),
        end: unixFromLocal(analysisEnd)
      })
      .then(res => {
        setAnalysisResult(res.data);
        setAnalysisStatus('');
      })
      .catch(err => {
        console.error('Market analysis failed', err);
        setAnalysisStatus('');
        setAnalysisError(apiMessage(err, 'Unable to fetch analysis.'));
      });
  };

  const runBacktest = () => {
    if (!analysisStart || !analysisEnd) {
      setBacktestError('Please select a start and end time.');
      return;
    }
    setBacktestError('');
    setBacktestStatus('Running backtest...');
    api
      .post('/analysis/backtest', {
        symbol: selectedSymbol,
        resolution,
        start: unixFromLocal(analysisStart),
        end: unixFromLocal(analysisEnd),
        buy_threshold: buyThreshold,
        sell_threshold: sellThreshold
      })
      .then(res => {
        setBacktestResult(res.data);
        setBacktestStatus('');
      })
      .catch(err => {
        console.error('Backtest failed', err);
        setBacktestStatus('');
        setBacktestError(apiMessage(err, 'Unable to run backtest.'));
      });
  };

  const sessionSummary = {
    mode: autoTrade ? 'Paper automation' : 'Paper signal-only',
    symbol: `${selectedSymbol} - ${RESOLUTION_LABELS[resolution] || resolution}`,
    latestLog: logs[logs.length - 1] ?? 'Waiting for paper-session activity.'
  };

  return (
    <div className="dashboard-shell">
      <header className="topbar">
        <div className="topbar-left">
          <div>
            <p className="eyebrow">Trading workspace</p>
            <div className="app-title">Paper Trading Control</div>
          </div>
          <span className="pill warning">Live disabled</span>
        </div>
        <div className="topbar-center">
          <span className="badge">{sessionSummary.symbol}</span>
        </div>
        <div className="topbar-right">
          <div className="topbar-meta">
            <p className="tiny muted">Logged in</p>
            <strong>{user?.username ?? '-'}</strong>
          </div>
          <div className="topbar-meta">
            <p className="tiny muted">Session</p>
            <span className={`status-dot ${sessionState.toLowerCase()}`}>{sessionState}</span>
          </div>
          <div className="topbar-actions">
            <Link to="/integrations" className="ghost compact">
              Integrations
            </Link>
            <button type="button" className="ghost compact" onClick={() => setTheme(prev => (prev === 'dark' ? 'light' : 'dark'))}>
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
            <button type="button" className="ghost compact" onClick={logout}>
              Log out
            </button>
          </div>
        </div>
      </header>

      <div className="mode-banner">
        <div>
          <p className="eyebrow">Execution mode</p>
          <h2>Paper trading only</h2>
        </div>
        <p className="muted">
          Live order routing remains disabled by backend safety gates. Paper fills are simulated and do not
          represent guaranteed live performance.
        </p>
      </div>

      <div className="layout">
        <aside className="panel card">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Onboarding</p>
              <h2>Readiness</h2>
            </div>
            <span className={canStartPaperSession ? 'pill status success' : 'pill warning'}>
              {canStartPaperSession ? 'Ready' : 'Blocked'}
            </span>
          </div>

          {integrations.length === 0 && (
            <div className="inline-alert warning">
              Add a broker integration before starting a paper session.
            </div>
          )}
          {statusMessage && <div className="inline-alert" role="status" aria-live="polite">{statusMessage}</div>}
          {readinessError && <div className="inline-alert warning" role="alert">{readinessError}</div>}

          <div className="legal-panel" aria-label="Invite-only beta access status">
            <div className="panel-header compact-header">
              <div>
                <p className="eyebrow">Beta access</p>
                <strong>{betaStatus?.beta_access.status ?? 'Unknown'}</strong>
              </div>
              <span className={betaStatus?.beta_access_active ? 'pill status success' : 'pill warning'}>
                {betaStatus?.beta_access_active ? 'Approved' : 'Invite required'}
              </span>
            </div>
            <p className="muted tiny">
              Paper beta access is invite-only. Approval does not enable live trading or billing.
            </p>
          </div>

          <div className="subscription-panel" aria-label="Subscription and entitlement status">
            <div className="panel-header compact-header">
              <div>
                <p className="eyebrow">Subscription</p>
                <strong>{subscriptionStatus?.subscription?.plan_code ?? 'Checking'}</strong>
              </div>
              <span className="pill warning">Billing disabled</span>
            </div>
            <p className="muted tiny">
              Paper beta access is free during invite-only beta. Checkout and payment collection are disabled.
            </p>
            <div className="simple-list compact-list">
              <div className="list-row">
                <span>Billing</span>
                <strong>{subscriptionStatus?.billing.checkout_enabled ? 'Available' : 'Unavailable'}</strong>
              </div>
              <div className="list-row">
                <span>Live trading</span>
                <strong>{subscriptionStatus?.live_trading_enabled ? 'Enabled' : 'Disabled'}</strong>
              </div>
              <div className="list-row">
                <span>Entitlements</span>
                <strong>{subscriptionStatus?.entitlements.length ?? 0}</strong>
              </div>
            </div>
            <div className="readiness-list" aria-label="Feature gates">
              {(subscriptionStatus?.feature_gates ?? []).map(gate => (
                <div className="readiness-item" key={gate.feature_code}>
                  <span className={gate.allowed ? 'check good' : 'check blocked'}>
                    {gate.allowed ? 'OK' : 'No'}
                  </span>
                  <div>
                    <strong>{gate.feature_code.replaceAll('_', ' ')}</strong>
                    <p className="tiny muted">{gate.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="legal-panel" aria-label="Legal acceptance status">
            <div className="panel-header compact-header">
              <div>
                <p className="eyebrow">Beta legal</p>
                <strong>{legalStatus?.all_required_accepted ? 'Accepted' : 'Required'}</strong>
              </div>
              <span className={legalStatus?.all_required_accepted ? 'pill status success' : 'pill warning'}>
                {legalStatus?.all_required_accepted ? 'Current' : 'Action needed'}
              </span>
            </div>
            <p className="muted tiny">
              Terms, privacy, and paper-trading risk disclosure are required before paper beta workflows.
              Live trading remains disabled.
            </p>
            <div className="simple-list compact-list">
              {(legalStatus?.documents ?? []).map(document => (
                <div className="list-row" key={`${document.document_type}:${document.version}`}>
                  <span>{document.title}</span>
                  <strong>{document.accepted ? 'Accepted' : document.version}</strong>
                </div>
              ))}
            </div>
            {!legalStatus?.all_required_accepted && (
              <button
                type="button"
                className="primary"
                onClick={acceptRequiredLegalDocuments}
                disabled={legalBusy || !legalStatus}
              >
                {legalBusy ? 'Recording...' : 'Accept required documents'}
              </button>
            )}
          </div>

          <div className="demo-panel">
            <div>
              <p className="eyebrow">Investor demo</p>
              <strong>{demoStatus?.seeded ? 'Demo data loaded' : 'Paper-only package'}</strong>
              <p className="muted tiny">
                {demoStatus?.disclaimer ??
                  'Demo mode uses simulated paper orders only. Live trading is disabled.'}
              </p>
            </div>
            <div className="button-row">
              <button type="button" className="ghost compact" onClick={seedDemoPackage} disabled={demoBusy}>
                Load demo
              </button>
              <button type="button" className="ghost compact" onClick={resetDemoPackage} disabled={demoBusy || !demoStatus?.seeded}>
                Reset
              </button>
            </div>
          </div>

          {demoStatus?.seeded && (
            <div className="simple-list compact-list">
              <div className="list-row">
                <span>Demo account</span>
                <strong>{demoStatus.demo_account_id}</strong>
              </div>
              <div className="list-row">
                <span>Paper orders</span>
                <strong>{demoStatus.counts.paper_orders}</strong>
              </div>
              <div className="list-row">
                <span>Live status</span>
                <strong>{demoStatus.live_trading_enabled ? 'Enabled' : 'Disabled'}</strong>
              </div>
            </div>
          )}

          <div className="readiness-summary" role="status" aria-live="polite">
            <strong>{launchGate?.live_trading_available ? 'Live gate passed' : 'Live gate blocked'}</strong>
            <p className="tiny muted">
              {launchGate?.live_trading_blocked_reason ??
                `${liveBlockers.length} readiness item${liveBlockers.length === 1 ? '' : 's'} need attention. Live trading remains disabled.`}
            </p>
          </div>

          <div className="readiness-list" aria-label="Live-readiness checklist">
            {readinessItems.map(item => (
              <div className="readiness-item" key={item.label}>
                <span className={item.ready ? 'check good' : 'check blocked'} aria-label={`${item.label}: ${item.ready ? 'ready' : 'blocked'}`}>
                  {item.ready ? 'OK' : 'Fix'}
                </span>
                <div>
                  <strong>{item.label}</strong>
                  <p className="tiny muted">{item.detail}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="onboarding-panel" aria-label="Paper beta onboarding checklist">
            <div className="panel-header compact-header">
              <div>
                <p className="eyebrow">Onboarding</p>
                <strong>{onboardingStatus?.required_complete ? 'Required steps complete' : 'Next steps'}</strong>
              </div>
              <span className={onboardingStatus?.required_complete ? 'pill status success' : 'pill warning'}>
                {onboardingStatus?.checklist.filter(item => item.complete).length ?? 0}/
                {onboardingStatus?.checklist.length ?? 0}
              </span>
            </div>
            <div className="readiness-list" aria-label="Paper beta onboarding steps">
              {(onboardingStatus?.checklist ?? []).map(item => (
                <div className="readiness-item" key={item.code}>
                  <span className={item.complete ? 'check good' : 'check blocked'}>
                    {item.complete ? 'OK' : item.required ? 'Req' : 'Todo'}
                  </span>
                  <div>
                    <strong>{item.label}</strong>
                    <p className="tiny muted">{item.detail}</p>
                    {!item.complete &&
                      ['paper_only_reviewed', 'integration_walkthrough_viewed', 'risk_controls_reviewed', 'strategy_setup_reviewed'].includes(item.code) && (
                        <button
                          type="button"
                          className="ghost compact"
                          onClick={() => completeOnboardingMilestone(item.code)}
                        >
                          Mark reviewed
                        </button>
                      )}
                  </div>
                </div>
              ))}
            </div>
            <div className="mini-card">
              <p className="eyebrow">Setup guide</p>
              <ul className="pattern-list">
                {(onboardingStatus?.guidance.integration_walkthrough ?? []).slice(0, 3).map(step => (
                  <li key={step}>{step}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="support-panel" aria-label="Beta support contact">
            <div className="panel-header compact-header">
              <div>
                <p className="eyebrow">Support</p>
                <strong>Contact beta support</strong>
              </div>
            </div>
            <form className="integration-form" onSubmit={submitSupportRequest}>
              <label htmlFor="support-category">Category</label>
              <select
                id="support-category"
                value={supportForm.category}
                onChange={e => setSupportForm({ ...supportForm, category: e.target.value })}
              >
                <option value="paper_session">Paper session</option>
                <option value="integration">Integration</option>
                <option value="risk_controls">Risk controls</option>
                <option value="account_access">Account access</option>
              </select>
              <label htmlFor="support-severity">Severity</label>
              <select
                id="support-severity"
                value={supportForm.severity}
                onChange={e => setSupportForm({ ...supportForm, severity: e.target.value })}
              >
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
              </select>
              <label htmlFor="support-subject">Subject</label>
              <input
                id="support-subject"
                value={supportForm.subject}
                onChange={e => setSupportForm({ ...supportForm, subject: e.target.value })}
                placeholder="Brief summary"
                required
              />
              <label htmlFor="support-message">Message</label>
              <textarea
                id="support-message"
                value={supportForm.message}
                onChange={e => setSupportForm({ ...supportForm, message: e.target.value })}
                placeholder="Describe what happened. Do not include credentials or secrets."
                required
              />
              <button type="submit" className="primary" disabled={supportBusy}>
                {supportBusy ? 'Sending...' : 'Send support request'}
              </button>
            </form>
          </div>

          {helpTopics.length > 0 && (
            <div className="help-panel" aria-label="Beta help topics">
              <div className="panel-header compact-header">
                <div>
                  <p className="eyebrow">Help</p>
                  <strong>Paper beta basics</strong>
                </div>
              </div>
              <div className="simple-list compact-list">
                {helpTopics.slice(0, 4).map(topic => (
                  <div className="list-row" key={topic.slug}>
                    <span>{topic.title}</span>
                    <strong>Read</strong>
                    <p className="tiny muted">{topic.summary}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="button-row">
            <button
              type="button"
              className="ghost danger"
              onClick={activateEmergencyStop}
              disabled={Boolean(activeKillSwitch)}
              aria-label="Activate emergency stop kill switch"
            >
              Emergency stop
            </button>
            <button type="button" className="ghost" onClick={refreshReadinessState}>
              Refresh readiness
            </button>
          </div>

          <div className="control-group">
            <label htmlFor="active-integration">Active integration</label>
            <div className="input-row">
              <select
                id="active-integration"
                value={activeIntegration?.id ?? ''}
                onChange={e => {
                  const nextId = Number(e.target.value);
                  if (nextId) {
                    setActiveIntegrationAndLoadContracts(nextId).catch(err =>
                      setStatusMessage(apiMessage(err, 'Unable to activate integration.'))
                    );
                  }
                }}
              >
                <option value="">Select integration</option>
                {integrations.map(integration => (
                  <option key={integration.id} value={integration.id}>
                    {integration.display_name} - {integration.provider}
                  </option>
                ))}
              </select>
              {activeIntegration && <span className="pill subtle">Active</span>}
            </div>
          </div>

          <div className="control-group">
            <label htmlFor="account-select">Account</label>
            <select
              id="account-select"
              value={selectedAccountId}
              onChange={e => setSelectedAccountId(e.target.value)}
              disabled={!activeIntegration || loadingAccounts || accounts.length === 0}
            >
              <option value="">{loadingAccounts ? 'Loading accounts...' : 'Select account'}</option>
              {accounts.map(account => (
                <option key={String(account.id)} value={String(account.id)}>
                  {account.name ?? account.id}
                </option>
              ))}
            </select>
            {accountsError && <p className="muted tiny">{accountsError}</p>}
          </div>

          <div className="control-group">
            <label htmlFor="contract-select">Contract</label>
            <div className="input-row">
              <select
                id="contract-select"
                value={selectedSymbol}
                onChange={e => setSelectedSymbol(e.target.value)}
                disabled={loadingContracts || contractOptions.length === 0}
              >
                {contractOptions.map(contract => {
                  const symbol = contractSymbol(contract);
                  return (
                    <option key={symbol} value={symbol}>
                      {symbol}
                    </option>
                  );
                })}
              </select>
              {isFallbackContracts && <span className="pill warning">Fallback</span>}
            </div>
            {loadingContracts && <p className="muted tiny">Loading provider contracts...</p>}
            {contractsError && <p className="muted tiny">{contractsError}</p>}
            {isFallbackContracts && (
              <p className="muted tiny">Fallback symbols are for paper/demo orientation only.</p>
            )}
          </div>

          <div className="control-inline">
            <div>
              <label>Resolution</label>
              <select value={resolution} onChange={e => setResolution(e.target.value)}>
                <option value="1">1 minute</option>
                <option value="3">3 minute</option>
                <option value="5">5 minute</option>
                <option value="15">15 minute</option>
                <option value="60">1 hour</option>
                <option value="D">Daily</option>
              </select>
            </div>
            <div>
              <label>Quantity</label>
              <input type="number" min={1} value={quantity} onChange={e => setQuantity(Number(e.target.value))} />
            </div>
          </div>

          <div className="control-inline">
            <div>
              <label>Buy RSI below</label>
              <input type="number" value={buyThreshold} onChange={e => setBuyThreshold(Number(e.target.value))} />
            </div>
            <div>
              <label>Sell RSI above</label>
              <input type="number" value={sellThreshold} onChange={e => setSellThreshold(Number(e.target.value))} />
            </div>
          </div>

          <div className="mode-toggle">
            <button type="button" className={!autoTrade ? 'active' : ''} onClick={() => setAutoTrade(false)}>
              Signal only
            </button>
            <button type="button" className={autoTrade ? 'active' : ''} onClick={() => setAutoTrade(true)}>
              Paper auto
            </button>
          </div>

          <div className="control-group">
            <label>Interval seconds</label>
            <input
              type="number"
              min={10}
              value={intervalSeconds}
              onChange={e => setIntervalSeconds(Number(e.target.value))}
            />
          </div>

          <div className="button-row">
            <button type="button" className="primary" onClick={startStream} disabled={!canStartPaperSession || sessionState === 'Running'}>
              Start paper session
            </button>
            <button type="button" className="ghost" onClick={stopStream}>
              Stop
            </button>
          </div>
        </aside>

        <main className="main">
          <section className="status-grid">
            <div className="card compact">
              <p className="tiny muted">Personal-device executor</p>
              <strong>
                {deviceTelemetry?.installations[0]?.freshness === 'delayed_read_only'
                  ? 'Reporting'
                  : deviceTelemetry?.installations[0]?.freshness === 'stale'
                    ? 'Stale'
                    : 'No telemetry'}
              </strong>
              <p className="tiny muted">Delayed/read-only · controls stay on the device</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">Mode</p>
              <strong>{sessionSummary.mode}</strong>
              <p className="tiny muted">Live trading unavailable</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">Bot status</p>
              <strong>{sessionState}</strong>
              <p className="tiny muted">{sessionState === 'Running' ? `Next cycle in ${countdown}s` : sessionSummary.latestLog}</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">Paper orders</p>
              <strong>{strategyMetrics?.orders ?? 0}</strong>
              <p className="tiny muted">{openOrders.length} open</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">Risk policy</p>
              <strong>{riskSettings?.enabled ? 'Active' : 'Missing'}</strong>
              <p className="tiny muted">Max qty {riskSettings?.max_quantity ?? '-'}</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">Kill switch</p>
              <strong>{activeKillSwitch ? 'Active' : 'Clear'}</strong>
              <p className="tiny muted">{activeKillSwitch?.reason ?? 'No active stop state'}</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">Paper equity</p>
              <strong>{scopedPaperAccount ? scopedPaperAccount.equity.toFixed(2) : '-'}</strong>
              <p className="tiny muted">Buying power {scopedPaperAccount ? scopedPaperAccount.buying_power.toFixed(2) : '-'}</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">Strategy signals</p>
              <strong>{strategyMetrics?.signals ?? 0}</strong>
              <p className="tiny muted">{strategyMetrics?.suppressed_signals ?? 0} suppressed</p>
            </div>
          </section>

          <section className="grid">
            <div className="card activity">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Paper session</p>
                  <h2>Activity</h2>
                </div>
                <span className={`status-dot ${connectionStatus}`}>{connectionStatus}</span>
              </div>

              {pendingTrade && (
                <div className="prompt-banner">
                  <div>
                    <p className="tiny muted">Manual approval required</p>
                    <h3>
                      {pendingTrade.side} {pendingTrade.quantity} {pendingTrade.symbol} @ {pendingTrade.price}
                    </h3>
                    <p className="muted tiny">Approval creates a paper order only.</p>
                  </div>
                  <div className="prompt-actions">
                    <button className="primary" onClick={approveTrade}>
                      Approve paper trade
                    </button>
                    <button className="ghost" onClick={() => setPendingTrade(null)}>
                      Reject
                    </button>
                  </div>
                </div>
              )}

              <div className="log-view" ref={logContainerRef}>
                {logs.length === 0 ? (
                  <p className="muted tiny">No session events yet.</p>
                ) : (
                  logs.map((log, idx) => (
                    <div key={`log-${idx}`} className="log-line">
                      <span className="log-dot" />
                      <span>{log}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="card">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Execution</p>
                  <h2>Paper Orders</h2>
                </div>
                <button type="button" className="ghost compact" onClick={refreshTradingState}>
                  Refresh
                </button>
              </div>
              {latestOrder?.order && (
                <div className="mini-card">
                  <p className="tiny muted">Latest filled paper order</p>
                  <strong>
                    {latestOrder.order.side} {latestOrder.order.quantity} {latestOrder.order.symbol}
                  </strong>
                  <p className="tiny muted">Status: {latestOrder.order.status}</p>
                </div>
              )}
              {openOrders.length === 0 ? (
                <p className="muted tiny">No open paper orders.</p>
              ) : (
                <div className="simple-list">
                  {openOrders.map(order => (
                    <div className="list-row" key={order.order?.id}>
                      <span>{order.order?.symbol}</span>
                      <strong>{order.order?.status}</strong>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="card">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Portfolio</p>
                  <h2>Paper Positions</h2>
                </div>
                <span className="pill subtle">{positions.length}</span>
              </div>
              {positions.length === 0 ? (
                <p className="muted tiny">No paper positions yet.</p>
              ) : (
                <div className="simple-list">
                  {positions.map(position => (
                    <div className="list-row" key={position.id}>
                      <span>{position.symbol}</span>
                      <strong>{position.quantity}</strong>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="card">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Strategy</p>
                  <h2>Signals & Metrics</h2>
                </div>
                <span className="pill subtle">rsi-threshold-v1</span>
              </div>
              <div className="stat-row">
                <div className="stat">
                  <p className="tiny muted">Executed</p>
                  <strong>{strategyMetrics?.executed_signals ?? 0}</strong>
                </div>
                <div className="stat">
                  <p className="tiny muted">Win / Loss</p>
                  <strong>
                    {strategyMetrics?.wins ?? 0} / {strategyMetrics?.losses ?? 0}
                  </strong>
                </div>
                <div className="stat">
                  <p className="tiny muted">Realized PnL</p>
                  <strong>{(strategyMetrics?.realized_pnl ?? 0).toFixed(2)}</strong>
                </div>
              </div>
              {strategySignals.length === 0 ? (
                <p className="muted tiny">No strategy signals recorded yet.</p>
              ) : (
                <div className="simple-list compact-list">
                  {strategySignals.slice(0, 5).map(signal => (
                    <div className="list-row" key={signal.id}>
                      <span>
                        {signal.symbol} {signal.signal}
                      </span>
                      <strong>{signal.status}</strong>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="grid">
            <div className="card">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Structure insights</p>
                  <h2>Market Analysis</h2>
                </div>
                <span className="pill subtle">{selectedSymbol}</span>
              </div>
              <div className="control-inline">
                <div>
                  <label htmlFor="analysis-start">Start</label>
                  <input id="analysis-start" type="datetime-local" value={analysisStart} onChange={e => setAnalysisStart(e.target.value)} />
                </div>
                <div>
                  <label htmlFor="analysis-end">End</label>
                  <input id="analysis-end" type="datetime-local" value={analysisEnd} onChange={e => setAnalysisEnd(e.target.value)} />
                </div>
              </div>
              <div className="button-row spaced">
                <button className="primary" onClick={runAnalysis}>
                  Run analysis
                </button>
                {analysisStatus && <p className="muted tiny">{analysisStatus}</p>}
              </div>
              {analysisError && <p className="inline-alert danger">{analysisError}</p>}
              {analysisResult ? (
                <div className="stat-row">
                  <div className="stat">
                    <p className="tiny muted">Divergences</p>
                    <strong>{analysisResult.divergences.length}</strong>
                  </div>
                  <div className="stat">
                    <p className="tiny muted">Liquidity sweeps</p>
                    <strong>{analysisResult.liquidity_sweeps.length}</strong>
                  </div>
                  <div className="stat">
                    <p className="tiny muted">Fair value gaps</p>
                    <strong>{analysisResult.fair_value_gaps.length}</strong>
                  </div>
                  <div className="stat">
                    <p className="tiny muted">Supply/Demand zones</p>
                    <strong>{analysisResult.supply_demand_zones.length}</strong>
                  </div>
                </div>
              ) : (
                <p className="muted tiny">Run analysis to review recent market structure.</p>
              )}
            </div>

            <div className="card">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Simulation</p>
                  <h2>Backtest Snapshot</h2>
                </div>
                <span className="pill warning">Not predictive</span>
              </div>
              <div className="button-row spaced">
                <button className="primary" onClick={runBacktest}>
                  Run backtest
                </button>
                {backtestStatus && <p className="muted tiny">{backtestStatus}</p>}
              </div>
              {backtestError && <p className="inline-alert danger">{backtestError}</p>}
              {backtestResult ? (
                <div className="backtest-results">
                  <div className="stat-row">
                    <div className="stat">
                      <p className="tiny muted">Total PnL</p>
                      <strong className={backtestResult.total_pnl >= 0 ? 'positive' : 'negative'}>
                        {backtestResult.total_pnl.toFixed(2)}
                      </strong>
                    </div>
                    <div className="stat">
                      <p className="tiny muted">Trades</p>
                      <strong>{backtestResult.trades.length}</strong>
                    </div>
                    <div className="stat">
                      <p className="tiny muted">Signals</p>
                      <strong>{(backtestResult.signals?.buy ?? 0) + (backtestResult.signals?.sell ?? 0)}</strong>
                    </div>
                  </div>
                  {backtestResult.assumptions?.length ? (
                    <p className="muted tiny">{backtestResult.assumptions[0]}</p>
                  ) : null}
                </div>
              ) : (
                <p className="muted tiny">Backtests are paper simulations and do not guarantee live performance.</p>
              )}
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}

export default Dashboard;
