"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import type { ApiClient } from "@/lib/api/client";
import { asApiError } from "@/lib/api/errors";
import type { Conversation } from "@/lib/api/types";
import { formatUkDateTime } from "@/lib/format/time";
import { cn } from "@/lib/utils";

interface ConversationsSheetProps {
  api: ApiClient;
  currentId: string | null;
  onSelect: (id: string) => void;
}

export function ConversationsSheet({ api, currentId, onSelect }: ConversationsSheetProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(cursor?: string) {
    setIsLoading(true);
    setError(null);
    try {
      const page = await api.listConversations(cursor ? { cursor } : {});
      setConversations((previous) => (cursor ? [...previous, ...page.items] : page.items));
      setNextCursor(page.nextCursor);
    } catch (cause) {
      setError(asApiError(cause).message);
    } finally {
      setIsLoading(false);
    }
  }

  function handleOpenChange(open: boolean) {
    setIsOpen(open);
    if (open) void load();
  }

  function choose(id: string) {
    setIsOpen(false);
    onSelect(id);
  }

  return (
    <Sheet open={isOpen} onOpenChange={handleOpenChange}>
      <SheetTrigger render={<Button variant="ghost" size="sm" />}>Your chats</SheetTrigger>
      <SheetContent side="left">
        <SheetHeader>
          <SheetTitle>Your chats</SheetTitle>
        </SheetHeader>
        <div className="flex flex-col gap-1 overflow-y-auto px-2 pb-4">
          {error && (
            <p role="alert" className="px-2 text-sm text-card-red">
              {error}
            </p>
          )}
          {!isLoading && !error && conversations.length === 0 && (
            <p className="px-2 text-sm text-muted-foreground">No chats yet.</p>
          )}
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              type="button"
              onClick={() => choose(conversation.id)}
              className={cn(
                "flex flex-col items-start rounded-md px-2 py-2 text-left hover:bg-muted",
                conversation.id === currentId && "bg-muted",
              )}
            >
              <span className="line-clamp-1">{conversation.title ?? "Untitled chat"}</span>
              <span className="text-xs text-muted-foreground">{formatUkDateTime(conversation.updated_at)}</span>
            </button>
          ))}
          {nextCursor && (
            <Button variant="ghost" size="sm" disabled={isLoading} onClick={() => load(nextCursor)}>
              Load more
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
