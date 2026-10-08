import Link from "next/link";
import { Logo, SiteFooter } from "@/components/app/brand";
import { buttonVariants } from "@/components/ui/button";

const EXAMPLE_QUESTIONS = [
  "How has Saka done away from home this season?",
  "Who's injured for Villa vs Spurs?",
  "What's the best price on Newcastle to win?",
];

export default function LandingPage() {
  return (
    <>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-8 p-6">
        <div className="flex flex-col gap-3">
          <h1 className="text-4xl font-bold tracking-tight">
            <Logo className="text-4xl" />
          </h1>
          <p className="text-lg text-muted-foreground">The tipster the bookies would send off.</p>
          <p>
            Premier League stats, injuries and odds in a chat. Every number comes with its source and how
            fresh it is.
          </p>
        </div>
        <ul className="flex flex-col gap-2">
          {EXAMPLE_QUESTIONS.map((question) => (
            <li
              key={question}
              aria-label={`Example question: ${question}`}
              className="rounded-2xl rounded-br-sm bg-secondary px-3 py-2 text-sm"
            >
              {question}
            </li>
          ))}
        </ul>
        <Link href="/sign-in" className={buttonVariants({ size: "lg", className: "h-11 text-base" })}>
          Sign in
        </Link>
      </main>
      <SiteFooter />
    </>
  );
}
