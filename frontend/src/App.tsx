import { useEffect, useState } from 'react';
import { Navigate, RouterProvider, useLocation } from './router';
import { api } from './api';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Register from './pages/Register';
import Integrations from './pages/Integrations';

function RequireAuth({ children }: { children: JSX.Element }) {
  const [state, setState] = useState<'loading' | 'authenticated' | 'anonymous'>('loading');
  useEffect(() => {
    let active = true;
    api.get('/auth/me')
      .then(() => active && setState('authenticated'))
      .catch(() => active && setState('anonymous'));
    return () => { active = false; };
  }, []);
  if (state === 'loading') return <div className="auth-shell">Checking secure session…</div>;
  if (state === 'anonymous') {
    return <Navigate to="/" replace />;
  }
  return children;
}

export default function App() {
  return <RouterProvider><AppRoutes /></RouterProvider>;
}

function AppRoutes() {
  const { pathname } = useLocation();
  let page: JSX.Element;
  if (pathname === '/') page = <Login />;
  else if (pathname === '/register') page = <Register />;
  else if (pathname === '/dashboard') page = <RequireAuth><Dashboard /></RequireAuth>;
  else if (pathname === '/integrations') page = <RequireAuth><Integrations /></RequireAuth>;
  else page = <Navigate to="/" replace />;
  return (
    page
  );
}
