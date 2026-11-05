import { useState } from 'react';
import { Alert, FormUI, Input, Modal, SimpleSelect, SimpleSelectOption, Typography } from '@databricks/design-system';
import { api, useResource } from '../api';

interface Columns {
  comment: string;
  columns: { name: string; type: string; comment: string }[];
}

const TABLE = '__table__';

/** Write the comment of a source table or of any of its columns. Runs COMMENT ON as the user. */
export function WriteComment({
  projectId,
  sourceId,
  fullName,
  onClose,
}: {
  projectId: string;
  sourceId: string;
  fullName: string;
  onClose: (saved: boolean) => void;
}) {
  const data = useResource<Columns>(`/api/projects/${projectId}/sources/${sourceId}/columns`);
  const [target, setTarget] = useState(TABLE);
  const [text, setText] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const current = target === TABLE ? data.data?.comment : data.data?.columns.find((c) => c.name === target)?.comment;
  const value = text ?? current ?? '';

  const save = () => {
    setBusy(true);
    setError(undefined);
    api(`/api/projects/${projectId}/sources/${sourceId}/comment`, {
      column: target === TABLE ? null : target,
      text: value,
    }).then(
      () => onClose(true),
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <Modal
      componentId="gsb.sources.write_comment"
      title={`Write a comment: ${fullName.split('.').pop() ?? fullName}`}
      visible
      okText="Run SQL"
      cancelText="Cancel"
      okButtonProps={{ loading: busy, disabled: !value.trim() || data.status !== 'ready' }}
      onCancel={() => onClose(false)}
      onOk={save}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Alert
          componentId="gsb.sources.write_comment_warning"
          type="warning"
          closable={false}
          message="This runs COMMENT ON as you on the SQL warehouse. It changes Unity Catalog metadata, not table data."
        />
        <div>
          <FormUI.Label htmlFor="wc-target">Table or column</FormUI.Label>
          <SimpleSelect
            componentId="gsb.sources.write_comment_target"
            id="wc-target"
            value={target}
            onChange={(e) => {
              setTarget(e.target.value);
              setText(undefined);
            }}
          >
            <SimpleSelectOption value={TABLE}>The table</SimpleSelectOption>
            {(data.data?.columns ?? []).map((c) => (
              <SimpleSelectOption key={c.name} value={c.name}>
                {`${c.name} (${c.type})${c.comment ? '' : ' - no comment'}`}
              </SimpleSelectOption>
            ))}
          </SimpleSelect>
        </div>
        <div>
          <FormUI.Label htmlFor="wc-text">Comment</FormUI.Label>
          <Input.TextArea
            componentId="gsb.sources.write_comment_text"
            id="wc-text"
            autoSize={{ minRows: 2, maxRows: 6 }}
            maxLength={1000}
            placeholder="What it means for the business, in one or two sentences"
            value={value}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        {data.status === 'error' && <Typography.Text color="error">{data.error}</Typography.Text>}
        {error && <Alert componentId="gsb.sources.write_comment_error" type="error" closable={false} message={error} />}
      </div>
    </Modal>
  );
}
