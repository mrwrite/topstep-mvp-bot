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

type SessionState = 'Idle' | 'Live' | 'Error';

type User = { username: string };

type Integration = {
  id: number;
  display_name: string;
  provider: string;
  status: string;
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
};

const unixFromLocal = (value: string) => Math.floor(new Date(value).getTime() / 1000);

const renderPatternList = (
  title: string,
  data: any[],
  formatter: (item: any) => string
) => (
  <div className="mini-card">
    <div className="pattern-header">
      <h4>{title}</h4>
      <span className="pill subtle">{data.length}</span>
    </div>
    {data.length === 0 ? (
      <p className="muted tiny">No matches in range.</p>
    ) : (
      <ul className="pattern-list">
        {data.map((item, idx) => (
          <li key={`${title}-${idx}`}>
            <span className="bullet" />
            <span>{formatter(item)}</span>
          </li>
        ))}
      </ul>
    )}
  </div>
);

const EquitySparkline = ({ data }: { data: Array<{ time: string; equity: number }> }) => {
  const gradientId = useMemo(() => `equity-${Math.random().toString(36).slice(2)}`, []);

  if (!data.length) return null;

  const values = data.map(point => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = data
    .map((point, idx) => {
      const x = (idx / (data.length - 1 || 1)) * 100;
      const y = 100 - ((point.equity - min) / range) * 100;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  const areaPoints = `${points} 100,100 0,100`;

  return (
    <svg className="sparkline" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Equity curve">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={areaPoints} fill={`url(#${gradientId})`} />
      <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="2" />
    </svg>
  );
};

function Dashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string>(DEFAULT_CONTRACTS[0]);
  const [resolution, setResolution] = useState<string>('1');
  const [buyThreshold, setBuyThreshold] = useState<number>(30);
  const [sellThreshold, setSellThreshold] = useState<number>(70);
  const [autoTrade, setAutoTrade] = useState<boolean>(false);
  const [quantity, setQuantity] = useState<number>(1);
  const [intervalSeconds, setIntervalSeconds] = useState<number>(60);
  const [logs, setLogs] = useState<string[]>([]);
  const [pendingTrade, setPendingTrade] = useState<TradePrompt | null>(null);
  const [countdown, setCountdown] = useState<number>(0);
  const [sessionState, setSessionState] = useState<SessionState>('Idle');
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected'>(
    'disconnected'
  );
  const [analysisStart, setAnalysisStart] = useState<string>(() => {
    const d = new Date(Date.now() - 24 * 60 * 60 * 1000);
    return d.toISOString().slice(0, 16);
  });
  const [analysisEnd, setAnalysisEnd] = useState<string>(() => {
    const d = new Date();
    return d.toISOString().slice(0, 16);
  });
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
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

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
        const buy = res.data.buy_threshold ?? 30;
        const sell = res.data.sell_threshold ?? 70;
        setBuyThreshold(buy);
        setSellThreshold(sell);
      })
      .catch(() => {
        setBuyThreshold(30);
        setSellThreshold(70);
      });

    api
      .get('/integrations')
      .then(res => setIntegrations(res.data ?? []))
      .catch(err => console.error('Failed to load integrations', err));
  }, [navigate]);

  const contractOptions = useMemo(() => {
    if (contracts.length > 0) {
      return contracts;
    }
    if (contractsError) {
      return [];
    }
    return DEFAULT_CONTRACTS.map(symbol => ({ symbol, name: symbol } as Contract));
  }, [contracts, contractsError]);

  const contractNotice = useMemo(() => {
    if (contractsError) {
      return contractsError;
    }
    if (!loadingContracts && (contractsSource === 'fallback' || contracts.length === 0)) {
      return 'Using fallback contracts until a market data integration is configured.';
    }
    return '';
  }, [contractsError, contractsSource, contracts.length, loadingContracts]);

  const isFallbackContracts = useMemo(
    () =>
      !contractsError &&
      !loadingContracts &&
      (contractsSource === 'fallback' || contracts.length === 0),
    [contractsError, contractsSource, contracts.length, loadingContracts]
  );

  useEffect(() => {
    if (contractOptions.length === 0) {
      return;
    }
    const contractSymbols = contractOptions.map(contract =>
      contract.symbol ?? contract.name ?? String(contract.id ?? '')
    );
    if (!contractSymbols.includes(selectedSymbol)) {
      setSelectedSymbol(contractSymbols[0]);
    }
  }, [contractOptions, selectedSymbol]);

  useEffect(() => {
    if (countdown <= 0 || sessionState !== 'Live') return;
    const timer = setInterval(() => {
      setCountdown(prev => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [countdown, sessionState]);

  useEffect(() => {
    if (!logContainerRef.current) return;
    logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
  }, [logs, pendingTrade]);

  const startStream = async () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const token = localStorage.getItem('token');
    if (!token) {
      setLogs(prev => [...prev, 'Missing access token. Please sign in again.']);
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
        integration_id: activeIntegration?.id ?? undefined,
        trading_mode: 'paper',
      });
      sessionId = sessionRes.data.session_id;
    } catch (err) {
      console.error('Failed to create bot session', err);
      setLogs(prev => [...prev, 'Unable to create a paper bot session.']);
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
    });
    if (activeIntegration?.id) {
      streamParams.set('integration_id', String(activeIntegration.id));
    }
    const url = `${API_BASE_URL}/scheduler/run-bot?${streamParams.toString()}`;

    const es = new EventSource(url);
    eventSourceRef.current = es;
    setLogs([]);
    setPendingTrade(null);
    setSessionState('Live');
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
        // ignore
      }

      setLogs(prev => {
        const next = [...prev, msg];
        return next.slice(-200);
      });

      if (msg.includes('⏰ Fetching data')) {
        setCountdown(intervalSeconds);
      }
    };

    es.onerror = err => {
      console.error('EventSource failed:', err);
      setSessionState('Error');
      setConnectionStatus('disconnected');
      es.close();
      eventSourceRef.current = null;
    };
  };

  const stopStream = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    api.post('/scheduler/stop-bot').catch(err => console.error('Failed to stop bot', err));
    setSessionState('Idle');
    setCountdown(0);
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
        integration_id: activeIntegration?.id ?? undefined,
        trading_mode: 'paper',
      })
      .then(() => setLogs(prev => [...prev, 'Paper trade simulated']))
      .catch(err => {
        console.error('Manual trade failed', err);
        setLogs(prev => [...prev, 'Manual trade failed']);
      });
    setPendingTrade(null);
  };

  const backtestEquity = useMemo(() => {
    if (!backtestResult) return [] as Array<{ time: string; equity: number }>;
    let running = 0;
    return backtestResult.trades
      .slice()
      .sort((a, b) => new Date(a.exit_time).getTime() - new Date(b.exit_time).getTime())
      .map(trade => {
        running += trade.pnl;
        return { time: new Date(trade.exit_time).toLocaleString(), equity: running };
      });
  }, [backtestResult]);

  const sessionSummary = {
    mode: autoTrade ? 'Auto Trade' : 'Signal Only',
    latestLog: logs[logs.length - 1] ?? 'Waiting for activity...',
    symbol: `${selectedSymbol} · ${RESOLUTION_LABELS[resolution] || resolution}`,
  };

  const marketDataUnsupported =
    contractsError &&
    (contractsError.toLowerCase().includes("doesn't provide contracts") ||
      contractsError.toLowerCase().includes('does not support market data'));

  return (
    <div className="dashboard-shell">
      <header className="topbar">
        <div className="topbar-left">
          <div>
            <p className="eyebrow">Trading Bot</p>
            <div className="app-title">Trading Orchestrator</div>
          </div>
          <span className="pill subtle">demo</span>
        </div>
        <div className="topbar-center">
          <span className="badge">{sessionSummary.symbol}</span>
        </div>
        <div className="topbar-right">
          <div className="topbar-meta">
            <p className="tiny muted">Logged in</p>
            <strong>{user?.username ?? '—'}</strong>
          </div>
          <div className="topbar-meta">
            <p className="tiny muted">Session</p>
            <span className={`status-dot ${sessionState.toLowerCase()}`}>
              {sessionState}
            </span>
          </div>
          <div className="topbar-meta">
            <p className="tiny muted">Backend</p>
            <span className={`status-dot ${connectionStatus}`}>
              {connectionStatus === 'connected' ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <div className="topbar-actions">
            <Link to="/integrations" className="ghost compact">
              Integrations
            </Link>
            <button
              type="button"
              className="ghost compact"
              onClick={() => setTheme(prev => (prev === 'dark' ? 'light' : 'dark'))}
            >
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
            <button type="button" className="ghost compact" onClick={logout}>
              Log out
            </button>
          </div>
        </div>
      </header>

      <div className="layout">
        <aside className="panel card">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Strategy & Session</p>
              <h2>Control Center</h2>
            </div>
            <span className="pill">RSI</span>
          </div>

          <div className="control-group">
            <label>Active Integration</label>
            <div className="input-row">
              <select
                value={activeIntegration?.id ?? ''}
                onChange={e => {
                  const nextId = Number(e.target.value);
                  if (nextId) {
                    setActiveIntegrationAndLoadContracts(nextId).catch(err =>
                      console.error('Failed to activate integration', err)
                    );
                  }
                }}
              >
                <option value="">Select integration</option>
                {integrations.map(integration => (
                  <option key={integration.id} value={integration.id}>
                    {integration.display_name} · {integration.provider}
                  </option>
                ))}
              </select>
              {activeIntegration && <span className="pill subtle">Active</span>}
            </div>
            {activeIntegration ? (
              <p className="muted tiny">
                Using {activeIntegration.display_name} for selected broker context.
              </p>
            ) : (
              <p className="muted tiny">Select a broker integration for paper sessions.</p>
            )}
            {!activeIntegration && (
              <div className="inline-alert warning">
                No active integration. Go to Integrations to activate one.
              </div>
            )}
          </div>

          <div className="control-group">
            <label>Symbol</label>
            <div className="input-row">
              <select
                value={selectedSymbol}
                onChange={e => setSelectedSymbol(e.target.value)}
                disabled={loadingContracts || contractOptions.length === 0}
              >
                {contractOptions.map(contract => {
                  const symbol =
                    contract.symbol ?? contract.name ?? String(contract.id ?? '');
                  return (
                    <option key={symbol} value={symbol}>
                      {symbol}
                    </option>
                  );
                })}
              </select>
              {isFallbackContracts && <span className="pill warning">Fallback</span>}
            </div>
            {contractNotice && <p className="muted tiny">{contractNotice}</p>}
            {marketDataUnsupported && (
              <p className="muted tiny">
                This integration doesn’t provide contracts/instruments. Switch integrations to
                load contracts.
              </p>
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
              <input
                type="number"
                min={1}
                value={quantity}
                onChange={e => setQuantity(Number(e.target.value))}
              />
            </div>
            <div>
              <label>Interval (s)</label>
              <input
                type="number"
                min={10}
                value={intervalSeconds}
                onChange={e => setIntervalSeconds(Number(e.target.value))}
              />
            </div>
          </div>

          <div className="control-inline">
            <div>
              <label>Buy RSI below</label>
              <input
                type="number"
                value={buyThreshold}
                onChange={e => setBuyThreshold(Number(e.target.value))}
              />
            </div>
            <div>
              <label>Sell RSI above</label>
              <input
                type="number"
                value={sellThreshold}
                onChange={e => setSellThreshold(Number(e.target.value))}
              />
            </div>
          </div>

          <div className="mode-toggle">
            <button
              type="button"
              className={!autoTrade ? 'active' : ''}
              onClick={() => {
                setAutoTrade(false);
                api.post('/scheduler/update-config', { auto_trade: false });
              }}
            >
              Signal Only
            </button>
            <button
              type="button"
              className={autoTrade ? 'active' : ''}
              onClick={() => {
                setAutoTrade(true);
                api.post('/scheduler/update-config', { auto_trade: true, trading_mode: 'paper' });
              }}
            >
              Auto Trade
            </button>
          </div>

          <div className="button-row">
            <button className="primary" onClick={startStream}>
              Start Session
            </button>
            <button className="ghost" onClick={stopStream}>
              Stop Session
            </button>
          </div>

          <div className="button-row spaced">
            <button
              className="ghost"
              onClick={() => {
                api
                  .put(
                    '/auth/rules',
                    { buy_threshold: buyThreshold, sell_threshold: sellThreshold },
                    { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
                  )
                  .catch(err => console.error('Failed to update rules', err));
                api
                  .post('/scheduler/update-config', {
                    buy_threshold: buyThreshold,
                    sell_threshold: sellThreshold,
                    quantity,
                    interval_seconds: intervalSeconds,
                    trading_mode: 'paper',
                  })
                  .catch(err => console.error('Failed to sync bot rules', err));
              }}
            >
              Save Config
            </button>
            <div className="countdown">Next run in {countdown || 0}s</div>
          </div>

          <div className="divider" />
          <div className="process">
            <div>
              <p className="eyebrow">Pipeline</p>
              <h4>Data → Analysis → Execution</h4>
            </div>
            <ul className="process-list">
              <li>
                <span className="pill subtle">Data</span>
                Signal + broker feeds
              </li>
              <li>
                <span className="pill subtle">RSI + Structure</span>
                Divergences, sweeps, FVGs
              </li>
              <li>
                <span className="pill subtle">Execution</span>
                {autoTrade ? 'Automated entries' : 'Manual approvals'}
              </li>
            </ul>
          </div>
        </aside>

        <main className="main">
          <div className="status-grid">
            <div className="card compact">
              <p className="tiny muted">Mode</p>
              <h3>{sessionSummary.mode}</h3>
              <p className="muted tiny">{sessionSummary.latestLog}</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">Session State</p>
              <h3 className={`status-dot ${sessionState.toLowerCase()}`}>{sessionState}</h3>
              <p className="muted tiny">Countdown: {countdown || 0}s</p>
            </div>
            <div className="card compact">
              <p className="tiny muted">RSI thresholds</p>
              <h3>
                {buyThreshold} / {sellThreshold}
              </h3>
              <p className="muted tiny">Qty {quantity}</p>
            </div>
          </div>

          <div className="grid">
            <section className="card activity">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Live telemetry</p>
                  <h2>Activity Stream & Trade Prompts</h2>
                </div>
                <span className="pill subtle">{logs.length} events</span>
              </div>

              {pendingTrade && (
                <div className="prompt-banner">
                  <div>
                    <p className="tiny muted">Manual approval required</p>
                    <h3>
                      {pendingTrade.side} {pendingTrade.quantity} {pendingTrade.symbol} @{' '}
                      {pendingTrade.price}
                    </h3>
                    <p className="muted tiny">Mode: {sessionSummary.mode}</p>
                  </div>
                  <div className="prompt-actions">
                    <button className="primary" onClick={approveTrade}>
                      Approve trade
                    </button>
                    <button className="ghost" onClick={() => setPendingTrade(null)}>
                      Reject
                    </button>
                  </div>
                </div>
              )}

              <div className="log-view" ref={logContainerRef}>
                {logs.length === 0 ? (
                  <p className="muted tiny">Waiting for events…</p>
                ) : (
                  logs.map((log, idx) => (
                    <div key={`log-${idx}`} className="log-line">
                      <span className="log-dot" />
                      <span>{log}</span>
                    </div>
                  ))
                )}
              </div>
            </section>

            <section className="card analysis">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Structure insights</p>
                  <h2>Market Structure Analysis</h2>
                </div>
                <span className="pill subtle">{selectedSymbol}</span>
              </div>

              <div className="control-inline">
                <div>
                  <label htmlFor="analysis-start">Start</label>
                  <input
                    id="analysis-start"
                    type="datetime-local"
                    value={analysisStart}
                    onChange={e => setAnalysisStart(e.target.value)}
                  />
                </div>
                <div>
                  <label htmlFor="analysis-end">End</label>
                  <input
                    id="analysis-end"
                    type="datetime-local"
                    value={analysisEnd}
                    onChange={e => setAnalysisEnd(e.target.value)}
                  />
                </div>
              </div>
              <div className="button-row spaced">
                <button
                  className="primary"
                  onClick={() => {
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
                        end: unixFromLocal(analysisEnd),
                      })
                      .then(res => {
                        setAnalysisResult(res.data);
                        setAnalysisStatus('');
                      })
                      .catch(err => {
                        console.error('Market analysis failed', err);
                        setAnalysisStatus('');
                        setAnalysisError('Unable to fetch analysis.');
                      });
                  }}
                >
                  Run Analysis
                </button>
                {analysisStatus && <p className="muted tiny">{analysisStatus}</p>}
              </div>
              {analysisError && <p className="inline-alert danger">{analysisError}</p>}

              {analysisResult && (
                <div className="analysis-results">
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
                    <div className="stat">
                      <p className="tiny muted">Supply/Demand zones</p>
                      <strong>{analysisResult.supply_demand_zones.length}</strong>
                    </div>
                    <div className="stat">
                      <p className="tiny muted">Supply/Demand zones</p>
                      <strong>{analysisResult.supply_demand_zones.length}</strong>
                    </div>
                  </div>
                  <div className="pattern-grid">
                    {renderPatternList(
                      'Divergence Signals',
                      analysisResult.divergences,
                      item =>
                        `${item.divergence_type} between ${
                          item.price1?.toFixed?.(2) ?? item.price1
                        } and ${item.price2?.toFixed?.(2) ?? item.price2}`
                    )}
                    {renderPatternList(
                      'Liquidity Sweeps',
                      analysisResult.liquidity_sweeps,
                      item => `${item.side} sweep at ${item.sweep_price?.toFixed?.(2) ?? item.sweep_price}`
                    )}
                    {renderPatternList(
                      'Fair Value Gaps',
                      analysisResult.fair_value_gaps,
                      item =>
                        `${item.direction} gap ${
                          item.start?.toFixed?.(2) ?? item.start
                        } → ${item.end?.toFixed?.(2) ?? item.end}`
                    )}
                    {renderPatternList(
                      'Supply / Demand Zones',
                      analysisResult.supply_demand_zones,
                      item =>
                        `${item.type} ${item.lower?.toFixed?.(2) ?? item.lower} - ${
                          item.upper?.toFixed?.(2) ?? item.upper
                        }`
                    )}
                  </div>
                  <div className="pattern-grid">
                    {renderPatternList(
                      'Divergence Signals',
                      analysisResult.divergences,
                      item =>
                        `${item.divergence_type} between ${
                          item.price1?.toFixed?.(2) ?? item.price1
                        } and ${item.price2?.toFixed?.(2) ?? item.price2}`
                    )}
                    {renderPatternList(
                      'Liquidity Sweeps',
                      analysisResult.liquidity_sweeps,
                      item => `${item.side} sweep at ${item.sweep_price?.toFixed?.(2) ?? item.sweep_price}`
                    )}
                    {renderPatternList(
                      'Fair Value Gaps',
                      analysisResult.fair_value_gaps,
                      item =>
                        `${item.direction} gap ${
                          item.start?.toFixed?.(2) ?? item.start
                        } → ${item.end?.toFixed?.(2) ?? item.end}`
                    )}
                    {renderPatternList(
                      'Supply / Demand Zones',
                      analysisResult.supply_demand_zones,
                      item =>
                        `${item.type} ${item.lower?.toFixed?.(2) ?? item.lower} - ${
                          item.upper?.toFixed?.(2) ?? item.upper
                        }`
                    )}
                  </div>
                  <div className="pattern-grid">
                    {renderPatternList(
                      'Divergence Signals',
                      analysisResult.divergences,
                      item =>
                        `${item.divergence_type} between ${
                          item.price1?.toFixed?.(2) ?? item.price1
                        } and ${item.price2?.toFixed?.(2) ?? item.price2}`
                    )}
                    {renderPatternList(
                      'Liquidity Sweeps',
                      analysisResult.liquidity_sweeps,
                      item => `${item.side} sweep at ${item.sweep_price?.toFixed?.(2) ?? item.sweep_price}`
                    )}
                    {renderPatternList(
                      'Fair Value Gaps',
                      analysisResult.fair_value_gaps,
                      item =>
                        `${item.direction} gap ${
                          item.start?.toFixed?.(2) ?? item.start
                        } → ${item.end?.toFixed?.(2) ?? item.end}`
                    )}
                    {renderPatternList(
                      'Supply / Demand Zones',
                      analysisResult.supply_demand_zones,
                      item =>
                        `${item.type} ${item.lower?.toFixed?.(2) ?? item.lower} - ${
                          item.upper?.toFixed?.(2) ?? item.upper
                        }`
                    )}
                  </div>
                  <div className="pattern-grid">
                    {renderPatternList(
                      'Divergence Signals',
                      analysisResult.divergences,
                      item =>
                        `${item.divergence_type} between ${
                          item.price1?.toFixed?.(2) ?? item.price1
                        } and ${item.price2?.toFixed?.(2) ?? item.price2}`
                    )}
                    {renderPatternList(
                      'Liquidity Sweeps',
                      analysisResult.liquidity_sweeps,
                      item => `${item.side} sweep at ${item.sweep_price?.toFixed?.(2) ?? item.sweep_price}`
                    )}
                    {renderPatternList(
                      'Fair Value Gaps',
                      analysisResult.fair_value_gaps,
                      item =>
                        `${item.direction} gap ${
                          item.start?.toFixed?.(2) ?? item.start
                        } → ${item.end?.toFixed?.(2) ?? item.end}`
                    )}
                    {renderPatternList(
                      'Supply / Demand Zones',
                      analysisResult.supply_demand_zones,
                      item =>
                        `${item.type} ${item.lower?.toFixed?.(2) ?? item.lower} - ${
                          item.upper?.toFixed?.(2) ?? item.upper
                        }`
                    )}
                  </div>
                </div>
              )}
            </section>

            <section className="card backtest">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Performance simulation</p>
                  <h2>RSI Strategy Backtest</h2>
                </div>
                <span className="pill subtle">Aligned w/ live config</span>
              </div>

              <div className="control-inline">
                <div>
                  <label htmlFor="backtest-start">Start</label>
                  <input
                    id="backtest-start"
                    type="datetime-local"
                    value={analysisStart}
                    onChange={e => setAnalysisStart(e.target.value)}
                  />
                </div>
                <div>
                  <label htmlFor="backtest-end">End</label>
                  <input
                    id="backtest-end"
                    type="datetime-local"
                    value={analysisEnd}
                    onChange={e => setAnalysisEnd(e.target.value)}
                  />
                </div>
                <span className="pill subtle">Aligned w/ live config</span>
              </div>
              <div className="button-row spaced">
                <button
                  className="primary"
                  onClick={() => {
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
                        sell_threshold: sellThreshold,
                      })
                      .then(res => {
                        setBacktestResult(res.data);
                        setBacktestStatus('');
                      })
                      .catch(err => {
                        console.error('Backtest failed', err);
                        setBacktestStatus('');
                        setBacktestError('Unable to run backtest.');
                      });
                  }}
                >
                  Run Backtest
                </button>
                {backtestStatus && <p className="muted tiny">{backtestStatus}</p>}
              </div>
              {backtestError && <p className="inline-alert danger">{backtestError}</p>}

              {backtestResult && (
                <div className="backtest-results">
                  <div className="stat-row">
                    <div className="stat">
                      <p className="tiny muted">Total PnL</p>
                      <strong className={backtestResult.total_pnl >= 0 ? 'positive' : 'negative'}>
                        {backtestResult.total_pnl.toFixed(2)}
                      </strong>
                      <p className="tiny muted">Across {backtestResult.trades.length} trades</p>
                    </div>
                    <div className="stat">
                      <p className="tiny muted">Win rate</p>
                      <strong>
                        {backtestResult.wins + backtestResult.losses === 0
                          ? '—'
                          : `${Math.round(
                              (backtestResult.wins / (backtestResult.wins + backtestResult.losses)) * 100
                            )}%`}
                      </strong>
                      <p className="tiny muted">
                        {backtestResult.wins} wins · {backtestResult.losses} losses
                      </p>
                    </div>
                    <div className="stat">
                      <p className="tiny muted">Signals</p>
                      <div className="chip-row">
                        <span className="pill subtle">Buy {backtestResult.signals?.buy ?? 0}</span>
                        <span className="pill subtle">Sell {backtestResult.signals?.sell ?? 0}</span>
                        <span className="pill subtle">Hold {backtestResult.signals?.hold ?? 0}</span>
                      </div>
                    </div>
                    <div className="stat">
                      <p className="tiny muted">Patterns</p>
                      <div className="chip-row">
                        <span className="pill subtle">Div {backtestResult.patterns?.divergences ?? 0}</span>
                        <span className="pill subtle">Sweeps {backtestResult.patterns?.liquidity_sweeps ?? 0}</span>
                        <span className="pill subtle">FVG {backtestResult.patterns?.fair_value_gaps ?? 0}</span>
                        <span className="pill subtle">S/D {backtestResult.patterns?.supply_demand_zones ?? 0}</span>
                      </div>
                    </div>
                  </div>

                  {backtestEquity.length > 0 && (
                    <div className="chart-block">
                      <div className="chart-header">
                        <p className="tiny muted">Equity Curve</p>
                        <span className="pill subtle">{backtestEquity.length} points</span>
                      </div>
                      <EquitySparkline data={backtestEquity} />
                    </div>
                  )}

                  <div>
                    <div className="table-header">
                      <h4>Trades</h4>
                      <span className="pill subtle">{backtestResult.trades.length}</span>
                    </div>
                    {backtestResult.trades.length === 0 ? (
                      <p className="muted tiny">No trades executed in this window.</p>
                    ) : (
                      <table className="trade-table">
                        <thead>
                          <tr>
                            <th>Side</th>
                            <th>Entry</th>
                            <th>Exit</th>
                            <th>Entry Price</th>
                            <th>Exit Price</th>
                            <th>PnL</th>
                          </tr>
                        </thead>
                        <tbody>
                          {backtestResult.trades.map((trade, idx) => (
                            <tr key={`trade-${idx}`}>
                              <td>{trade.side}</td>
                              <td>{new Date(trade.entry_time).toLocaleString()}</td>
                              <td>{new Date(trade.exit_time).toLocaleString()}</td>
                              <td>{trade.entry_price.toFixed(2)}</td>
                              <td>{trade.exit_price.toFixed(2)}</td>
                              <td className={trade.pnl >= 0 ? 'positive' : 'negative'}>
                                {trade.pnl.toFixed(2)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
              )}
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}

export default Dashboard;
