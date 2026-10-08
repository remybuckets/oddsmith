"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";
import { useApp } from "@/components/app/app-context";
import { Logo, SupportLinks } from "@/components/app/brand";
import { isOnBreak, useMe } from "@/components/app/member-gate";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { asApiError } from "@/lib/api/errors";
import type { BreakDuration } from "@/lib/api/types";
import { formatUkDateTime } from "@/lib/format/time";

const BREAK_OPTIONS: { duration: BreakDuration; label: string; adjective: string }[] = [
  { duration: "24h", label: "24 hours", adjective: "24-hour" },
  { duration: "7d", label: "7 days", adjective: "7-day" },
  { duration: "30d", label: "30 days", adjective: "30-day" },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t pt-5">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="text-sm text-card-red">
      {message}
    </p>
  );
}

function Usage() {
  const { usage } = useMe().me;
  return (
    <Section title="Usage">
      <p>{`${usage.questions_today} of ${usage.daily_limit} questions used today`}</p>
      <p className="text-sm text-muted-foreground">{`Resets ${formatUkDateTime(usage.resets_at)}`}</p>
    </Section>
  );
}

function TakeBreak() {
  const { api } = useApp();
  const { me, setMe } = useMe();
  const [pending, setPending] = useState<(typeof BREAK_OPTIONS)[number] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startBreak(duration: BreakDuration) {
    setPending(null);
    setError(null);
    try {
      setMe(await api.takeBreak(duration));
    } catch (cause) {
      setError(asApiError(cause).message);
    }
  }

  if (isOnBreak(me) && me.self_excluded_until) {
    return (
      <Section title="Take a break">
        <p>{`You're on a break until ${formatUkDateTime(me.self_excluded_until)}. It can't be shortened.`}</p>
      </Section>
    );
  }

  return (
    <Section title="Take a break">
      <p className="text-sm text-muted-foreground">
        Pause chat for a while. Once started, a break can&apos;t be shortened or cancelled.
      </p>
      <div className="flex flex-wrap gap-2">
        {BREAK_OPTIONS.map((option) => (
          <Button key={option.duration} variant="outline" onClick={() => setPending(option)}>
            {option.label}
          </Button>
        ))}
      </div>
      <ErrorText message={error} />
      <AlertDialog open={pending !== null} onOpenChange={(isOpen) => !isOpen && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{`Take a ${pending?.adjective ?? ""} break?`}</AlertDialogTitle>
            <AlertDialogDescription>
              You won&apos;t be able to ask questions until it ends. It can&apos;t be shortened or cancelled.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => pending && startBreak(pending.duration)}>Start break</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Section>
  );
}

function AccountActions() {
  const { api, auth } = useApp();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function signOut() {
    await auth.signOut();
    router.replace("/");
  }

  async function deleteAccount() {
    setError(null);
    try {
      await api.deleteAccount();
      await signOut();
    } catch (cause) {
      setError(asApiError(cause).message);
    }
  }

  return (
    <Section title="Account">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={signOut}>
          Sign out
        </Button>
        <AlertDialog>
          <AlertDialogTrigger render={<Button variant="destructive" />}>Delete account</AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete your account?</AlertDialogTitle>
              <AlertDialogDescription>
                This removes your account, chats and usage for good. It can&apos;t be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={deleteAccount}>
                Delete my account
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
      <ErrorText message={error} />
    </Section>
  );
}

export function SettingsScreen() {
  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col gap-5 p-4">
      <header className="flex items-center justify-between">
        <Logo />
        <Link href="/chat" className="text-sm text-primary underline-offset-2 hover:underline">
          Back to chat
        </Link>
      </header>
      <h1 className="text-2xl font-semibold">Settings</h1>
      <Usage />
      <TakeBreak />
      <Section title="Help">
        <p className="text-sm">Spotted a wrong number? Tap thumbs down on the answer so we can check it.</p>
        <SupportLinks />
      </Section>
      <AccountActions />
    </main>
  );
}
