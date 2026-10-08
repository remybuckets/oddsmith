"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";
import Markdown from "react-markdown";
import { Button } from "@/components/ui/button";
import type { FeedbackRating, SourceRef } from "@/lib/api/types";
import type { AnswerState } from "@/lib/chat/answer";
import { formatUkDateTime } from "@/lib/format/time";
import { CardView } from "./cards";

interface AnswerViewProps {
  answer: AnswerState;
  feedback?: FeedbackRating | null;
  onFeedback?: (rating: FeedbackRating) => void;
}

function sourcesLine(sources: SourceRef[]): string {
  const parts = sources.map((s) => `${s.source} (${formatUkDateTime(s.as_of)})`);
  return `Sources: ${parts.join(", ")}`;
}

function FeedbackButtons({
  value,
  onChange,
}: {
  value: FeedbackRating | null;
  onChange: (rating: FeedbackRating) => void;
}) {
  return (
    <div className="flex gap-1">
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Helpful"
        aria-pressed={value === 1}
        onClick={() => onChange(1)}
        className="aria-pressed:text-primary"
      >
        <ThumbsUp />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Not helpful"
        aria-pressed={value === -1}
        onClick={() => onChange(-1)}
        className="aria-pressed:text-primary"
      >
        <ThumbsDown />
      </Button>
    </div>
  );
}

export function AnswerView({ answer, feedback = null, onFeedback }: AnswerViewProps) {
  const isDone = answer.status === "done";
  return (
    <div className="flex flex-col gap-3">
      {answer.activity && (
        <p role="status" className="animate-pulse text-xs text-muted-foreground">
          {`${answer.activity}…`}
        </p>
      )}
      {answer.text && (
        <div className="leading-relaxed [&_li]:ml-4 [&_ol]:list-decimal [&_p+p]:mt-2 [&_ul]:list-disc">
          <Markdown>{answer.text}</Markdown>
        </div>
      )}
      {answer.cards.map((card, index) => (
        <CardView key={index} card={card} />
      ))}
      {answer.status === "error" && answer.error && (
        <p role="alert" className="rounded-lg border border-card-red/40 px-3 py-2 text-sm">
          {answer.error.message}
        </p>
      )}
      {answer.sources.length > 0 && (
        <p className="text-xs text-muted-foreground">{sourcesLine(answer.sources)}</p>
      )}
      {isDone && answer.messageId && onFeedback && (
        <FeedbackButtons value={feedback} onChange={onFeedback} />
      )}
    </div>
  );
}
