import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState
} from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ApiError, api } from "./api";
import type { AuthState } from "./types";

type AuthContextValue = {
  auth: AuthState | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const value = await api.me();
      setAuth(value);
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setAuth(null);
      } else {
        setError(caught instanceof Error ? caught.message : "Falha ao carregar sessão");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      const value = await api.login(email, password);
      setAuth(value);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha de autenticação");
      throw caught;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    setAuth(null);
  }, []);

  const value = useMemo(
    () => ({ auth, loading, error, login, logout, refresh }),
    [auth, loading, error, login, logout, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is required");
  return value;
}

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { auth, loading } = useAuth();
  const location = useLocation();
  if (loading) return <main className="centered">Carregando sessão...</main>;
  if (!auth) return <Navigate to="/login" replace state={{ from: location }} />;
  return <>{children}</>;
}
