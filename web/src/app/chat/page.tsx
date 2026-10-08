import { MemberGate } from "@/components/app/member-gate";
import { ChatScreen } from "@/components/chat/chat-screen";

export default function ChatPage() {
  return (
    <MemberGate>
      <ChatScreen />
    </MemberGate>
  );
}
