import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

interface ConfirmRequest {
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  resolve: (value: boolean) => void;
}

type ConfirmFn = (message: string, options?: { confirmLabel?: string; cancelLabel?: string }) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

/**
 * 应用内确认弹窗,替代 window.confirm。
 * window.confirm 同步阻塞 JS 线程,在 iframe/无头/嵌入式环境会卡死渲染器,
 * 某些上下文还会被禁用而静默返回 false——破坏性操作就失去了二次确认。
 * 这里用 Promise 化的非阻塞弹窗,语义一致但不冻结页面。
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);

  const confirm = useCallback<ConfirmFn>((message, options) => {
    return new Promise<boolean>((resolve) => {
      setRequest({
        message,
        confirmLabel: options?.confirmLabel ?? "确认",
        cancelLabel: options?.cancelLabel ?? "取消",
        resolve,
      });
    });
  }, []);

  const settle = useCallback(
    (value: boolean) => {
      setRequest((current) => {
        current?.resolve(value);
        return null;
      });
    },
    []
  );

  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      {request && (
        <div className="confirmOverlay" role="dialog" aria-modal="true" onClick={() => settle(false)}>
          <div className="confirmDialog" onClick={(event) => event.stopPropagation()}>
            <p className="confirmMessage">{request.message}</p>
            <div className="confirmActions">
              <button type="button" className="confirmCancel" onClick={() => settle(false)}>
                {request.cancelLabel}
              </button>
              <button type="button" className="confirmAccept" autoFocus onClick={() => settle(true)}>
                {request.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmContext);
  if (!confirm) {
    // Provider 缺失时回退到原生 confirm,保证破坏性操作不会无声执行。
    return (message) => Promise.resolve(window.confirm(message));
  }
  return confirm;
}
