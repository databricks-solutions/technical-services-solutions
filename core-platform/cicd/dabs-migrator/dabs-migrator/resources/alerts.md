# Resource: `alerts`

SQL Alerts (Alerts V2) — monitor query results and notify on threshold breaches.

Docs: https://docs.databricks.com/api/workspace/alertsv2/createalert

## Migration guidance

Resolve the id, then read the alert (redirect stderr before `jq` so a proxied CLI banner can't corrupt the JSON):

```bash
databricks alerts-v2 list-alerts -p <profile> -o json 2>/dev/null | jq -r '.[] | select(.display_name=="<name>") | .id'
databricks alerts-v2 get-alert <id> -p <profile> -o json 2>/dev/null
```

- `warehouse_id` comes back from a live read as a concrete ID (e.g. `3d885699…`). Replace it with `${var.warehouse_id}` and declare the variable — never inline the raw ID.
- `query_text` is read back with fully-qualified table names. Parameterize the catalog and schema with `${var.catalog}` / `${var.schema}` (e.g. `SELECT count(*) FROM ${var.catalog}.${var.schema}.<table>`) rather than hardcoding them.
- Preserve `schedule.pause_status` exactly as the source alert has it (`PAUSED` or `UNPAUSED`). Omitting it silently flips a paused alert to active.
- **Omit `evaluation.notification` entirely unless it has real content.** A live read returns the `notification` key even when the alert has no subscriptions, so a naive copy produces an empty `evaluation.notification: {}`. That passes `bundle validate` but the create API rejects it: `evaluation.notification is provided but doesn't contain any value, please remove this field if you don't want to set it (400 INVALID_PARAMETER_VALUE)`. Only emit `notification` when it carries `subscriptions` (or `notify_on_ok`/`retrigger_seconds`); otherwise drop the whole key. The same "drop empty optional sub-objects" rule applies to any block you'd otherwise serialize as `{}`.

## Complete schema reference

Required fields: `display_name`, `evaluation`, `query_text`, `schedule`, `warehouse_id`

```yaml
resources:
  alerts:
    <alert_name>:
      custom_description: <string>  # string | Custom description for the alert. support mustache template.
      custom_summary: <string>  # string | Custom summary for the alert. support mustache template.
      display_name: <string>  # REQUIRED | string | The display name of the alert.
      evaluation:  # REQUIRED | object
        comparison_operator: LESS_THAN  # REQUIRED | enum: LESS_THAN, GREATER_THAN, EQUAL, NOT_EQUAL, GREATER_THAN_OR_EQUAL, LESS_THAN_OR_EQUAL, ... | Operator used for comparison in alert evaluation.
        empty_result_state: UNKNOWN  # enum: UNKNOWN, TRIGGERED, OK, ERROR | Alert state if result is empty. Please avoid setting this field to be `UNKNOWN`
        notification:  # object | User or Notification Destination to notify when alert is triggered.
          notify_on_ok: <bool>  # bool | Whether to notify alert subscribers when alert returns back to normal.
          retrigger_seconds: <int>  # int | Number of seconds an alert waits after being triggered before it is allowed to s
          subscriptions:  # array[object]
            -
              destination_id: <string>  # string
              user_email: <string>  # string
        source:  # REQUIRED | object | Source column from result to use to evaluate alert
          aggregation: SUM  # enum: SUM, COUNT, COUNT_DISTINCT, AVG, MEDIAN, MIN, ... | If not set, the behavior is equivalent to using `First row` in the UI.
          display: <string>  # string
          name: <string>  # REQUIRED | string
        threshold:  # object | Threshold to user for alert evaluation, can be a column or a value.
          column:  # object
            aggregation: SUM  # enum: SUM, COUNT, COUNT_DISTINCT, AVG, MEDIAN, MIN, ... | If not set, the behavior is equivalent to using `First row` in the UI.
            display: <string>  # string
            name: <string>  # REQUIRED | string
          value:  # object
            bool_value: <bool>  # bool
            double_value: <float>  # float
            string_value: <string>  # string
      file_path: <string>  # string
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      parent_path: <string>  # string | The workspace path of the folder containing the alert. Can only be set on create
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW, ... | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      query_text: <string>  # REQUIRED | string | Text of the query to be run.
      run_as:  # object | Specifies the identity that will be used to run the alert.
        service_principal_name: <string>  # string | Application ID of an active service principal. Setting this field requires the `
        user_name: <string>  # string | The email of an active workspace user. Can only set this field to their own emai
      run_as_user_name: <string>  # DEPRECATED | string | The run as username or application ID of service principal.
      schedule:  # REQUIRED | object
        pause_status: UNPAUSED  # enum: UNPAUSED, PAUSED | Indicate whether this schedule is paused or not.
        quartz_cron_schedule: <string>  # REQUIRED | string | A cron expression using quartz syntax that specifies the schedule for this pipel
        timezone_id: <string>  # REQUIRED | string | A Java timezone id. The schedule will be resolved using this timezone.
      warehouse_id: <string>  # REQUIRED | string | ID of the SQL warehouse attached to the alert.
```

## What to ask the user

- Query and threshold (operator + value)?
- Schedule cron + timezone?
- Notification recipients (emails or destination IDs)?
