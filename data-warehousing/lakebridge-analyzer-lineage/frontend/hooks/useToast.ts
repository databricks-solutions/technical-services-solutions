/**
 * Custom hook for managing toast notifications
 */

import { useState, useCallback, useEffect } from 'react';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

interface ToastContextType {
  toasts: Toast[];
  showToast: (message: string, type: ToastType, duration?: number, action?: Toast['action']) => void;
  removeToast: (id: string) => void;
}

let toastCounter = 0;

// Global toast state for cross-component usage
let globalToasts: Toast[] = [];
let listeners: Array<(toasts: Toast[]) => void> = [];

const emitChange = () => {
  listeners.forEach((listener) => listener(globalToasts));
};

export const useToast = (): ToastContextType => {
  const [toasts, setToasts] = useState<Toast[]>(globalToasts);

  useEffect(() => {
    const listener = (newToasts: Toast[]) => {
      setToasts(newToasts);
    };
    listeners.push(listener);
    return () => {
      listeners = listeners.filter((l) => l !== listener);
    };
  }, []);

  const showToast = useCallback((
    message: string,
    type: ToastType = 'info',
    duration: number = 5000,
    action?: Toast['action']
  ) => {
    const id = `toast-${++toastCounter}`;
    const toast: Toast = { id, type, message, duration, action };
    
    globalToasts = [...globalToasts, toast];
    emitChange();

    // Auto-dismiss after duration
    if (duration > 0) {
      setTimeout(() => {
        globalToasts = globalToasts.filter((t) => t.id !== id);
        emitChange();
      }, duration);
    }
  }, []);

  const removeToast = useCallback((id: string) => {
    globalToasts = globalToasts.filter((t) => t.id !== id);
    emitChange();
  }, []);

  return { toasts, showToast, removeToast };
};

