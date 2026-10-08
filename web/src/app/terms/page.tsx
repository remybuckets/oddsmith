import Link from "next/link";
import { Logo, SiteFooter } from "@/components/app/brand";

// DRAFT: placeholder wording until the terms are written and reviewed (SPEC "Compliance").
export default function TermsPage() {
  return (
    <>
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-6">
        <Link href="/">
          <Logo />
        </Link>
        <h1 className="text-2xl font-semibold">Terms of use</h1>
        <p className="rounded-lg border border-card-red/50 px-3 py-2 text-sm">
          Draft for the private beta. Final terms will replace this page before launch.
        </p>
        <ul className="flex list-disc flex-col gap-2 pl-5">
          <li>Oddsmith is only for adults (18 or over) in Great Britain.</li>
          <li>
            Oddsmith gives information about football and betting markets. It is not betting advice and takes no
            bets.
          </li>
          <li>Value views are estimates from a simple model and can be wrong. Only bet what you can afford to lose.</li>
          <li>
            Stats and odds come from third-party providers and may be late or incomplete; each answer shows its
            sources and times.
          </li>
          <li>You can take a break or delete your account at any time in Settings.</li>
        </ul>
      </main>
      <SiteFooter />
    </>
  );
}
