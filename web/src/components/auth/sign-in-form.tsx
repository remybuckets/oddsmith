"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import { useApp } from "@/components/app/app-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const INVALID_EMAIL = "Enter a valid email address.";
const SEND_FAILED = "We couldn't send the link. Wait a minute and try again.";

export function SignInForm() {
  const { auth } = useApp();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);

  useEffect(() => {
    if (!auth.isLoading && auth.session) router.replace("/chat");
  }, [auth.isLoading, auth.session, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const address = email.trim();
    if (!EMAIL_PATTERN.test(address)) {
      setError(INVALID_EMAIL);
      return;
    }
    setError(null);
    setIsSending(true);
    try {
      await auth.sendMagicLink(address);
      setSentTo(address);
    } catch {
      setError(SEND_FAILED);
    } finally {
      setIsSending(false);
    }
  }

  if (sentTo) {
    return (
      <div className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold">Check your email</h1>
        <p>{`We've sent a sign-in link to ${sentTo}. Open it on this device to carry on.`}</p>
        <Button variant="link" className="self-start px-0" onClick={() => setSentTo(null)}>
          Use a different email
        </Button>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={handleSubmit} className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <p className="text-muted-foreground">No password: we&apos;ll email you a link.</p>
      <div className="flex flex-col gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          aria-invalid={error === INVALID_EMAIL}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-card-red">
          {error}
        </p>
      )}
      <Button type="submit" size="lg" disabled={isSending}>
        Email me a sign-in link
      </Button>
    </form>
  );
}
