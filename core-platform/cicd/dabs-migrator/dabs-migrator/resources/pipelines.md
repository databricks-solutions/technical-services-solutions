# Resource: `pipelines`

Spark Declarative Pipelines (SDP) — formerly Lakeflow Declarative Pipelines / Delta Live Tables (DLT). One YAML per pipeline under `resources/pipelines/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#pipeline  
Pipelines API: https://docs.databricks.com/api/workspace/pipelines/create

## Library entry kind: `notebook:` vs `file:`

Pick the entry kind by file extension:

| Source extension | Entry kind |
|---|---|
| `.py` | `notebook:` |
| `.sql` | `file:` |

Mismatching the kind produces:

```
Error: expected a file for "resources.pipelines.<name>.libraries[0].file.path"
```

(or the symmetric `notebook` error). Always match the kind to the file extension — never use `file:` for a Python source, and never use `notebook:` for a `.sql` source.

Mixed example:

```yaml
libraries:
  - notebook:
      path: ../../src/{{ pipeline_name }}/bronze.py
  - file:
      path: ../../src/{{ pipeline_name }}/silver.sql
```

## Why `schema:` and not `target:`

`target` is the legacy DLT field name. New SDP pipelines should use `schema`. Using `target` may still work but emits deprecation warnings and is being phased out.

## Path convention

All `path:` values are relative to the bundle root **resolved via the YAML file's location**. Since pipeline YAMLs live at `resources/pipelines/<name>.yml`, paths to `src/` need **two** `..` segments: `../../src/<name>/...`.

## Source code

**If migrating an existing pipeline:** clone every notebook/script the source pipeline loaded as a library, verbatim, into `src/{{ pipeline_name }}/`. Preserve filenames, decorators, SQL bodies, and comments exactly. Do not replace any block with `# TODO: Replace with actual ingestion logic` or add `# Originally sourced from:` headers. Update each `libraries[].notebook.path` entry above to match the cloned filenames.

**Stubs (only when starting from scratch)** — medallion convention:

- `bronze.py` — raw ingestion (`@dlt.table` reading from sources).
- `silver.py` — cleansed/typed tables.
- `gold.py` — aggregated business tables.

Each should `import dlt` and define `@dlt.table`-decorated functions.

## Common variations

- **Continuous pipeline** — set `continuous: true`; omit any external scheduler.
- **Serverless** — drop the `clusters:` block; set `serverless: true`.
- **SQL pipeline** — replace `.py` libraries with `.sql` files and switch the entry kind to `file:` (one `file:` entry per `.sql` source).

## Complete schema reference

