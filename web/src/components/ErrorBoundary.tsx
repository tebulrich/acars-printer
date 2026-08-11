import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: string | null;
}

/** Catch render crashes so the window does not go fully blank. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error: error?.message || String(error) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI crash", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 bg-[var(--bg)] p-6 text-center">
          <div className="max-w-lg rounded border border-[var(--danger)] bg-[var(--toast-error-bg)] p-4 text-sm text-[var(--danger)]">
            Something went wrong in the UI: {this.state.error}
          </div>
          <button
            type="button"
            className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white"
            onClick={() => {
              this.setState({ error: null });
              window.location.reload();
            }}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
