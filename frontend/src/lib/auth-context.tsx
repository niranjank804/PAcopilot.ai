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

  /** Null until the product tour is finished or dismissed.
   *
   * Server-side so a second device does not replay an introduction the
   * person has already sat through. Optional here because the frontend
   * and backend deploy independently — a browser holding the new bundle
   * can still be talking to an API that predates these fields. */
  onboarding_completed_at?: string | null;
  onboarding_dismissed_at?: string | null;
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
  /** Re-read /auth/me. The user object is state here rather than a
   * React Query cache, so callers that change something about the
   * signed-in user — onboarding, profile — need a way to pull the new
   * value rather than invalidating a key that does not exist. */
  refreshUser: () => Promise<void>;
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

  const refreshUser = useCallback(async () => {
    try {
      setUser(await apiRequest<AuthUser>("/auth/me"));
    } catch {
      // A failed refresh is not a reason to sign someone out — the
      // token may simply be mid-rotation. The stale user stays until
      // something authoritative says otherwise.
    }
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
        refreshUser,
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
