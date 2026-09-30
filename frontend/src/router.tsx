import {
  AnchorHTMLAttributes,
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState
} from 'react';

type NavigateOptions = { replace?: boolean; state?: unknown };
type LocationValue = { pathname: string; state: unknown };
type RouterValue = LocationValue & {
  navigate: (to: string, options?: NavigateOptions) => void;
};

const RouterContext = createContext<RouterValue | null>(null);

export function RouterProvider({ children }: { children: ReactNode }) {
  const readLocation = (): LocationValue => ({
    pathname: window.location.pathname,
    state: window.history.state
  });
  const [location, setLocation] = useState<LocationValue>(readLocation);
  useEffect(() => {
    const update = () => setLocation(readLocation());
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, []);
  const navigate = useCallback((to: string, options: NavigateOptions = {}) => {
    const method = options.replace ? 'replaceState' : 'pushState';
    window.history[method](options.state ?? null, '', to);
    setLocation(readLocation());
  }, []);
  const value = useMemo(() => ({ ...location, navigate }), [location, navigate]);
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

function useRouter() {
  const value = useContext(RouterContext);
  if (!value) throw new Error('RouterProvider is required.');
  return value;
}

export function useNavigate() {
  return useRouter().navigate;
}

export function useLocation() {
  const { pathname, state } = useRouter();
  return { pathname, state };
}

export function Navigate({ to, replace = false }: { to: string; replace?: boolean }) {
  const navigate = useNavigate();
  useEffect(() => navigate(to, { replace }), [navigate, replace, to]);
  return null;
}

export function Link({
  to,
  onClick,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const navigate = useNavigate();
  return (
    <a
      {...props}
      href={to}
      onClick={event => {
        onClick?.(event);
        if (!event.defaultPrevented && event.button === 0 && !event.metaKey && !event.ctrlKey) {
          event.preventDefault();
          navigate(to);
        }
      }}
    />
  );
}
