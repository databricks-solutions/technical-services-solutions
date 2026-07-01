# Resource: `quality_monitors`

Lakehouse Monitoring — data/ML quality monitors on UC tables.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#quality_monitor

## Complete schema reference

Required fields: `assets_dir`, `output_schema_name`, `table_name`

```yaml
resources:
  quality_monitors:
    <quality_monitor_name>:
      assets_dir: <string>  # REQUIRED | string | [Create:REQ Update:IGN] Field for specifying the absolute path to a custom direc
      baseline_table_name: <string>  # string | [Create:OPT Update:OPT] Baseline table name.
      custom_metrics:  # array[object] | [Create:OPT Update:OPT] Custom metrics.
        -
          definition: <string>  # REQUIRED | string | Jinja template for a SQL expression that specifies how to compute the metric. Se
          input_columns:  # REQUIRED | array[string] | A list of column names in the input table the metric should be computed for.
            - <value>
          name: <string>  # REQUIRED | string | Name of the metric in the output tables.
          output_data_type: <string>  # REQUIRED | string | The output type of the custom metric.
          type: CUSTOM_METRIC_TYPE_AGGREGATE  # REQUIRED | enum: CUSTOM_METRIC_TYPE_AGGREGATE, CUSTOM_METRIC_TYPE_DERIVED, CUSTOM_METRIC_TYPE_DRIFT | Can only be one of ``"CUSTOM_METRIC_TYPE_AGGREGATE"``, ``"CUSTOM_METRIC_TYPE_DER
      data_classification_config:  # PRIVATE PREVIEW | object | [Create:OPT Update:OPT] Data classification related config.
        enabled: <bool>  # PRIVATE PREVIEW | bool | Whether to enable data classification.
      inference_log:  # object
        granularities:  # REQUIRED | array[string] | Granularities for aggregating data into time windows based on their timestamp. V
          - <value>
        label_col: <string>  # string | Column for the label.
        model_id_col: <string>  # REQUIRED | string | Column for the model identifier.
        prediction_col: <string>  # REQUIRED | string | Column for the prediction.
        prediction_proba_col: <string>  # string | Column for prediction probabilities
        problem_type: PROBLEM_TYPE_CLASSIFICATION  # REQUIRED | enum: PROBLEM_TYPE_CLASSIFICATION, PROBLEM_TYPE_REGRESSION | Problem type the model aims to solve.
        timestamp_col: <string>  # REQUIRED | string | Column for the timestamp.
      latest_monitor_failure_msg: <string>  # string | [Create:ERR Update:IGN] The latest error message for a monitor failure.
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      notifications:  # object | [Create:OPT Update:OPT] Field for specifying notification settings.
        on_failure:  # object | Destinations to send notifications on failure/timeout.
          email_addresses:  # array[string] | The list of email addresses to send the notification to. A maximum of 5 email ad
            - <value>
        on_new_classification_tag_detected:  # PRIVATE PREVIEW | object | Destinations to send notifications on new classification tag detected.
          email_addresses:  # array[string] | The list of email addresses to send the notification to. A maximum of 5 email ad
            - <value>
      output_schema_name: <string>  # REQUIRED | string | [Create:REQ Update:REQ] Schema where output tables are created. Needs to be in 2
      schedule:  # object | [Create:OPT Update:OPT] The monitor schedule.
        pause_status: UNSPECIFIED  # enum: UNSPECIFIED, UNPAUSED, PAUSED | Read only field that indicates whether a schedule is paused or not.
        quartz_cron_expression: <string>  # REQUIRED | string | The expression that determines when to run the monitor. See [examples](https://w
        timezone_id: <string>  # REQUIRED | string | The timezone id (e.g., ``PST``) in which to evaluate the quartz expression.
      skip_builtin_dashboard: <bool>  # bool | Whether to skip creating a default dashboard summarizing data quality metrics.
      slicing_exprs:  # array[string] | [Create:OPT Update:OPT] List of column expressions to slice data with for target
        - <value>
      snapshot:  # map[string, string] | Configuration for monitoring snapshot tables.
        <key>: <value>
      table_name: <string>  # REQUIRED | string
      time_series:  # object | Configuration for monitoring time series tables.
        granularities:  # REQUIRED | array[string] | Granularities for aggregating data into time windows based on their timestamp. V
          - <value>
        timestamp_col: <string>  # REQUIRED | string | Column for the timestamp.
      warehouse_id: <string>  # string | Optional argument to specify the warehouse for dashboard creation. If not specif
```

## What to ask the user

- Monitor type (snapshot, time series, inference log)?
- Granularity and timestamp column (if time series)?
