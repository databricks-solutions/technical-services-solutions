'use client';

import { useToast } from '@/hooks/useToast';
import Toast from './Toast';

export default function ToastContainer() {
  const { toasts, removeToast } = useToast();

  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col space-y-3 pointer-events-none">
      <div className="pointer-events-auto">
        {toasts.map((toast) => (
          <div key={toast.id} className="mb-3">
            <Toast toast={toast} onRemove={removeToast} />
          </div>
        ))}
      </div>
    </div>
  );
}

