# Resource: `alerts`

SQL Alerts (Alerts V2) — monitor query results and notify on threshold breaches.

Docs: https://docs.databricks.com/api/workspace/alertsv2/createalert

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
