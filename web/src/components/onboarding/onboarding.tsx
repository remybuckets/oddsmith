"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useApp } from "@/components/app/app-context";
import { Logo } from "@/components/app/brand";
import { useMe } from "@/components/app/member-gate";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { asApiError } from "@/lib/api/errors";

function AgeDeclaration() {
  const { api } = useApp();
  const { setMe } = useMe();
  const [isAgreed, setIsAgreed] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setIsSaving(true);
    setError(null);
    try {
      setMe(await api.confirmAge());
    } catch (cause) {
      setError(asApiError(cause).message);
      setIsSaving(false);
    }
  }

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Before you start</h1>
      <p>Oddsmith is for adults in Great Britain. It gives information about football betting, not advice.</p>
      <label className="flex items-start gap-3">
        <Checkbox
          checked={isAgreed}
          onCheckedChange={(checked) => setIsAgreed(checked)}
          aria-labelledby="age-declaration"
          className="mt-0.5"
        />
        <span id="age-declaration">
          I&apos;m 18 or over and I accept the{" "}
          <Link href="/terms" className="underline underline-offset-2">
            terms
          </Link>
          .
        </span>
      </label>
      {error && (
        <p role="alert" className="text-sm text-card-red">
          {error}
        </p>
      )}
      <Button size="lg" disabled={!isAgreed || isSaving} onClick={confirm}>
        Continue
      </Button>
    </section>
  );
}

function HowItWorks() {
  const { me } = useMe();
  const router = useRouter();
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">How Oddsmith works</h1>
      <ul className="flex list-disc flex-col gap-2 pl-5">
        <li>Ask about Premier League players, teams, injuries and odds.</li>
        <li>Every number comes with its source and how fresh it is.</li>
        <li>Value views are estimates, not advice. Only bet what you can afford to lose.</li>
        <li>{`You get ${me.usage.daily_limit} questions a day.`}</li>
      </ul>
      <Button size="lg" onClick={() => router.push("/chat")}>
        Start asking
      </Button>
    </section>
  );
}

export function Onboarding() {
  const { me } = useMe();
  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-6 p-6">
      <Logo />
      {me.age_confirmed ? <HowItWorks /> : <AgeDeclaration />}
    </main>
  );
}
