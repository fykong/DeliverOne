export interface ConversationMessage {
  role: "你" | "Agent" | "系统";
  text: string;
  meta?: string;
  /** Clarifier 阻断时的澄清问题列表，渲染在消息下方。 */
  questions?: string[];
}
