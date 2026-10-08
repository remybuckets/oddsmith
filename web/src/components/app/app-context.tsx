"use client";

import type { Session as SupabaseSession } from "@supabase/supabase-js";
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { type ApiClient, createApiClient } from "@/lib/api/client";
import { getSupabase } from "@/lib/auth/supabase";
import { getConfig } from "@/lib/config";

export interface Session {
  accessToken: string;
  email: string | null;
}

export interface AuthState {
  session: Session | null;
  isLoading: boolean;
  sendMagicLink: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
}

export interface AppServices {
  api: ApiClient;
  auth: AuthState;
}

export const AppContext = createContext<AppServices | null>(null);

export function useApp(): AppServices {
  const services = useContext(AppContext);
  if (!services) throw new Error("useApp must be used inside <AppProvider>");
  return services;
}

function toSession(session: SupabaseSession | null): Session | null {
  return session ? { accessToken: session.access_token, email: session.user.email ?? null } : null;
}

/** Real services: Supabase Auth in the browser and the API client with its token. */
export function AppProvider({ children }: { children: ReactNode }) {
  const supabase = useMemo(() => getSupabase(), []);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isCurrent = true;
    supabase.auth
      .getSession()
      .then(({ data }) => isCurrent && setSession(toSession(data.session)))
      .finally(() => isCurrent && setIsLoading(false));
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(toSession(next));
      setIsLoading(false);
    });
    return () => {
      isCurrent = false;
      data.subscription.unsubscribe();
    };
  }, [supabase]);

  const api = useMemo(
    () =>
      createApiClient({
        baseUrl: getConfig().apiUrl,
        getAccessToken: async () => (await supabase.auth.getSession()).data.session?.access_token ?? null,
      }),
    [supabase],
  );

  const auth = useMemo<AuthState>(
    () => ({
      session,
      isLoading,
      async sendMagicLink(email) {
        const { error } = await supabase.auth.signInWithOtp({
          email,
          options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
        });
        if (error) throw error;
      },
      async signOut() {
        await supabase.auth.signOut();
      },
    }),
    [session, isLoading, supabase],
  );

  const services = useMemo(() => ({ api, auth }), [api, auth]);
  return <AppContext.Provider value={services}>{children}</AppContext.Provider>;
}
