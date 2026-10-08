"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { describeApiError } from "@/lib/api/error-display";
import { type ApiRequestError, asApiError } from "@/lib/api/errors";
import type { Me } from "@/lib/api/types";
import { formatUkDateTime } from "@/lib/format/time";
import { useApp } from "./app-context";
import { Logo, SupportLinks } from "./brand";

interface MeContextValue {
  me: Me;
  setMe: (me: Me) => void;
}

const MeContext = createContext<MeContextValue | null>(null);

export function useMe(): MeContextValue {
  const value = useContext(MeContext);
  if (!value) throw new Error("useMe must be used inside <MemberGate>");
  return value;
}

export function isOnBreak(me: Me, now: number = Date.now()): boolean {
  return me.self_excluded_until !== null && Date.parse(me.self_excluded_until) > now;
}

export function Loading() {
  return (
    <div role="status" aria-label="Loading" className="grid flex-1 place-items-center p-8">
      <span className="size-6 animate-spin rounded-full border-2 border-muted border-t-primary" />
    </div>
  );
}

export function BreakScreen({ until }: { until: string }) {
  return (
    <main className="mx-auto flex max-w-md flex-1 flex-col justify-center gap-4 p-6">
      <Logo />
      <h1 className="text-2xl font-semibold">You&apos;re on a break</h1>
      <p>{`Chat is paused until ${formatUkDateTime(until)}. A break can't be shortened.`}</p>
      <SupportLinks />
      <Link href="/settings" className="text-sm text-muted-foreground underline underline-offset-2">
        Settings
      </Link>
    </main>
  );
}

function GateError({ error }: { error: ApiRequestError }) {
  const display = describeApiError(error);
  return (
    <main className="mx-auto flex max-w-md flex-1 flex-col justify-center gap-2 p-6">
      <h1 className="text-lg font-semibold">{display.title}</h1>
      <p role="alert">{display.body}</p>
    </main>
  );
}

interface MemberGateProps {
  children: ReactNode;
  /** Onboarding runs before the 18+ declaration exists. */
  allowUnconfirmed?: boolean;
  /** Settings stay open during a break (e.g. to delete the account). */
  allowOnBreak?: boolean;
}

/** Signed in → profile loaded → 18+ confirmed → not on a break; otherwise redirect or explain. */
export function MemberGate({ children, allowUnconfirmed = false, allowOnBreak = false }: MemberGateProps) {
  const { api, auth } = useApp();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<ApiRequestError | null>(null);
  const hasSession = auth.session !== null;
  const needsOnboarding = me !== null && !me.age_confirmed && !allowUnconfirmed;

  useEffect(() => {
    if (auth.isLoading) return;
    if (!hasSession) {
      router.replace("/sign-in");
      return;
    }
    let isCurrent = true;
    api
      .getMe()
      .then((profile) => isCurrent && setMe(profile))
      .catch((cause: unknown) => {
        if (!isCurrent) return;
        const apiError = asApiError(cause);
        const { redirectTo } = describeApiError(apiError);
        if (redirectTo) router.replace(redirectTo);
        else setError(apiError);
      });
    return () => {
      isCurrent = false;
    };
  }, [api, auth.isLoading, hasSession, router]);

  useEffect(() => {
    if (needsOnboarding) router.replace("/onboarding");
  }, [needsOnboarding, router]);

  const value = useMemo(() => (me ? { me, setMe } : null), [me]);

  if (error) return <GateError error={error} />;
  if (!value || needsOnboarding) return <Loading />;
  if (!allowOnBreak && isOnBreak(value.me) && value.me.self_excluded_until) {
    return <BreakScreen until={value.me.self_excluded_until} />;
  }
  return <MeContext.Provider value={value}>{children}</MeContext.Provider>;
}
