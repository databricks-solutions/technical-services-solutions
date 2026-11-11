import { useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  DialogCombobox,
  DialogComboboxContent,
  DialogComboboxOptionList,
  DialogComboboxOptionListSearch,
  DialogComboboxOptionListSelectItem,
  DialogComboboxTrigger,
  DownloadIcon,
  FormUI,
  Input,
  Modal,
  PencilIcon,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import { DESCRIPTION_MAX, importPrompt, pagesBundle, piiWarnings } from '../../../shared/pages';
import type { DomainList, PageDraft, PagesView } from '../../../shared/pages';
import { api, useResource } from '../api';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';

const KIND: Record<PageDraft['kind'], string> = {
  term: 'Business term',
  metric: 'Metric',
  dimension: 'Dimension',
  entity: 'Entity',
};

function EditModal({
  page,
  busy,
  onSave,
  onReset,
  onClose,
}: {
  page: PageDraft;
  busy: boolean;
  onSave: (p: PageDraft) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  const [p, setP] = useState(page);
  const [synonyms, setSynonyms] = useState(page.synonyms.join(', '));
  const next = {
    ...p,
    synonyms: synonyms
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 20),
  };
  const warnings = piiWarnings(next);
  return (
    <Modal
      componentId="gsb.pages.edit_modal"
      size="wide"
      title={`Edit the Page: ${page.title}`}
      visible
      okText="Save"
      cancelText="Cancel"
      okButtonProps={{ loading: busy, disabled: !next.title.trim() }}
      onOk={() => onSave(next)}
      onCancel={onClose}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <FormUI.Label htmlFor="page-title">Title</FormUI.Label>
          <Input
            componentId="gsb.pages.title"
            id="page-title"
            maxLength={200}
            value={p.title}
            onChange={(e) => setP({ ...p, title: e.target.value })}
          />
        </div>
        <div>
          <FormUI.Label htmlFor="page-synonyms">Synonyms</FormUI.Label>
          <FormUI.Hint>Other names users type, separated by commas.</FormUI.Hint>
          <Input
            componentId="gsb.pages.synonyms"
            id="page-synonyms"
            value={synonyms}
            onChange={(e) => setSynonyms(e.target.value)}
          />
        </div>
        <div>
          <FormUI.Label htmlFor="page-description">Description</FormUI.Label>
          <FormUI.Hint>
            A short summary, {DESCRIPTION_MAX} characters maximum ({p.description.length} now). Genie One shows it
            first.
          </FormUI.Hint>
          <Input.TextArea
            componentId="gsb.pages.description"
            id="page-description"
            autoSize={{ minRows: 2, maxRows: 5 }}
            maxLength={DESCRIPTION_MAX}
            value={p.description}
            onChange={(e) => setP({ ...p, description: e.target.value })}
          />
        </div>
        <div>
          <FormUI.Label htmlFor="page-body">Page body (Markdown)</FormUI.Label>
          <Input.TextArea
            componentId="gsb.pages.body"
            id="page-body"
            autoSize={{ minRows: 10, maxRows: 24 }}
            maxLength={20000}
            value={p.body}
            onChange={(e) => setP({ ...p, body: e.target.value })}
          />
        </div>
        <Typography.Text color="secondary" size="sm">
          Related assets: {page.relatedAssets.join(', ') || 'none'}. Sources: {page.sources.join(', ')}.
        </Typography.Text>
        {warnings.length > 0 && (
          <Alert
            componentId="gsb.pages.pii"
            type="warning"
            closable={false}
            message="Pages must not hold personal or regulated data"
            description={warnings.join(' ')}
          />
        )}
        {page.edited && (
          <div>
            <Button componentId="gsb.pages.reset" size="small" disabled={busy} onClick={onReset}>
              Go back to the generated Page
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}

/**
 * Pages for UC Semantics Discover: business concepts that Genie One uses as context. Pages have no API, so the app
 * drafts them, the user edits them, and the download goes to Genie Code bulk import. Nothing is published from here.
 */
export function PagesPanel({ projectId, title }: { projectId: string; title: string }) {
  const data = useResource<PagesView>(`/api/projects/${projectId}/pages`);
  const list = useResource<DomainList>('/api/pages/domains').data;
  const [domain, setDomain] = useState<string>();
  const [editing, setEditing] = useState<PageDraft>();
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [done, setDone] = useState<number>();
  const base = useResource<{ workspaceUrl: string | null }>('/api/config').data?.workspaceUrl;
  const [copied, setCopied] = useState(false);
  const [script, setScript] = useState<string>();
  const v = data.data;
  const current = domain ?? v?.domain ?? '';
  const included = v?.pages.filter((p) => p.include) ?? [];
  const flagged = included.filter((p) => piiWarnings(p).length);

  const post = (path: string, body: unknown, after?: () => void) => {
    setBusy(true);
    setError(undefined);
    api<PagesView>(`/api/projects/${projectId}/pages/${path}`, body).then(
      (next) => {
        setBusy(false);
        data.setData(next);
        after?.();
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };
  const save = (p: PageDraft) =>
    post(
      'edit',
      {
        key: p.key,
        title: p.title,
        synonyms: p.synonyms,
        description: p.description,
        body: p.body,
        include: p.include,
      },
      () => setEditing(undefined)
    );
  const download = () => {
    if (!v) return;
    const blob = new Blob([pagesBundle(v, title)], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${
      title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '') || 'semantics'
    }-pages.md`;
    a.click();
    URL.revokeObjectURL(a.href);
    setDone(included.length);
    void api(`/api/projects/${projectId}/pages/exported`, { pages: included.length }).catch(() => undefined);
  };

  return (
    <section aria-labelledby="gsb-pages" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Title level={4} id="gsb-pages" withoutMargins>
        Pages for Discover
      </Typography.Title>
      <Typography.Text color="secondary">
        Pages are governed definitions of business concepts in Unity Catalog Discover. Genie One uses published Pages as
        context when it answers. The app drafts one Page for each certified dictionary entry, each glossary term of the
        brief, and the metric view. Edit them here, then download one file for Genie Code bulk import.
      </Typography.Text>
      <DataState status={data.status} message={data.error} onRetry={data.reload}>
        {v && (
          <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div style={{ minWidth: 320 }}>
                <FormUI.Label htmlFor="pages-domain">Domain</FormUI.Label>
                {list?.domains.length ? (
                  <>
                    <FormUI.Hint>
                      The published Discover domain or subdomain of these Pages. One per project.
                    </FormUI.Hint>
                    <DialogCombobox
                      componentId="gsb.pages.domain_pick"
                      id="pages-domain"
                      value={current ? [current] : []}
                    >
                      <DialogComboboxTrigger placeholder="Select a domain" allowClear={false} width={360} />
                      <DialogComboboxContent maxHeight={360} matchTriggerWidth>
                        <DialogComboboxOptionList>
                          <DialogComboboxOptionListSearch>
                            {list.domains.map((d) => (
                              <DialogComboboxOptionListSelectItem
                                key={d.id}
                                value={d.name}
                                checked={d.name === current}
                                onChange={() => setDomain(d.name)}
                                hintColumn={d.subdomain ? 'Subdomain' : undefined}
                              >
                                {d.name}
                              </DialogComboboxOptionListSelectItem>
                            ))}
                          </DialogComboboxOptionListSearch>
                        </DialogComboboxOptionList>
                      </DialogComboboxContent>
                    </DialogCombobox>
                    {v.domain && !list.domains.some((d) => d.name === v.domain) && (
                      <FormUI.Message
                        type="warning"
                        message={`"${v.domain}" is not a published Discover domain. Select one from the list.`}
                      />
                    )}
                  </>
                ) : (
                  <>
                    <FormUI.Hint>
                      Type the exact name of a Discover domain or subdomain, for example Sales or Sales/Orders. One per
                      project.
                      {list?.error &&
                        ' The app cannot list the domains: its service principal needs the MANAGE DISCOVER permission. Copy the name from Discover > Manage Domains.'}
                    </FormUI.Hint>
                    <Input
                      componentId="gsb.pages.domain"
                      id="pages-domain"
                      maxLength={200}
                      value={current}
                      onChange={(e) => setDomain(e.target.value)}
                    />
                  </>
                )}
              </div>
              <Button
                componentId="gsb.pages.save_domain"
                disabled={busy || !domain?.trim() || domain.trim() === v.domain}
                onClick={() => post('domain', { domain: domain!.trim() }, () => setDomain(undefined))}
              >
                Save the domain
              </Button>
            </div>
            {v.pages.length ? (
              <Table aria-label="Pages" scrollable>
                <TableRow isHeader>
                  <TableHeader componentId="gsb.pages.h_include" style={{ flex: '0 0 72px' }}>
                    Include
                  </TableHeader>
                  <TableHeader componentId="gsb.pages.h_title" style={{ flex: 2 }}>
                    Page
                  </TableHeader>
                  <TableHeader componentId="gsb.pages.h_desc" style={{ flex: 4 }}>
                    Description
                  </TableHeader>
                  <TableHeader componentId="gsb.pages.h_syn" style={{ flex: 2 }}>
                    Synonyms
                  </TableHeader>
                  <TableHeader componentId="gsb.pages.h_edit" style={{ flex: '0 0 96px' }}>
                    {' '}
                  </TableHeader>
                </TableRow>
                {v.pages.map((p) => (
                  <TableRow key={p.key}>
                    <TableCell style={{ flex: '0 0 72px' }}>
                      <Checkbox
                        componentId="gsb.pages.include"
                        aria-label={`Include ${p.title}`}
                        isChecked={p.include}
                        isDisabled={busy}
                        onChange={(on) => save({ ...p, include: on })}
                      />
                    </TableCell>
                    <TableCell multiline style={{ flex: 2 }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                        <Typography.Text bold>{p.title}</Typography.Text>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          <Tag componentId="gsb.pages.kind">{KIND[p.kind]}</Tag>
                          {p.edited && (
                            <Tag componentId="gsb.pages.edited" color="indigo">
                              Edited
                            </Tag>
                          )}
                          {piiWarnings(p).length > 0 && (
                            <Tag componentId="gsb.pages.pii_tag" color="coral" title={piiWarnings(p).join(' ')}>
                              Check for personal data
                            </Tag>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell multiline style={{ flex: 4 }}>
                      <Typography.Text color={p.description ? undefined : 'secondary'}>
                        {p.description || 'No description'}
                      </Typography.Text>
                    </TableCell>
                    <TableCell multiline style={{ flex: 2 }}>
                      {p.synonyms.join(', ')}
                    </TableCell>
                    <TableCell style={{ flex: '0 0 96px' }}>
                      <Button
                        componentId="gsb.pages.edit"
                        size="small"
                        icon={<PencilIcon />}
                        disabled={busy}
                        aria-label={`Edit ${p.title}`}
                        onClick={() => setEditing(p)}
                      >
                        Edit
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </Table>
            ) : (
              <Typography.Text color="secondary">
                No Pages yet. Certify entries in the project dictionary, add glossary terms to the brief, or design the
                metric view.
              </Typography.Text>
            )}
            {flagged.length > 0 && (
              <Checkbox componentId="gsb.pages.pii_checked" isChecked={checked} onChange={setChecked}>
                I checked the {flagged.length} flagged Page{flagged.length === 1 ? '' : 's'}: they hold no personal or
                regulated data
              </Checkbox>
            )}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Button
                componentId="gsb.pages.download"
                type="primary"
                icon={<DownloadIcon />}
                disabled={!v.domain || !included.length || (flagged.length > 0 && !checked)}
                onClick={download}
              >
                Download {included.length} Page{included.length === 1 ? '' : 's'} for bulk import
              </Button>
              <Button
                componentId="gsb.pages.commands"
                disabled={busy || !v.domain || !included.length || (flagged.length > 0 && !checked)}
                onClick={() =>
                  void api<{ script: string }>(`/api/projects/${projectId}/pages/commands`, {}).then(
                    (r) => setScript(r.script),
                    (err: unknown) => setError((err as Error).message)
                  )
                }
              >
                Make the API commands
              </Button>
              {!v.domain && <Typography.Text color="secondary">Save a domain first.</Typography.Text>}
            </div>
            {done !== undefined && (
              <Alert
                componentId="gsb.pages.next"
                type="info"
                closable
                onClose={() => setDone(undefined)}
                message={`Downloaded ${done} Page${done === 1 ? '' : 's'}. Next, in Databricks:`}
                description={
                  <ol style={{ margin: 0, paddingLeft: 20 }}>
                    <li>Open Discover. In the Genie Code pane, select Bulk import pages.</li>
                    <li>Attach the downloaded file, and paste the prompt.</li>
                    <li>Genie Code proposes the Pages. Review them, then let it create them as drafts.</li>
                    <li>A curator of the domain publishes them.</li>
                  </ol>
                }
              />
            )}
            {done !== undefined && v.domain && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {base && (
                  <Typography.Link componentId="gsb.pages.open_discover" href={`${base}/discover`} openInNewTab>
                    Open Discover
                  </Typography.Link>
                )}
                <Button
                  componentId="gsb.pages.copy_prompt"
                  size="small"
                  onClick={() =>
                    void navigator.clipboard.writeText(importPrompt(v.domain!, done)).then(() => setCopied(true))
                  }
                >
                  {copied ? 'Prompt copied' : 'Copy the prompt'}
                </Button>
              </div>
            )}
            {error && <Alert componentId="gsb.pages.error" type="error" closable={false} message={error} />}
          </>
        )}
      </DataState>
      <Modal
        componentId="gsb.pages.commands_modal"
        title="Create the Pages with the API"
        visible={!!script}
        footer={null}
        onCancel={() => setScript(undefined)}
      >
        {script && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Typography.Text>
              The app cannot call the Pages API: apps cannot get its permission scope. Run this script in your terminal,
              as you, with the Databricks CLI and jq. It finds the domain by its name, then creates each Page as a
              draft. A second run does not make copies of Pages that exist. A curator of the domain publishes them.
            </Typography.Text>
            <SqlBlock label="Script (read it before you run it)" sql={script} />
            <div style={{ display: 'flex', gap: 8 }}>
              <Button componentId="gsb.pages.commands_copy" onClick={() => void navigator.clipboard.writeText(script)}>
                Copy
              </Button>
              <Button
                componentId="gsb.pages.commands_download"
                icon={<DownloadIcon />}
                onClick={() => {
                  const a = document.createElement('a');
                  a.href = URL.createObjectURL(new Blob([script], { type: 'text/x-shellscript' }));
                  a.download = 'create-pages.sh';
                  a.click();
                  URL.revokeObjectURL(a.href);
                }}
              >
                Download create-pages.sh
              </Button>
            </div>
          </div>
        )}
      </Modal>
      {editing && (
        <EditModal
          page={editing}
          busy={busy}
          onSave={save}
          onReset={() => post('reset', { key: editing.key }, () => setEditing(undefined))}
          onClose={() => setEditing(undefined)}
        />
      )}
    </section>
  );
}
