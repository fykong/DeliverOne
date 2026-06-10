import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  /** 出错时显示的区域名,便于用户描述问题。 */
  label: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * 单个面板渲染出错时只降级该面板,不让整个应用白屏。
 * 这是"一个面板崩溃 = 整个工作台不可用"的根本防护。
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 保留到控制台便于排查,但不向用户暴露堆栈。
    console.error(`[${this.props.label}] 渲染出错:`, error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <section className="panel panelError" role="alert">
          <h3>{this.props.label} 暂时无法显示</h3>
          <p>这个面板渲染时出错了，其他功能不受影响。可点击重试，或继续使用其它面板。</p>
          <button type="button" className="inspectorButton secondary" onClick={this.reset}>
            重试
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
