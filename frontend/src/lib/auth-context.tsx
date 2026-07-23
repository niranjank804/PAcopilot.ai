"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { apiRequest, registerTokenAccessors } from "@/lib/api-client";

export interface AuthUser {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  organization_id: string;
}

interface Tokens {
  accessToken: string;
  refreshToken: string;
}

interface TokenResponseBody {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  loginWithGoogle: (googleIdToken: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const STORAGE_KEY = "pa-copilot-tokens";

function readStoredTokens(): Tokens | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.localStorage.getItem(STORAGE_KEY);

  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as Tokens;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const tokensRef = useRef<Tokens | null>(null);

  const applyTokens = useCallback((next: Tokens | null) => {
    tokensRef.current = next;

    if (typeof window === "undefined") {
      return;
    }

    if (next) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    registerTokenAccessors({
      getAccessToken: () => tokensRef.current?.accessToken ?? null,
      getRefreshToken: () => tokensRef.current?.refreshToken ?? null,
      setTokens: (next) =>
        applyTokens(
          next
            ? { accessToken: next.accessToken, refreshToken: next.refreshToken }
            : null,
        ),
    });
  }, [applyTokens]);

  useEffect(() => {
    const stored = readStoredTokens();

    if (!stored) {
      // Nothing to hydrate from localStorage — this must run client-side
      // only (SSR always starts with isLoading=true to match hydration),
      // so this synchronous setState is the earliest point it's safe to
      // resolve the "no session" case.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setIsLoading(false);
      return;
    }

    applyTokens(stored);

    apiRequest<AuthUser>("/auth/me")
      .then((me) => setUser(me))
      .catch(() => {
        applyTokens(null);
        setUser(null);
      })
      .finally(() => setIsLoading(false));
    // Only run once on mount — applyTokens is stable (useCallback, empty deps).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const data = await apiRequest<TokenResponseBody>("/auth/login", {
        method: "POST",
        body: { username, password },
        skipAuth: true,
      });

      applyTokens({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      });

      const me = await apiRequest<AuthUser>("/auth/me");
      setUser(me);
    },
    [applyTokens],
  );

  const loginWithGoogle = useCallback(
    async (googleIdToken: string) => {
      const data = await apiRequest<TokenResponseBody>("/auth/google", {
        method: "POST",
        body: { id_token: googleIdToken },
        skipAuth: true,
      });

      applyTokens({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      });

      const me = await apiRequest<AuthUser>("/auth/me");
      setUser(me);
    },
    [applyTokens],
  );

  const logout = useCallback(() => {
    applyTokens(null);
    setUser(null);
  }, [applyTokens]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: Boolean(user),
        login,
        loginWithGoogle,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);

  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }

  return ctx;
}
