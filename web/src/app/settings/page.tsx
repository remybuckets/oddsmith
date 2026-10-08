import { SiteFooter } from "@/components/app/brand";
import { MemberGate } from "@/components/app/member-gate";
import { SettingsScreen } from "@/components/settings/settings-screen";

export default function SettingsPage() {
  return (
    <>
      <MemberGate allowOnBreak>
        <SettingsScreen />
      </MemberGate>
      <SiteFooter />
    </>
  );
}
