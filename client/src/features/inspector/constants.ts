import type { AgentPhase, ToolCallPlan } from "@workbench/shared";

export const phaseLabels: Record<AgentPhase, string> = {
  idle: "未开始",
  repository_required: "等待仓库",
  sandbox_creating: "创建沙盒",
  sandbox_ready: "沙盒就绪",
  preflight: "预检",
  clarification: "澄清需求",
  planning: "生成方案",
  waiting_plan_confirmation: "等待确认方案",
  waiting_tool_plan_confirmation: "等待确认工具计划",
  waiting_sandbox: "等待沙盒",
  locating_code: "定位代码",
  ready_to_edit: "准备修改",
  checkpoint_before_write: "写入前 checkpoint",
  editing: "修改代码",
  verifying: "运行验证",
  reviewing: "审查结果",
  delivery_ready: "交付待确认",
  execution_blocked: "执行阻断",
  execution_ready: "执行就绪",
  tool_plan_approved: "工具计划已确认",
  tool_plan_running: "工具计划执行中",
  tool_plan_completed: "工具计划完成",
  tool_plan_failed: "工具计划失败",
  tool_plan_waiting_approval: "工具等待授权",
  completed: "已完成",
  failed: "失败"
};

export const toolPlanStatusLabels: Record<ToolCallPlan["status"], string> = {
  waiting_confirmation: "等待确认",
  approved: "已确认",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  waiting_approval: "等待授权"
};
