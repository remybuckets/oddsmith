import Link from "next/link";
import { Logo, SiteFooter } from "@/components/app/brand";

// DRAFT: placeholder wording until the UK GDPR privacy notice is written and reviewed.
export default function PrivacyPage() {
  return (
    <>
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-6">
        <Link href="/">
          <Logo />
        </Link>
        <h1 className="text-2xl font-semibold">Privacy</h1>
        <p className="rounded-lg border border-card-red/50 px-3 py-2 text-sm">
          Draft for the private beta. A full privacy notice will replace this page before launch.
        </p>
        <ul className="flex list-disc flex-col gap-2 pl-5">
          <li>We store your email address to sign you in, your 18+ declaration, your chats and your daily usage.</li>
          <li>We use them only to run Oddsmith, keep to the daily limits and fix wrong answers.</li>
          <li>Your browser stores your sign-in session; we don&apos;t use tracking or advertising cookies.</li>
          <li>Deleting your account in Settings removes your account, chats and usage.</li>
        </ul>
      </main>
      <SiteFooter />
    </>
  );
}
