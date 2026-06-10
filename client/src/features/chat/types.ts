export interface ConversationMessage {
  role: "你" | "Agent" | "系统";
  text: string;
  meta?: string;
}
