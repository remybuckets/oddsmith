"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useApp } from "@/components/app/app-context";
import { GAMCARE_PHONE, Logo } from "@/components/app/brand";
import { useMe } from "@/components/app/member-gate";
import { Button } from "@/components/ui/button";
import { describeApiError } from "@/lib/api/error-display";
import type { NextFixtures } from "@/lib/api/types";
import { useChat } from "@/lib/chat/use-chat";
import { ChatInput, ErrorBanner, FixtureStrip, SuggestedQuestions, Thread } from "./chat-parts";
import { ConversationsSheet } from "./conversations-sheet";

function useNextFixtures(): NextFixtures | null {
  const { api } = useApp();
  const [next, setNext] = useState<NextFixtures | null>(null);
  useEffect(() => {
    let isCurrent = true;
    // The strip is optional: if it can't load, chat still works, so there's nothing to show.
    api
      .getNextFixtures()
      .then((data) => isCurrent && setNext(data))
      .catch(() => isCurrent && setNext(null));
    return () => {
      isCurrent = false;
    };
  }, [api]);
  return next;
}

export function ChatScreen() {
  const { api } = useApp();
  const { me, setMe } = useMe();
  const router = useRouter();
  const chat = useChat(api);
  const next = useNextFixtures();
  const error = chat.error;
  const presentation = error ? describeApiError(error) : null;
  const questionsLeft = chat.questionsRemaining ?? Math.max(0, me.usage.daily_limit - me.usage.questions_today);

  useEffect(() => {
    if (!error) return;
    const { redirectTo, presentation: kind } = describeApiError(error);
    if (redirectTo) {
      router.replace(redirectTo);
    } else if (kind === "screen") {
      // Reload the profile so the gate shows the break screen; the banner covers a failure.
      api.getMe().then(setMe, () => undefined);
    }
  }, [error, api, router, setMe]);

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-1 border-b px-3 py-2">
        <Logo className="mr-auto" />
        <ConversationsSheet api={api} currentId={chat.conversationId} onSelect={chat.open} />
        <Button variant="ghost" size="sm" onClick={chat.reset}>
          New chat
        </Button>
        <Link href="/settings" className="px-2 text-sm text-muted-foreground hover:text-foreground">
          Settings
        </Link>
      </header>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto py-3">
        {next && <FixtureStrip next={next} onAsk={chat.ask} />}
        <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-4">
          {chat.items.length === 0 && (
            <SuggestedQuestions questions={next?.suggested_questions ?? []} onAsk={chat.ask} />
          )}
          <Thread items={chat.items} onRate={chat.rate} />
        </div>
      </div>

      <footer className="mx-auto flex w-full max-w-2xl flex-col gap-2 border-t px-4 py-3">
        {error && presentation?.presentation !== "redirect" && (
          <ErrorBanner error={error} onDismiss={chat.dismissError} />
        )}
        <ChatInput onSend={chat.ask} isSending={chat.isSending} />
        <p className="flex justify-between text-xs text-muted-foreground">
          <span>{`${questionsLeft} questions left today`}</span>
          <span>{`18+ · GamCare ${GAMCARE_PHONE}`}</span>
        </p>
      </footer>
    </div>
  );
}
