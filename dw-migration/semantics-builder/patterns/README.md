# Pattern library

Each folder is one pattern. The app loads every folder at startup and skips (with a log line) a folder that is not valid.

| File              | Content                                                                                                                                                             |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pattern.yml`     | `title`, `category`, `scenario`, `question`, `roles` (the columns a user maps in "Apply to my data"), `test.query` with a `{{view}}` placeholder, optional `minDbr` |
| `metric_view.yml` | The metric view YAML. Must pass the app's validator with no errors.                                                                                                 |
| `expected.json`   | The test query result on the sample data. Do not edit by hand.                                                                                                      |

The folder name is the pattern id: lowercase letters, digits and `_`.

## Add or change a pattern

1. Create the folder with `pattern.yml` and `metric_view.yml`. Use `samples.tpch` or `samples.tpcds_sf1`, or a SQL query source for reference data that the samples do not have.
2. Run it on a warehouse. This writes `expected.json`:

   ```bash
   pnpm tsx scripts/run-patterns.ts --profile <PROFILE> --warehouse <WAREHOUSE_ID> --sandbox <catalog.schema> <slug>
   ```

3. Check the numbers in `expected.json` by hand, then run `pnpm test`.

## Attribution

The categories follow [databricks-solutions/uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns). The YAML in this folder is original work for this app.
