import type { RollbackConfirmationSummary } from "@workbench/shared";

interface RollbackConfirmationViewProps {
  confirmation: RollbackConfirmationSummary;
  compact?: boolean;
}

export function RollbackConfirmationView({ confirmation, compact = false }: RollbackConfirmationViewProps) {
  return (
    <div className={`rollbackConfirmation ${confirmation.status} ${compact ? "compact" : ""}`}>
      <strong>{confirmationLabel(confirmation.status)}</strong>
      <span>{confirmation.summary}</span>
      {!compact && (
        <small>
          变更文件 {confirmation.beforeFileCount} → {confirmation.afterFileCount}，diff {confirmation.beforeDiffBytes} → {confirmation.afterDiffBytes} bytes
        </small>
      )}
    </div>
  );
}

function confirmationLabel(status: string) {
  if (status === "clean") return "回退已确认";
  if (status === "improved") return "回退已减少变更";
  if (status === "unchanged") return "回退未改变 diff";
  if (status === "expanded") return "回退后变更多";
  if (status === "failed") return "回退失败";
  return "回退结果待确认";
}
