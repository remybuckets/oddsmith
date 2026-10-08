import { MemberGate } from "@/components/app/member-gate";
import { Onboarding } from "@/components/onboarding/onboarding";

export default function OnboardingPage() {
  return (
    <MemberGate allowUnconfirmed>
      <Onboarding />
    </MemberGate>
  );
}
