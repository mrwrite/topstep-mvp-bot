import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
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
    const response = (err as { response?: { data?: { detail?: string } } }).response;
    return response?.data?.detail ?? fallback;
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

  useEffect(() => {
    api
      .get('/auth/me')
      .then(res => {
        setUser(res.data);
        setConnectionStatus('connected');
      })
      .catch(err => {
        if (err.response && err.response.status === 401) {
          localStorage.removeItem('token');
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
  }, [navigate]);

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

  const readinessItems = [
    {
      label: 'Broker integration',
      ready: Boolean(activeIntegration),
      detail: activeIntegration ? `${activeIntegration.display_name} (${activeIntegration.provider})` : 'Select an integration.'
    },
    {
      label: 'Account',
      ready: Boolean(selectedAccountId),
      detail: selectedAccountId || 'Select an account.'
    },
    {
      label: 'Contract',
      ready: Boolean(selectedSymbol) && !contractsError && !isFallbackContracts,
      detail: contractsError
        ? contractsError
        : isFallbackContracts
          ? 'Fallback symbols are paper-only and not provider validated.'
          : selectedSymbol
    },
    {
      label: 'Mode',
      ready: true,
      detail: 'Paper only. Live trading is disabled.'
    },
    {
      label: 'Provider status',
      ready: providerHealth.toLowerCase() === 'ok' || providerHealth === 'Unchecked',
      detail: providerHealth
    },
    {
      label: 'Risk status',
      ready: true,
      detail: 'Defensive Phase 1 guards active; max quantity remains limited.'
    }
  ];

  const blockers = readinessItems.filter(item => !item.ready);
  const canStartPaperSession = blockers.length === 0 && !loadingAccounts && !loadingContracts;

  const startStream = async () => {
    if (!canStartPaperSession) {
      setStatusMessage(`Resolve setup first: ${blockers.map(item => item.label).join(', ')}`);
      return;
    }

    eventSourceRef.current?.close();
    eventSourceRef.current = null;

    const token = localStorage.getItem('token');
    if (!token) {
      setStatusMessage('Missing access token. Please sign in again.');
      setSessionState('Error');
      return;
    }

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
    const es = new EventSource(`${API_BASE_URL}/scheduler/run-bot?${streamParams.toString()}`);
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

  const logout = () => {
    stopStream();
    localStorage.removeItem('token');
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
          {statusMessage && <div className="inline-alert">{statusMessage}</div>}

          <div className="readiness-list">
            {readinessItems.map(item => (
              <div className="readiness-item" key={item.label}>
                <span className={item.ready ? 'check good' : 'check blocked'}>{item.ready ? 'OK' : 'Fix'}</span>
                <div>
                  <strong>{item.label}</strong>
                  <p className="tiny muted">{item.detail}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="control-group">
            <label>Active integration</label>
            <div className="input-row">
              <select
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
            <label>Account</label>
            <select
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
            <label>Contract</label>
            <div className="input-row">
              <select
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
