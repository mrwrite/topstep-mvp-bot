import { useEffect, useState, useRef } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';

interface User {
  username: string;
  // Add other properties as needed based on the API response
}

function Dashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [contracts, setContracts] = useState<string[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');
  const [logs, setLogs] = useState<string[]>([]);
  const [buyThreshold, setBuyThreshold] = useState<number>(30);
  const [sellThreshold, setSellThreshold] = useState<number>(70);
  const eventSourceRef = useRef<EventSource | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    axios.get('http://localhost:8000/auth/me', {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
    })
      .then(res => setUser(res.data))
      .catch(err => {
        if (err.response && err.response.status === 401) {
          alert('Session expired. Please log in again.');
          localStorage.removeItem('token');
          navigate('/login');
        } else {
          console.error('An error occurred:', err);
          alert('An error occurred while fetching user data.');
        }
      });

    axios.get('http://localhost:8000/contracts')
      .then(res => {
        setContracts(res.data.contracts);
        if (res.data.contracts.length > 0) {
          setSelectedSymbol(res.data.contracts[0]);
        }
      })
      .catch(err => {
        console.error('Failed to fetch contracts:', err);
        alert('Could not load contracts list.');
      });

    axios.get('http://localhost:8000/auth/rules', {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
    })
      .then(res => {
        // API may return null if the user record predates rule columns
        const buy = res.data.buy_threshold ?? 30;
        const sell = res.data.sell_threshold ?? 70;
        setBuyThreshold(buy);
        setSellThreshold(sell);
      })
      .catch(err => {
        console.error('Failed to fetch rules:', err);
        // fallback to defaults if the request fails
        setBuyThreshold(30);
        setSellThreshold(70);
      });
  }, []);

  return (
    <div className="container">
      <div className="card">
        <h1>Dashboard</h1>
        <p>Welcome {user?.username}</p>
        <div>
          <label htmlFor="contract-select">Contract:</label>
          <select
            id="contract-select"
            value={selectedSymbol}
            onChange={e => setSelectedSymbol(e.target.value)}
          >
            {contracts.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="rule-inputs">
          <div>
            <label htmlFor="buy">Buy RSI below</label>
            <input
              id="buy"
              type="number"
              value={buyThreshold}
              onChange={e => setBuyThreshold(Number(e.target.value))}
            />
          </div>
          <div>
            <label htmlFor="sell">Sell RSI above</label>
            <input
              id="sell"
              type="number"
              value={sellThreshold}
              onChange={e => setSellThreshold(Number(e.target.value))}
            />
          </div>
          <button onClick={() => {
            axios.put('http://localhost:8000/auth/rules', {
              buy_threshold: buyThreshold,
              sell_threshold: sellThreshold
            }, {
              headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
            }).catch(err => console.error('Failed to update rules', err));
          }}>Save Rules</button>
        </div>
        <button onClick={() => {
          if (eventSourceRef.current) {
            eventSourceRef.current.close();
          }
        const url = `http://localhost:8000/scheduler/run-bot?symbol=${encodeURIComponent(selectedSymbol)}&buy_threshold=${buyThreshold ?? 30}&sell_threshold=${sellThreshold ?? 70}`;
        const es = new EventSource(url);
        eventSourceRef.current = es;
        setLogs([]);
        es.onmessage = (e) => {
          setLogs(prev => [...prev, e.data]);
        };
        es.onerror = (err) => {
          console.error('EventSource failed:', err);
          es.close();
        };

        }}>Run Bot</button>
        <pre>
          {logs.join('\n')}
        </pre>
      </div>
    </div>
  );
}

export default Dashboard;
