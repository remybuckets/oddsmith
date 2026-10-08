import Link from "next/link";
import { cn } from "@/lib/utils";

export const GAMCARE_PHONE = "0808 8020 133";
export const GAMSTOP_URL = "https://www.gamstop.co.uk";

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <span aria-hidden className="inline-block h-4 w-3 rotate-12 rounded-[2px] bg-card-red" />
      Oddsmith
    </span>
  );
}

export function SupportLinks({ className }: { className?: string }) {
  return (
    <p className={cn("text-sm", className)}>
      Need to talk? Call{" "}
      <a href={`tel:${GAMCARE_PHONE.replace(/\s/g, "")}`} className="underline underline-offset-2">
        GamCare on {GAMCARE_PHONE}
      </a>{" "}
      (free, 24/7) or block gambling sites with{" "}
      <a href={GAMSTOP_URL} target="_blank" rel="noreferrer" className="underline underline-offset-2">
        GAMSTOP
      </a>
      .
    </p>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-auto flex flex-col gap-2 border-t px-4 py-6 text-xs text-muted-foreground">
      <p>
        <strong className="text-foreground">18+ only.</strong> Oddsmith gives information, not betting
        advice. Gamble responsibly.
      </p>
      <SupportLinks className="text-xs" />
      <p className="flex gap-4">
        <Link href="/terms" className="underline underline-offset-2">
          Terms
        </Link>
        <Link href="/privacy" className="underline underline-offset-2">
          Privacy
        </Link>
      </p>
    </footer>
  );
}
