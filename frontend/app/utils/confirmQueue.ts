export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  tone?: 'primary' | 'danger';
}

export interface ConfirmRequest {
  id: number;
  options: ConfirmOptions;
}

export function createConfirmQueue(onChange: (request: ConfirmRequest | null) => void = () => {}) {
  let sequence = 0;
  type Pending = { request: ConfirmRequest; resolve: (value: boolean) => void };
  let current: Pending | null = null;
  const pending: Pending[] = [];

  function advance() {
    current = pending.shift() ?? null;
    onChange(current?.request ?? null);
  }

  return {
    get active(): ConfirmRequest | null { return current?.request ?? null; },
    confirm(options: ConfirmOptions): Promise<boolean> {
      return new Promise((resolve) => {
        pending.push({ request: { id: ++sequence, options: { ...options } }, resolve });
        if (!current) advance();
      });
    },
    settle(value: boolean, id: number) {
      if (!current || current.request.id !== id) return;
      const previous = current;
      current = null;
      advance();
      previous.resolve(value);
    },
    cancelAll() {
      const cancelled = current ? [current, ...pending] : [...pending];
      current = null;
      pending.length = 0;
      onChange(null);
      for (const entry of cancelled) entry.resolve(false);
    },
  };
}
