"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";
import { useApp } from "@/components/app/app-context";

const LINK_FAILED = "That sign-in link didn't work. It may have expired or been used already.";

/** Supabase puts link errors in the query (PKCE) or the hash (implicit flow). */
function readLinkError(): string | null {
  const query = new URLSearchParams(window.location.search);
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const description = query.get("error_description") ?? hash.get("error_description");
  if (description) return description;
  return query.has("error") || hash.has("error") ? LINK_FAILED : null;
}

const noSubscription = () => () => {};

export function AuthCallback() {
  const { auth } = useApp();
  const router = useRouter();
  const linkError = useSyncExternalStore(noSubscription, readLinkError, () => null);

  useEffect(() => {
    if (auth.session) router.replace("/chat");
  }, [auth.session, router]);

  const error = linkError ?? (!auth.isLoading && !auth.session ? LINK_FAILED : null);
  if (!error) {
    return (
      <p role="status" className="text-muted-foreground">
        Signing you in…
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p role="alert">{error}</p>
      <Link href="/sign-in" className="text-primary underline underline-offset-2">
        Send a new link
      </Link>
    </div>
  );
}