```yaml
resources:
  pipelines:
    <pipeline_name>:
      allow_duplicate_names: <bool>  # bool | If false, deployment will fail if name conflicts with that of another pipeline.
      budget_policy_id: <string>  # string | Budget policy of this pipeline.
      catalog: <string>  # string | A catalog in Unity Catalog to publish data from this pipeline to. If `target` is
      channel: <string>  # string | DLT Release Channel that specifies which version to use.
      clusters:  # array[object] | Cluster settings for this pipeline deployment.
        -
          apply_policy_default_values: <bool>  # bool | Note: This field won't be persisted. Only API users will check this field.
          autoscale:  # object | Parameters needed in order to automatically scale clusters up and down based on
            max_workers: <int>  # REQUIRED | int | The maximum number of workers to which the cluster can scale up when overloaded.
            min_workers: <int>  # REQUIRED | int | The minimum number of workers the cluster can scale down to when underutilized.
            mode: <...(nested)>  # ...(nested) | Databricks Enhanced Autoscaling optimizes cluster utilization by automatically
          aws_attributes:  # object | Attributes related to clusters running on Amazon Web Services.
            availability: <...(nested)>  # ...(nested)
            ebs_volume_count: <int>  # int | The number of volumes launched for each instance. Users can choose up to 10 volu
            ebs_volume_iops: <int>  # int | If using gp3 volumes, what IOPS to use for the disk. If this is not set, the max
            ebs_volume_size: <int>  # int | The size of each EBS volume (in GiB) launched for each instance. For general pur
            ebs_volume_throughput: <int>  # int | If using gp3 volumes, what throughput to use for the disk. If this is not set, t
            ebs_volume_type: <...(nested)>  # ...(nested)
            first_on_demand: <int>  # int | The first `first_on_demand` nodes of the cluster will be placed on on-demand ins
            instance_profile_arn: <string>  # string | Nodes for this cluster will only be placed on AWS instances with this instance p
            spot_bid_price_percent: <int>  # int | The bid price for AWS spot instances, as a percentage of the corresponding insta
            zone_id: <string>  # string | Identifier for the availability zone/datacenter in which the cluster resides.
          azure_attributes:  # object | Attributes related to clusters running on Microsoft Azure.
            availability: <...(nested)>  # ...(nested)
            first_on_demand: <int>  # int | The first `first_on_demand` nodes of the cluster will be placed on on-demand ins
            log_analytics_info: <...(nested)>  # ...(nested) | Defines values necessary to configure and run Azure Log Analytics agent
            spot_bid_max_price: <float>  # float | The max bid price to be used for Azure spot instances.
          cluster_log_conf:  # object | The configuration for delivering spark logs to a long-term storage destination.
            dbfs: <...(nested)>  # ...(nested) | destination needs to be provided. e.g.
            s3: <...(nested)>  # ...(nested) | destination and either the region or endpoint need to be provided. e.g.
            volumes: <...(nested)>  # ...(nested) | destination needs to be provided, e.g.
          custom_tags:  # map[string, string] | Additional tags for cluster resources. Databricks will tag all cluster resources
            <key>: <value>
          driver_instance_pool_id: <string>  # string | The optional ID of the instance pool for the driver of the cluster belongs.
          driver_node_type_id: <string>  # string | The node type of the Spark driver.
          enable_local_disk_encryption: <bool>  # bool | Whether to enable local disk encryption for the cluster.
          gcp_attributes:  # object | Attributes related to clusters running on Google Cloud Platform.
            availability: <...(nested)>  # ...(nested)
            boot_disk_size: <int>  # int | Boot disk size in GB
            first_on_demand: <int>  # int | The first `first_on_demand` nodes of the cluster will be placed on on-demand ins
            google_service_account: <string>  # string | If provided, the cluster will impersonate the google service account when access
            local_ssd_count: <int>  # int | If provided, each node (workers and driver) in the cluster will have this number
            use_preemptible_executors: <bool>  # DEPRECATED | bool | This field determines whether the spark executors will be scheduled to run on pr
            zone_id: <string>  # string | Identifier for the availability zone in which the cluster resides.
          init_scripts:  # array[object] | The configuration for storing init scripts. Any number of destinations can be sp
            -
              abfss: <...(nested)>  # ...(nested) | Contains the Azure Data Lake Storage destination path
              dbfs: <...(nested)>  # DEPRECATED | ...(nested) | destination needs to be provided. e.g.
              file: <...(nested)>  # ...(nested) | destination needs to be provided, e.g.
              gcs: <...(nested)>  # ...(nested) | destination needs to be provided, e.g.
              s3: <...(nested)>  # ...(nested) | destination and either the region or endpoint need to be provided. e.g.
              volumes: <...(nested)>  # ...(nested) | destination needs to be provided. e.g.
              workspace: <...(nested)>  # ...(nested) | destination needs to be provided, e.g.
          instance_pool_id: <string>  # string | The optional ID of the instance pool to which the cluster belongs.
          label: <string>  # string | A label for the cluster specification, either `default` to configure the default
          node_type_id: <string>  # string | This field encodes, through a single value, the resources available to each of
          num_workers: <int>  # int | Number of worker nodes that this cluster should have. A cluster has one Spark Dr
          policy_id: <string>  # string | The ID of the cluster policy used to create the cluster if applicable.
          spark_conf:  # map[string, string] | An object containing a set of optional, user-specified Spark configuration key-v
            <key>: <value>
          spark_env_vars:  # map[string, string] | An object containing a set of optional, user-specified environment variable key-
            <key>: <value>
          ssh_public_keys:  # array[string] | SSH public key contents that will be added to each Spark node in this cluster. T
            - <value>
      configuration:  # map[string, string] | String-String configuration for this pipeline execution.
        <key>: <value>
      continuous: <bool>  # bool | Whether the pipeline is continuous or triggered. This replaces `trigger`.
      development: <bool>  # bool | Whether the pipeline is in Development mode. Defaults to false.
      edition: <string>  # string | Pipeline product edition.
      environment:  # object | Environment specification for this pipeline used to install dependencies.
        dependencies:  # array[string] | List of pip dependencies, as supported by the version of pip in this environment
          - <value>
        environment_version: <string>  # PRIVATE PREVIEW | string | The environment version of the serverless Python environment used to execute
      event_log:  # object | Event log configuration for this pipeline
        catalog: <string>  # string | The UC catalog the event log is published under.
        name: <string>  # string | The name the event log is published to in UC.
        schema: <string>  # string | The UC schema the event log is published under.
      filters:  # object | Filters on which Pipeline packages to include in the deployed graph.
        exclude:  # array[string] | Paths to exclude.
          - <value>
        include:  # array[string] | Paths to include.
          - <value>
      gateway_definition:  # PRIVATE PREVIEW | object | The definition of a gateway pipeline to support change data capture.
        connection_id: <string>  # DEPRECATED | string | [Deprecated, use connection_name instead] Immutable. The Unity Catalog connectio
        connection_name: <string>  # REQUIRED | string | Immutable. The Unity Catalog connection that this gateway pipeline uses to commu
        connection_parameters:  # PRIVATE PREVIEW | object | Optional, Internal. Parameters required to establish an initial connection with
          source_catalog: <string>  # PRIVATE PREVIEW | string | Source catalog for initial connection.
        gateway_storage_catalog: <string>  # REQUIRED | string | Required, Immutable. The name of the catalog for the gateway pipeline's storage
        gateway_storage_name: <string>  # string | Optional. The Unity Catalog-compatible name for the gateway storage location.
        gateway_storage_schema: <string>  # REQUIRED | string | Required, Immutable. The name of the schema for the gateway pipelines's storage
      id: <string>  # string | Unique identifier for this pipeline.
      ingestion_definition:  # object | The configuration for a managed ingestion pipeline. These settings cannot be use
        connection_name: <string>  # string | The Unity Catalog connection that this ingestion pipeline uses to communicate wi
        connector_type: CDC  # PRIVATE PREVIEW | enum: CDC, QUERY_BASED | (Optional) Connector Type for sources. Ex: CDC, Query Based.
        data_staging_options:  # PRIVATE PREVIEW | object | (Optional) Location of staged data storage. This is required for migration from
          catalog_name: <string>  # REQUIRED | string | (Required, Immutable) The name of the catalog for the connector's staging storag
          schema_name: <string>  # REQUIRED | string | (Required, Immutable) The name of the schema for the connector's staging storage
          volume_name: <string>  # string | (Optional) The Unity Catalog-compatible name for the storage location.
        full_refresh_window:  # object | (Optional) A window that specifies a set of time ranges for snapshot queries in
          days_of_week:  # array[...(nested)] | Days of week in which the window is allowed to happen
            - <value>
          start_hour: <int>  # REQUIRED | int | An integer between 0 and 23 denoting the start hour for the window in the 24-hou
          time_zone_id: <string>  # string | Time zone id of window. See https://docs.databricks.com/sql/language-manual/sql-
        ingest_from_uc_foreign_catalog: <bool>  # PRIVATE PREVIEW | bool | Immutable. If set to true, the pipeline will ingest tables from the
        ingestion_gateway_id: <string>  # string | Identifier for the gateway that is used by this ingestion pipeline to communicat
        netsuite_jar_path: <string>  # PRIVATE PREVIEW | string
        objects:  # array[object] | Required. Settings specifying tables to replicate and the destination for the re
          -
            report: <...(nested)>  # ...(nested) | Select a specific source report.
            schema: <...(nested)>  # ...(nested) | Select all tables from a specific source schema.
            table: <...(nested)>  # ...(nested) | Select a specific source table.
        source_configurations:  # array[object] | Top-level source configurations
          -
            catalog: <...(nested)>  # ...(nested) | Catalog-level source configuration parameters
        table_configuration:  # object | Configuration settings to control the ingestion of tables. These settings are ap
          auto_full_refresh_policy:  # object | (Optional, Mutable) Policy for auto full refresh, if enabled pipeline will autom
            enabled: <...(nested)>  # REQUIRED | ...(nested) | (Required, Mutable) Whether to enable auto full refresh or not.
            min_interval_hours: <...(nested)>  # ...(nested) | (Optional, Mutable) Specify the minimum interval in hours between the timestamp
          exclude_columns:  # array[string] | A list of column names to be excluded for the ingestion.
            - <value>
          include_columns:  # array[string] | A list of column names to be included for the ingestion.
            - <value>
          primary_keys:  # array[string] | The primary key of the table used to apply changes.
            - <value>
          query_based_connector_config:  # PRIVATE PREVIEW | object | Configurations that are only applicable for query-based ingestion connectors.
            cursor_columns: <...(nested)>  # PRIVATE PREVIEW | ...(nested) | The names of the monotonically increasing columns in the source table that are u
            deletion_condition: <...(nested)>  # PRIVATE PREVIEW | ...(nested) | Specifies a SQL WHERE condition that specifies that the source row has been dele
            hard_deletion_sync_min_interval_in_seconds: <...(nested)>  # PRIVATE PREVIEW | ...(nested) | Specifies the minimum interval (in seconds) between snapshots on primary keys
          row_filter: <string>  # PRIVATE PREVIEW | string | (Optional, Immutable) The row filter condition to be applied to the table.
          salesforce_include_formula_fields: <bool>  # PRIVATE PREVIEW | bool | If true, formula fields defined in the table are included in the ingestion. This
          scd_type: SCD_TYPE_1  # PRIVATE PREVIEW | enum: SCD_TYPE_1, SCD_TYPE_2, APPEND_ONLY | The SCD type to use to ingest the table.
          sequence_by:  # array[string] | The column names specifying the logical order of events in the source data. Spar
            - <value>
          workday_report_parameters:  # PRIVATE PREVIEW | object
            incremental: <...(nested)>  # DEPRECATED | ...(nested) | (Optional) Marks the report as incremental.
            parameters: <...(nested)>  # ...(nested) | Parameters for the Workday report. Each key represents the parameter name (e.g.,
            report_parameters: <...(nested)>  # DEPRECATED | ...(nested) | (Optional) Additional custom parameters for Workday Report
      libraries:  # array[object] | Libraries or code needed by this deployment.
        -
          file:  # object | The path to a file that defines a pipeline and is stored in the Databricks Repos
            path: <string>  # string | The absolute path of the source code.
          glob:  # object | The unified field to include source codes.
            include: <string>  # string | The source code to include for pipelines
          jar: <string>  # PRIVATE PREVIEW | string | URI of the jar to be installed. Currently only DBFS is supported.
          maven:  # PRIVATE PREVIEW | object | Specification of a maven library to be installed.
            coordinates: <string>  # REQUIRED | string | Gradle-style maven coordinates. For example: "org.jsoup:jsoup:1.7.2".
            exclusions:  # array[...(nested)] | List of dependences to exclude. For example: `["slf4j:slf4j", "*:hadoop-client"]
              - <value>
            repo: <string>  # string | Maven repo to install the Maven package from. If omitted, both Maven Central Rep
          notebook:  # object | The path to a notebook that defines a pipeline and is stored in the Databricks w
            path: <string>  # string | The absolute path of the source code.
          whl: <string>  # DEPRECATED | string | URI of the whl to be installed.
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # string | Friendly identifier for this pipeline.
      notifications:  # array[object] | List of notification settings for this pipeline.
        -
          alerts:  # array[string] | A list of alerts that trigger the sending of notifications to the configured
            - <value>
          email_recipients:  # array[string] | A list of email addresses notified when a configured alert is triggered.
            - <value>
      permissions:  # array[object]
        -
          group_name: <string>  # string
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, IS_OWNER, CAN_RUN, CAN_VIEW
          service_principal_name: <string>  # string
          user_name: <string>  # string
      photon: <bool>  # bool | Whether Photon is enabled for this pipeline.
      restart_window:  # PRIVATE PREVIEW | object | Restart window of this pipeline.
        days_of_week:  # array[enum] | Days of week in which the restart is allowed to happen (within a five-hour windo
          - <value>
        start_hour: <int>  # REQUIRED | int | An integer between 0 and 23 denoting the start hour for the restart window in th
        time_zone_id: <string>  # string | Time zone id of restart window. See https://docs.databricks.com/sql/language-man
      root_path: <string>  # string | Root path for this pipeline.
      run_as:  # object
        service_principal_name: <string>  # string | Application ID of an active service principal. Setting this field requires the `
        user_name: <string>  # string | The email of an active workspace user. Users can only set this field to their ow
      schema: <string>  # string | The default schema (database) where tables are read from or published to.
      serverless: <bool>  # bool | Whether serverless compute is enabled for this pipeline.
      storage: <string>  # string | DBFS root directory for storing checkpoints and tables.
      tags:  # map[string, string] | A map of tags associated with the pipeline.
        <key>: <value>
      target: <string>  # DEPRECATED | string | Target schema (database) to add tables in this pipeline to. Exactly one of `sche
      trigger:  # DEPRECATED | object | Which pipeline trigger to use. Deprecated: Use `continuous` instead.
        cron:  # object
          quartz_cron_schedule: <string>  # string
          timezone_id: <string>  # string
        manual:  # object
      usage_policy_id: <string>  # PRIVATE PREVIEW | string | Usage policy of this pipeline.
```

## What to ask the user

- Catalog and target schema?
- Triggered or continuous?
- Serverless or classic compute?
