"use client";

import { ArrowUp, X } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { AnswerView } from "@/components/answer/answer-view";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { describeApiError } from "@/lib/api/error-display";
import type { ApiRequestError } from "@/lib/api/errors";
import type { FeedbackRating, Fixture, NextFixtures } from "@/lib/api/types";
import type { ChatItem } from "@/lib/chat/use-chat";
import { formatUkDateTime } from "@/lib/format/time";

const MAX_QUESTION_LENGTH = 1000;

export function fixtureQuestion(fixture: Fixture): string {
  return `What do I need to know before ${fixture.home.short_name} v ${fixture.away.short_name}?`;
}

export function FixtureStrip({ next, onAsk }: { next: NextFixtures; onAsk: (question: string) => void }) {
  if (next.fixtures.length === 0) return null;
  return (
    <section aria-labelledby="matchweek" className="flex flex-col gap-2">
      <h2 id="matchweek" className="px-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {`Matchweek ${next.matchweek}`}
      </h2>
      <ul className="flex gap-2 overflow-x-auto px-4 pb-1">
        {next.fixtures.map((fixture) => (
          <li key={fixture.fixture_id} className="shrink-0">
            <button
              type="button"
              onClick={() => onAsk(fixtureQuestion(fixture))}
              className="flex flex-col items-start rounded-lg border bg-card px-3 py-2 text-left text-sm hover:border-primary"
            >
              <span className="font-medium">{`${fixture.home.short_name} v ${fixture.away.short_name}`}</span>
              <span className="text-xs text-muted-foreground">{formatUkDateTime(fixture.kickoff_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function SuggestedQuestions({ questions, onAsk }: { questions: string[]; onAsk: (question: string) => void }) {
  if (questions.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-muted-foreground">Try asking</p>
      {questions.map((question) => (
        <Button
          key={question}
          variant="outline"
          className="h-auto justify-start whitespace-normal py-2 text-left"
          onClick={() => onAsk(question)}
        >
          {question}
        </Button>
      ))}
    </div>
  );
}

export function ChatInput({ onSend, isSending }: { onSend: (question: string) => void; isSending: boolean }) {
  const [text, setText] = useState("");
  const canSend = text.trim().length > 0 && !isSending;

  function send() {
    if (!canSend) return;
    onSend(text);
    setText("");
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2">
      <Textarea
        aria-label="Ask Oddsmith"
        placeholder="Ask about a player, team or match…"
        rows={1}
        maxLength={MAX_QUESTION_LENGTH}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
        className="max-h-32 min-h-10 resize-none"
      />
      <Button type="submit" size="icon-lg" aria-label="Send" disabled={!canSend}>
        <ArrowUp />
      </Button>
    </form>
  );
}

export function ErrorBanner({ error, onDismiss }: { error: ApiRequestError; onDismiss: () => void }) {
  const display = describeApiError(error);
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-card-red/50 bg-card px-3 py-2 text-sm">
      <div className="flex flex-1 flex-col gap-0.5">
        <p className="font-semibold">{display.title}</p>
        <p>{display.body}</p>
        {display.retryLabel && <p className="text-muted-foreground">{display.retryLabel}</p>}
      </div>
      <Button variant="ghost" size="icon-xs" aria-label="Dismiss" onClick={onDismiss}>
        <X />
      </Button>
    </div>
  );
}

export function Thread({
  items,
  onRate,
}: {
  items: ChatItem[];
  onRate: (messageId: string, rating: FeedbackRating) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  const last = items.at(-1);
  const lastLength = last?.kind === "assistant" ? last.answer.text.length + last.answer.cards.length : 0;

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [items.length, lastLength]);

  return (
    <div className="flex flex-col gap-5">
      <ol className="flex flex-col gap-5">
        {items.map((item) => (
          <li key={item.id} className={item.kind === "user" ? "self-end" : "self-stretch"}>
            {item.kind === "user" ? (
              <p className="max-w-[85vw] rounded-2xl rounded-br-sm bg-secondary px-3 py-2 sm:max-w-md">
                {item.content}
              </p>
            ) : (
              <AnswerView
                answer={item.answer}
                feedback={item.feedback}
                onFeedback={(rating) => item.answer.messageId && onRate(item.answer.messageId, rating)}
              />
            )}
          </li>
        ))}
      </ol>
      <div ref={end} />
    </div>
  );
}
