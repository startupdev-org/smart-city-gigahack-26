"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  AuthUser,
  clearAuth,
  loadAuth,
  saveAuth,
  syncAuthCookie,
} from "@/lib/api";

type AuthState = {
  user: AuthUser | null;
  ready: boolean;
  login: (u: AuthUser) => void;
  logout: () => void;
  setUser: (u: AuthUser | null) => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    syncAuthCookie();
    setUser(loadAuth());
    setReady(true);
  }, []);

  const login = useCallback((u: AuthUser) => {
    saveAuth(u);
    setUser(u);
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, ready, login, logout, setUser }),
    [user, ready, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
