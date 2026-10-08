import Link from "next/link";
import { Logo, SiteFooter } from "@/components/app/brand";
import { SignInForm } from "@/components/auth/sign-in-form";

export default function SignInPage() {
  return (
    <>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-6 p-6">
        <Link href="/">
          <Logo />
        </Link>
        <SignInForm />
      </main>
      <SiteFooter />
    </>
  );
}
