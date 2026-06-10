import { ShieldCheck, ShieldQuestion, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { ApprovalGrant, RuntimeEvent } from "@workbench/shared";

interface ApprovalPanelProps {
  events: RuntimeEvent[];
  approvals: ApprovalGrant[];
  isRunning: boolean;
  onGrant: (toolId: string, scope: ApprovalGrant["scope"], riskLevel?: string, command?: string, requestEventId?: string) => void;
  onDeny: (toolId: string, riskLevel: string, reason: string, requestEventId?: string, command?: string) => void;
}

interface ApprovalRequest {
  eventId: string;
  toolId: string;
  toolName: string;
  riskLevel: string;
  inputSummary: string;
  command?: string;
}

function requestFromEvent(event: RuntimeEvent): ApprovalRequest | null {
  if (event.type !== "approval.requested") return null;
  const payload = event.payload;
  const toolId = typeof payload.toolId === "string" ? payload.toolId : "";
  if (!toolId) return null;
  const toolName = typeof payload.toolName === "string" ? payload.toolName : toolId;
  const riskLevel = typeof payload.riskLevel === "string" ? payload.riskLevel : "external";
  const inputSummary = typeof payload.inputSummary === "string" ? payload.inputSummary : "";
  const command = inputSummary.match(/"command"\s*:\s*"([^"]+)"/)?.[1];
  return { eventId: event.id, toolId, toolName, riskLevel, inputSummary, command };
}

function decisionText(approval: ApprovalGrant) {
  if (approval.decision === "denied") return "已拒绝";
  if (approval.decision === "revoked") return "已撤销";
  if (approval.scope === "once") return "一次授权";
  if (approval.scope === "turn") return "本轮授权";
  return "会话授权";
}

function requestResolved(request: ApprovalRequest, approvals: ApprovalGrant[]) {
  return approvals.some((approval) => {
    if (approval.requestEventId && approval.requestEventId === request.eventId) return true;
    return approval.active && approval.toolId === request.toolId && approval.riskLevel === request.riskLevel;
  });
}

export function ApprovalPanel({ events, approvals, isRunning, onGrant, onDeny }: ApprovalPanelProps) {
  const [selectedRequest, setSelectedRequest] = useState<ApprovalRequest | null>(null);
  const [denyReason, setDenyReason] = useState("");

  const pendingRequests = useMemo(
    () =>
      events
        .map(requestFromEvent)
        .filter((request): request is ApprovalRequest => Boolean(request))
        .filter((request) => !requestResolved(request, approvals))
        .slice(-4)
        .reverse(),
    [approvals, events]
  );

  const history = approvals.slice(-6).reverse();
  const activeSelection = selectedRequest && requestResolved(selectedRequest, approvals) ? null : selectedRequest;

  function closeDialog() {
    setSelectedRequest(null);
    setDenyReason("");
  }

  function grant(scope: ApprovalGrant["scope"]) {
    if (!activeSelection) return;
    onGrant(activeSelection.toolId, scope, activeSelection.riskLevel, activeSelection.command, activeSelection.eventId);
    closeDialog();
  }

  function deny() {
    if (!activeSelection) return;
    const reason = denyReason.trim() || "用户拒绝本次工具调用。";
    onDeny(activeSelection.toolId, activeSelection.riskLevel, reason, activeSelection.eventId, activeSelection.command);
    closeDialog();
  }

  return (
    <section className="panel">
      <h3>
        <ShieldQuestion size={16} />
        审批
        <small>{pendingRequests.length ? `${pendingRequests.length} 个待处理` : "无待处理"}</small>
      </h3>

      {pendingRequests.length === 0 && <p>高风险命令和外部工具会在执行前进入审批。</p>}

      <div className="approvalRequestList">
        {pendingRequests.map((request) => (
          <button className="approvalRequest" key={request.eventId} type="button" onClick={() => setSelectedRequest(request)}>
            <div>
              <ShieldCheck size={14} />
              <strong>{request.toolName}</strong>
              <span>{request.riskLevel}</span>
            </div>
            {request.inputSummary && <code>{request.inputSummary}</code>}
            <em>审查</em>
          </button>
        ))}
      </div>

      {history.length > 0 && (
        <div className="approvalHistory">
          <strong>审批历史</strong>
          {history.map((approval) => (
            <div className={`approvalHistoryRow ${approval.decision ?? "granted"}`} key={approval.id}>
              <span>{decisionText(approval)}</span>
              <code>{approval.toolId}</code>
              <small>{approval.deniedAt ?? approval.revokedAt ?? approval.createdAt}</small>
            </div>
          ))}
        </div>
      )}

      {activeSelection && (
        <div className="modalBackdrop" role="presentation">
          <div className="reviewModal" role="dialog" aria-modal="true" aria-label="审批工具调用">
            <header>
              <div>
                <span>工具审批</span>
                <strong>{activeSelection.toolName}</strong>
              </div>
              <button className="iconButton" type="button" onClick={closeDialog} title="关闭">
                <X size={16} />
              </button>
            </header>
            <div className="modalMeta">
              <span>工具 ID</span>
              <code>{activeSelection.toolId}</code>
              <span>风险级别</span>
              <code>{activeSelection.riskLevel}</code>
            </div>
            <label className="modalField">
              <span>输入摘要</span>
              <pre>{activeSelection.inputSummary || "无输入摘要。"}</pre>
            </label>
            <label className="modalField">
              <span>拒绝原因</span>
              <textarea value={denyReason} onChange={(event) => setDenyReason(event.target.value)} placeholder="可选；拒绝后会写入审批历史和事件流。" />
            </label>
            <footer>
              <button type="button" disabled={isRunning} onClick={() => grant("once")}>
                授权一次
              </button>
              <button type="button" disabled={isRunning} onClick={() => grant("session")}>
                会话授权
              </button>
              <button className="dangerButton" type="button" disabled={isRunning} onClick={deny}>
                拒绝
              </button>
            </footer>
          </div>
        </div>
      )}
    </section>
  );
}
