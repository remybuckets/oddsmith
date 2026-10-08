import { Logo } from "@/components/app/brand";
import { AuthCallback } from "@/components/auth/auth-callback";

export default function AuthCallbackPage() {
  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-6 p-6">
      <Logo />
      <AuthCallback />
    </main>
  );
}
