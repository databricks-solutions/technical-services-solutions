import type { LakebasePool } from '@databricks/appkit';
import type { DictionaryEntry } from '../../shared/dictionary';

/** The dictionary of a project or of its parent: a sub-project reuses the top-level project's entries. */
export async function loadDictionary(db: Pick<LakebasePool, 'query'>, projectId: string): Promise<DictionaryEntry[]> {
  const { rows } = await db.query<{ entry: DictionaryEntry }>(
    `SELECT d.entry FROM gsb.dictionary_entry d
     JOIN gsb.project p ON d.project_id = COALESCE(p.parent_id, p.id)
     WHERE p.id = $1 ORDER BY d.kind, lower(d.name)`,
    [projectId]
  );
  return rows.map((r) => r.entry);
}
