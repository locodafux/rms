import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, getAccessToken, setTokens } from "./api";
import type { SchemaResponse, User } from "./types";

interface AuthCtx {
  user: User | null;
  schema: SchemaResponse | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshSchema: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>(null as any);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [loading, setLoading] = useState(true);

  async function bootstrap() {
    if (!getAccessToken()) {
      setLoading(false);
      return;
    }
    try {
      const me = await api.me();
      setUser(me);
      if (me.role) setSchema(await api.schema());
    } catch {
      setTokens(null, null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(email: string, password: string) {
    await api.login(email, password);
    const me = await api.me();
    setUser(me);
    if (me.role) setSchema(await api.schema());
  }

  function logout() {
    setTokens(null, null);
    setUser(null);
    setSchema(null);
  }

  async function refreshSchema() {
    setSchema(await api.schema());
  }

  return (
    <Ctx.Provider value={{ user, schema, loading, login, logout, refreshSchema }}>
      {children}
    </Ctx.Provider>
  );
}
