import type { ReactNode } from 'react';
import { Alert, Button, Empty, LockIcon, Spinner } from '@databricks/design-system';

export type DataStateStatus = 'loading' | 'empty' | 'error' | 'forbidden' | 'ready';

interface DataStateProps {
  status: DataStateStatus;
  /** Shown for loading (spinner label), empty, error, and forbidden. */
  message?: ReactNode;
  emptyAction?: ReactNode;
  onRetry?: () => void;
  children?: ReactNode;
}

/** One place for the four required states of every data screen. */
export function DataState({ status, message, emptyAction, onRetry, children }: DataStateProps) {
  switch (status) {
    case 'loading':
      return (
        <div role="status" aria-live="polite" style={{ padding: 32, display: 'flex', justifyContent: 'center' }}>
          <Spinner label={message ?? 'Loading'} />
        </div>
      );
    case 'empty':
      return <Empty title="Nothing here yet" description={message ?? 'No items to show.'} button={emptyAction} />;
    case 'forbidden':
      return (
        <Empty
          image={<LockIcon />}
          title="You do not have access"
          description={
            message ??
            'Your Unity Catalog privileges do not allow this action. Ask the object owner or a metastore admin for access.'
          }
        />
      );
    case 'error':
      return (
        <div role="alert" style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
          <Alert
            componentId="gsb.data_state.error"
            type="error"
            closable={false}
            message={message ?? 'Something went wrong.'}
          />
          {onRetry && (
            <Button componentId="gsb.data_state.retry" onClick={onRetry}>
              Try again
            </Button>
          )}
        </div>
      );
    default:
      return <>{children}</>;
  }
}
