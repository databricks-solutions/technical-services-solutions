# Resource: `jobs`

Scheduled or triggered Databricks Jobs (Workflows). One YAML per job under `resources/jobs/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#job  
Job API: https://docs.databricks.com/api/workspace/jobs/create

## Source code

**If migrating an existing job:** clone the original notebook(s) and any referenced scripts verbatim into `src/{{ job_name }}/`. Keep filenames, comments, and logic intact. Do not insert `# TODO` placeholders or `# Originally sourced from:` headers — the user's working code must survive the migration unchanged. Update the `notebook_path` / `sql_task.file.path` entries above to match the cloned filenames.

**Stubs (only when starting from scratch):**

- `notebook.py` — entrypoint notebook referenced by the task above.
- Add `.sql` / `.py` files for additional tasks; reference each via its own task block.

## Common variations

- **Multi-task** — add more entries to `tasks:`, use `depends_on:` for ordering.
- **SQL task** — replace `notebook_task` with `sql_task: { warehouse_id: <warehouse_id>, file: { path: ../../src/{{ job_name }}/query.sql } }`.
- **Python wheel task** — `python_wheel_task: { package_name: ..., entry_point: ... }` with the wheel in `environments`.
- **Triggered (no schedule)** — omit the `schedule:` block; trigger via API or another job.

## Complete schema reference

```yaml
resources:
  jobs:
    <job_name>:
      budget_policy_id: <string>  # string | The id of the user specified budget policy to use for this job.
      continuous:  # object | An optional continuous property for this job. The continuous property will ensur
        pause_status: UNPAUSED  # enum: UNPAUSED, PAUSED | Indicate whether the continuous execution of the job is paused or not. Defaults
        task_retry_mode: NEVER  # enum: NEVER, ON_FAILURE | Indicate whether the continuous job is applying task level retries or not. Defau
      description: <string>  # string | An optional description for the job. The maximum length is 27700 characters in U
      email_notifications:  # object | An optional set of email addresses that is notified when runs of this job begin
        no_alert_for_skipped_runs: <bool>  # DEPRECATED | bool | If true, do not send email to recipients specified in `on_failure` if the run is
        on_duration_warning_threshold_exceeded:  # array[string] | A list of email addresses to be notified when the duration of a run exceeds the
          - <value>
        on_failure:  # array[string] | A list of email addresses to be notified when a run unsuccessfully completes. A
          - <value>
        on_start:  # array[string] | A list of email addresses to be notified when a run begins. If not specified on
          - <value>
        on_streaming_backlog_exceeded:  # array[string] | A list of email addresses to notify when any streaming backlog thresholds are ex
          - <value>
        on_success:  # array[string] | A list of email addresses to be notified when a run successfully completes. A ru
          - <value>
      environments:  # array[object] | A list of task execution environment specifications that can be referenced by se
        -
          environment_key: <string>  # REQUIRED | string | The key of an environment. It has to be unique within a job.
          spec:  # object
            base_environment: <string>  # string | The base environment this environment is built on top of. A base environment def
            client: <string>  # DEPRECATED | string | Use `environment_version` instead.
            dependencies:  # array[...(nested)] | List of pip dependencies, as supported by the version of pip in this environment
              - <value>
            environment_version: <string>  # string | Either `environment_version` or `base_environment` needs to be provided. Environ
            java_dependencies:  # array[...(nested)]
              - <value>
      git_source:  # object | An optional specification for a remote Git repository containing the source code
        git_branch: <string>  # string | Name of the branch to be checked out and used by this job. This field cannot be
        git_commit: <string>  # string | Commit to be checked out and used by this job. This field cannot be specified in
        git_provider: gitHub  # REQUIRED | enum: gitHub, bitbucketCloud, azureDevOpsServices, gitHubEnterprise, bitbucketServer, gitLab, ... | Unique identifier of the service used to host the Git repository. The value is c
        git_tag: <string>  # string | Name of the tag to be checked out and used by this job. This field cannot be spe
        git_url: <string>  # REQUIRED | string | URL of the repository to be cloned by this job.
        sparse_checkout:  # object
          patterns:  # array[string] | List of patterns to include for sparse checkout.
            - <value>
      health:  # object
        rules:  # array[object]
          -
            metric: <...(nested)>  # REQUIRED | ...(nested)
            op: <...(nested)>  # REQUIRED | ...(nested)
            value: <int>  # REQUIRED | int | Specifies the threshold value that the health metric should obey to satisfy the
      job_clusters:  # array[object] | A list of job cluster specifications that can be shared and reused by tasks of t
        -
          job_cluster_key: <string>  # REQUIRED | string | A unique name for the job cluster. This field is required and must be unique wit
          new_cluster:  # REQUIRED | object | If new_cluster, a description of a cluster that is created for each task.
            apply_policy_default_values: <bool>  # bool | When set to true, fixed and default values from the policy will be used for fiel
            autoscale: <...(nested)>  # ...(nested) | Parameters needed in order to automatically scale clusters up and down based on
            autotermination_minutes: <int>  # int | Automatically terminates the cluster after it is inactive for this time in minut
            aws_attributes: <...(nested)>  # ...(nested) | Attributes related to clusters running on Amazon Web Services.
            azure_attributes: <...(nested)>  # ...(nested) | Attributes related to clusters running on Microsoft Azure.
            cluster_log_conf: <...(nested)>  # ...(nested) | The configuration for delivering spark logs to a long-term storage destination.
            cluster_name: <string>  # string | Cluster name requested by the user. This doesn't have to be unique.
            custom_tags:  # map[string, string] | Additional tags for cluster resources. Databricks will tag all cluster resources
              <key>: <value>
            data_security_mode: <...(nested)>  # ...(nested)
            docker_image: <...(nested)>  # ...(nested)
            driver_instance_pool_id: <string>  # string | The optional ID of the instance pool for the driver of the cluster belongs.
            driver_node_type_flexibility: <...(nested)>  # ...(nested) | Flexible node type configuration for the driver node.
            driver_node_type_id: <string>  # string | The node type of the Spark driver.
            enable_elastic_disk: <bool>  # bool | Autoscaling Local Storage: when enabled, this cluster will dynamically acquire a
            enable_local_disk_encryption: <bool>  # bool | Whether to enable LUKS on cluster VMs' local disks
            gcp_attributes: <...(nested)>  # ...(nested) | Attributes related to clusters running on Google Cloud Platform.
            init_scripts:  # array[...(nested)] | The configuration for storing init scripts. Any number of destinations can be sp
              - <value>
            instance_pool_id: <string>  # string | The optional ID of the instance pool to which the cluster belongs.
            is_single_node: <bool>  # bool | This field can only be used when `kind = CLASSIC_PREVIEW`.
            kind: <...(nested)>  # ...(nested)
            node_type_id: <string>  # string | This field encodes, through a single value, the resources available to each of
            num_workers: <int>  # int | Number of worker nodes that this cluster should have. A cluster has one Spark Dr
            policy_id: <string>  # string | The ID of the cluster policy used to create the cluster if applicable.
            remote_disk_throughput: <int>  # int | If set, what the configurable throughput (in Mb/s) for the remote disk is. Curre
            runtime_engine: <...(nested)>  # ...(nested)
            single_user_name: <string>  # string | Single user name if data_security_mode is `SINGLE_USER`
            spark_conf:  # map[string, string] | An object containing a set of optional, user-specified Spark configuration key-v
              <key>: <value>
            spark_env_vars:  # map[string, string] | An object containing a set of optional, user-specified environment variable key-
              <key>: <value>
            spark_version: <string>  # string | The Spark version of the cluster, e.g. `3.3.x-scala2.11`.
            ssh_public_keys:  # array[...(nested)] | SSH public key contents that will be added to each Spark node in this cluster. T
              - <value>
            total_initial_remote_disk_size: <int>  # int | If set, what the total initial volume size (in GB) of the remote disks should be
            use_ml_runtime: <bool>  # bool | This field can only be used when `kind = CLASSIC_PREVIEW`.
            worker_node_type_flexibility: <...(nested)>  # ...(nested) | Flexible node type configuration for worker nodes.
            workload_type: <...(nested)>  # ...(nested)
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      max_concurrent_runs: <int>  # int | An optional maximum allowed number of concurrent runs of the job.
      name: <string>  # string | An optional name for the job. The maximum length is 4096 bytes in UTF-8 encoding
      notification_settings:  # object | Optional notification settings that are used when sending notifications to each
        no_alert_for_canceled_runs: <bool>  # bool | If true, do not send notifications to recipients specified in `on_failure` if th
        no_alert_for_skipped_runs: <bool>  # bool | If true, do not send notifications to recipients specified in `on_failure` if th
      parameters:  # array[object] | Job-level parameter definitions
        -
          default: <string>  # REQUIRED | string | Default value of the parameter.
          name: <string>  # REQUIRED | string | The name of the defined parameter. May only contain alphanumeric characters, `_`
      performance_target: PERFORMANCE_OPTIMIZED  # enum: PERFORMANCE_OPTIMIZED, STANDARD | The performance mode on a serverless job. This field determines the level of com
      permissions:  # array[object]
        -
          group_name: <string>  # string
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW
          service_principal_name: <string>  # string
          user_name: <string>  # string
      queue:  # object | The queue settings of the job.
        enabled: <bool>  # REQUIRED | bool | If true, enable queueing for the job. This is a required field.
      run_as:  # object
        group_name: <string>  # PRIVATE PREVIEW | string | Group name of an account group assigned to the workspace. Setting this field req
        service_principal_name: <string>  # string | The application ID of an active service principal. Setting this field requires t
        user_name: <string>  # string | The email of an active workspace user. Non-admin users can only set this field t
      schedule:  # object | An optional periodic schedule for this job. The default behavior is that the job
        pause_status: UNPAUSED  # enum: UNPAUSED, PAUSED | Indicate whether this schedule is paused or not.
        quartz_cron_expression: <string>  # REQUIRED | string | A Cron expression using Quartz syntax that describes the schedule for a job. See
        timezone_id: <string>  # REQUIRED | string | A Java timezone ID. The schedule for a job is resolved with respect to this time
      tags:  # map[string, string] | A map of tags associated with the job. These are forwarded to the cluster as clu
        <key>: <value>
      tasks:  # array[object] | A list of task specifications to be executed by this job.
        -
          alert_task:  # object | The task evaluates a Databricks alert and sends notifications to subscribers
            alert_id: <string>  # string | The alert_id is the canonical identifier of the alert.
            subscribers:  # array[...(nested)] | The subscribers receive alert evaluation result notifications after the alert ta
              - <value>
            warehouse_id: <string>  # string | The warehouse_id identifies the warehouse settings used by the alert task.
            workspace_path: <string>  # string | The workspace_path is the path to the alert file in the workspace. The path:
          clean_rooms_notebook_task:  # object | The task runs a [clean rooms](https://docs.databricks.com/clean-rooms/index.html
            clean_room_name: <string>  # REQUIRED | string | The clean room that the notebook belongs to.
            etag: <string>  # string | Checksum to validate the freshness of the notebook resource (i.e. the notebook b
            notebook_base_parameters:  # map[string, string] | Base parameters to be used for the clean room notebook job.
              <key>: <value>
            notebook_name: <string>  # REQUIRED | string | Name of the notebook being run.
          compute:  # object | Task level compute configuration.
            hardware_accelerator: <...(nested)>  # ...(nested) | Hardware accelerator configuration for Serverless GPU workloads.
          condition_task:  # object | The task evaluates a condition that can be used to control the execution of othe
            left: <string>  # REQUIRED | string | The left operand of the condition task. Can be either a string value or a job st
            op: <...(nested)>  # REQUIRED | ...(nested) | * `EQUAL_TO`, `NOT_EQUAL` operators perform string comparison of their operands.
            right: <string>  # REQUIRED | string | The right operand of the condition task. Can be either a string value or a job s
          dashboard_task:  # object | The task refreshes a dashboard and sends a snapshot to subscribers.
            dashboard_id: <string>  # string
            filters:  # PRIVATE PREVIEW | map[string, string] | Dashboard task parameters. Used to apply dashboard filter values during dashboar
              <key>: <value>
            subscription: <...(nested)>  # ...(nested)
            warehouse_id: <string>  # string | Optional: The warehouse id to execute the dashboard with for the schedule.
          dbt_cloud_task:  # DEPRECATED | PRIVATE PREVIEW | object | Task type for dbt cloud, deprecated in favor of the new name dbt_platform_task
            connection_resource_name: <string>  # string | The resource name of the UC connection that authenticates the dbt Cloud for this
            dbt_cloud_job_id: <int>  # int | Id of the dbt Cloud job to be triggered
          dbt_platform_task:  # PRIVATE PREVIEW | object
            connection_resource_name: <string>  # string | The resource name of the UC connection that authenticates the dbt platform for t
            dbt_platform_job_id: <string>  # string | Id of the dbt platform job to be triggered. Specified as a string for maximum co
          dbt_task:  # object | The task runs one or more dbt commands when the `dbt_task` field is present. The
            catalog: <string>  # string | Optional name of the catalog to use. The value is the top level in the 3-level n
            commands:  # REQUIRED | array[...(nested)] | A list of dbt commands to execute. All commands must start with `dbt`. This para
              - <value>
            profiles_directory: <string>  # string | Optional (relative) path to the profiles directory. Can only be specified if no
            project_directory: <string>  # string | Path to the project directory. Optional for Git sourced tasks, in which
            schema: <string>  # string | Optional schema to write to. This parameter is only used when a warehouse_id is
            source: <...(nested)>  # ...(nested) | Optional location type of the project directory. When set to `WORKSPACE`, the pr
            warehouse_id: <string>  # string | ID of the SQL warehouse to connect to. If provided, we automatically generate an
          depends_on:  # array[object] | An optional array of objects specifying the dependency graph of the task. All ta
            -
              outcome: <...(nested)>  # ...(nested) | Can only be specified on condition task dependencies. The outcome of the depende
              task_key: <...(nested)>  # REQUIRED | ...(nested) | The name of the task this task depends on.
          description: <string>  # string | An optional description for this task.
          disable_auto_optimization: <bool>  # bool | An option to disable auto optimization in serverless
          disabled: <bool>  # PRIVATE PREVIEW | bool | An optional flag to disable the task. If set to true, the task will not run even
          email_notifications:  # object | An optional set of email addresses that is notified when runs of this task begin
            no_alert_for_skipped_runs: <bool>  # DEPRECATED | bool | If true, do not send email to recipients specified in `on_failure` if the run is
            on_duration_warning_threshold_exceeded:  # array[...(nested)] | A list of email addresses to be notified when the duration of a run exceeds the
              - <value>
            on_failure:  # array[...(nested)] | A list of email addresses to be notified when a run unsuccessfully completes. A
              - <value>
            on_start:  # array[...(nested)] | A list of email addresses to be notified when a run begins. If not specified on
              - <value>
            on_streaming_backlog_exceeded:  # array[...(nested)] | A list of email addresses to notify when any streaming backlog thresholds are ex
              - <value>
            on_success:  # array[...(nested)] | A list of email addresses to be notified when a run successfully completes. A ru
              - <value>
          environment_key: <string>  # string | The key that references an environment spec in a job. This field is required for
          existing_cluster_id: <string>  # string | If existing_cluster_id, the ID of an existing cluster that is used for all runs.
          for_each_task:  # object | The task executes a nested task for every input provided when the `for_each_task
            concurrency: <int>  # int | An optional maximum allowed number of concurrent runs of the task.
            inputs: <string>  # REQUIRED | string | Array for task to iterate on. This can be a JSON string or a reference to
            task: <...(circular)>  # REQUIRED | ...(circular) | Configuration for the task that will be run for each element in the array
          gen_ai_compute_task:  # PRIVATE PREVIEW | object
            command: <string>  # string | Command launcher to run the actual script, e.g. bash, python etc.
            compute: <...(nested)>  # ...(nested)
            dl_runtime_image: <string>  # REQUIRED | string | Runtime image
            mlflow_experiment_name: <string>  # string | Optional string containing the name of the MLflow experiment to log the run to.
            source: <...(nested)>  # ...(nested) | Optional location type of the training script. When set to `WORKSPACE`, the scri
            training_script_path: <string>  # string | The training script file path to be executed. Cloud file URIs (such as dbfs:/, s
            yaml_parameters: <string>  # string | Optional string containing model parameters passed to the training script in yam
            yaml_parameters_file_path: <string>  # string | Optional path to a YAML file containing model parameters passed to the training
          health:  # object
            rules:  # array[...(nested)]
              - <value>
          job_cluster_key: <string>  # string | If job_cluster_key, this task is executed reusing the cluster specified in `job.
          libraries:  # array[object] | An optional list of libraries to be installed on the cluster.
            -
              cran: <...(nested)>  # ...(nested) | Specification of a CRAN library to be installed as part of the library
              egg: <...(nested)>  # DEPRECATED | ...(nested) | Deprecated. URI of the egg library to install. Installing Python egg files is de
              jar: <...(nested)>  # ...(nested) | URI of the JAR library to install. Supported URIs include Workspace paths, Unity
              maven: <...(nested)>  # ...(nested) | Specification of a maven library to be installed. For example:
              pypi: <...(nested)>  # ...(nested) | Specification of a PyPi library to be installed. For example:
              requirements: <...(nested)>  # ...(nested) | URI of the requirements.txt file to install. Only Workspace paths and Unity Cata
              whl: <...(nested)>  # ...(nested) | URI of the wheel library to install. Supported URIs include Workspace paths, Uni
          max_retries: <int>  # int | An optional maximum number of times to retry an unsuccessful run. A run is consi
          min_retry_interval_millis: <int>  # int | An optional minimal interval in milliseconds between the start of the failed run
          new_cluster:  # object | If new_cluster, a description of a new cluster that is created for each run.
            apply_policy_default_values: <bool>  # bool | When set to true, fixed and default values from the policy will be used for fiel
            autoscale: <...(nested)>  # ...(nested) | Parameters needed in order to automatically scale clusters up and down based on
            autotermination_minutes: <int>  # int | Automatically terminates the cluster after it is inactive for this time in minut
            aws_attributes: <...(nested)>  # ...(nested) | Attributes related to clusters running on Amazon Web Services.
            azure_attributes: <...(nested)>  # ...(nested) | Attributes related to clusters running on Microsoft Azure.
            cluster_log_conf: <...(nested)>  # ...(nested) | The configuration for delivering spark logs to a long-term storage destination.
            cluster_name: <string>  # string | Cluster name requested by the user. This doesn't have to be unique.
            custom_tags:  # map[string, string] | Additional tags for cluster resources. Databricks will tag all cluster resources
              <key>: <value>
            data_security_mode: <...(nested)>  # ...(nested)
            docker_image: <...(nested)>  # ...(nested)
            driver_instance_pool_id: <string>  # string | The optional ID of the instance pool for the driver of the cluster belongs.
            driver_node_type_flexibility: <...(nested)>  # ...(nested) | Flexible node type configuration for the driver node.
            driver_node_type_id: <string>  # string | The node type of the Spark driver.
            enable_elastic_disk: <bool>  # bool | Autoscaling Local Storage: when enabled, this cluster will dynamically acquire a
            enable_local_disk_encryption: <bool>  # bool | Whether to enable LUKS on cluster VMs' local disks
            gcp_attributes: <...(nested)>  # ...(nested) | Attributes related to clusters running on Google Cloud Platform.
            init_scripts:  # array[...(nested)] | The configuration for storing init scripts. Any number of destinations can be sp
              - <value>
            instance_pool_id: <string>  # string | The optional ID of the instance pool to which the cluster belongs.
            is_single_node: <bool>  # bool | This field can only be used when `kind = CLASSIC_PREVIEW`.
            kind: <...(nested)>  # ...(nested)
            node_type_id: <string>  # string | This field encodes, through a single value, the resources available to each of
            num_workers: <int>  # int | Number of worker nodes that this cluster should have. A cluster has one Spark Dr
            policy_id: <string>  # string | The ID of the cluster policy used to create the cluster if applicable.
            remote_disk_throughput: <int>  # int | If set, what the configurable throughput (in Mb/s) for the remote disk is. Curre
            runtime_engine: <...(nested)>  # ...(nested)
            single_user_name: <string>  # string | Single user name if data_security_mode is `SINGLE_USER`
            spark_conf:  # map[string, string] | An object containing a set of optional, user-specified Spark configuration key-v
              <key>: <value>
            spark_env_vars:  # map[string, string] | An object containing a set of optional, user-specified environment variable key-
              <key>: <value>
            spark_version: <string>  # string | The Spark version of the cluster, e.g. `3.3.x-scala2.11`.
            ssh_public_keys:  # array[...(nested)] | SSH public key contents that will be added to each Spark node in this cluster. T
              - <value>
            total_initial_remote_disk_size: <int>  # int | If set, what the total initial volume size (in GB) of the remote disks should be
            use_ml_runtime: <bool>  # bool | This field can only be used when `kind = CLASSIC_PREVIEW`.
            worker_node_type_flexibility: <...(nested)>  # ...(nested) | Flexible node type configuration for worker nodes.
            workload_type: <...(nested)>  # ...(nested)
          notebook_task:  # object | The task runs a notebook when the `notebook_task` field is present.
            base_parameters:  # map[string, string] | Base parameters to be used for each run of this job. If the run is initiated by
              <key>: <value>
            notebook_path: <string>  # REQUIRED | string | The path of the notebook to be run in the Databricks workspace or remote reposit
            source: <...(nested)>  # ...(nested) | Optional location type of the notebook. When set to `WORKSPACE`, the notebook wi
            warehouse_id: <string>  # string | Optional `warehouse_id` to run the notebook on a SQL warehouse. Classic SQL ware
          notification_settings:  # object | Optional notification settings that are used when sending notifications to each
            alert_on_last_attempt: <bool>  # bool | If true, do not send notifications to recipients specified in `on_start` for the
            no_alert_for_canceled_runs: <bool>  # bool | If true, do not send notifications to recipients specified in `on_failure` if th
            no_alert_for_skipped_runs: <bool>  # bool | If true, do not send notifications to recipients specified in `on_failure` if th
          pipeline_task:  # object | The task triggers a pipeline update when the `pipeline_task` field is present. O
            full_refresh: <bool>  # bool | If true, triggers a full refresh on the delta live table.
            pipeline_id: <string>  # REQUIRED | string | The full name of the pipeline task to execute.
          power_bi_task:  # object | The task triggers a Power BI semantic model update when the `power_bi_task` fiel
            connection_resource_name: <string>  # string | The resource name of the UC connection to authenticate from Databricks to Power
            power_bi_model: <...(nested)>  # ...(nested) | The semantic model to update
            refresh_after_update: <bool>  # bool | Whether the model should be refreshed after the update
            tables:  # array[...(nested)] | The tables to be exported to Power BI
              - <value>
            warehouse_id: <string>  # string | The SQL warehouse ID to use as the Power BI data source
          python_wheel_task:  # object | The task runs a Python wheel when the `python_wheel_task` field is present.
            entry_point: <string>  # REQUIRED | string | Named entry point to use, if it does not exist in the metadata of the package it
            named_parameters:  # map[string, string] | Command-line parameters passed to Python wheel task in the form of `["--name=tas
              <key>: <value>
            package_name: <string>  # REQUIRED | string | Name of the package to execute
            parameters:  # array[...(nested)] | Command-line parameters passed to Python wheel task. Leave it empty if `named_pa
              - <value>
          retry_on_timeout: <bool>  # bool | An optional policy to specify whether to retry a job when it times out. The defa
          run_if: ALL_SUCCESS  # enum: ALL_SUCCESS, ALL_DONE, NONE_FAILED, AT_LEAST_ONE_SUCCESS, ALL_FAILED, AT_LEAST_ONE_FAILED | An optional value specifying the condition determining whether the task is run o
          run_job_task:  # object | The task triggers another job when the `run_job_task` field is present.
            dbt_commands:  # DEPRECATED | PRIVATE PREVIEW | array[...(nested)] | An array of commands to execute for jobs with the dbt task, for example `"dbt_co
              - <value>
            jar_params:  # DEPRECATED | PRIVATE PREVIEW | array[...(nested)] | A list of parameters for jobs with Spark JAR tasks, for example `"jar_params": [
              - <value>
            job_id: <int>  # REQUIRED | int | ID of the job to trigger.
            job_parameters:  # map[string, string] | Job-level parameters used to trigger the job.
              <key>: <value>
            notebook_params:  # DEPRECATED | PRIVATE PREVIEW | map[string, string] | A map from keys to values for jobs with notebook task, for example `"notebook_pa
              <key>: <value>
            pipeline_params: <...(nested)>  # ...(nested) | Controls whether the pipeline should perform a full refresh
            python_named_params:  # DEPRECATED | PRIVATE PREVIEW | map[string, string]
              <key>: <value>
            python_params:  # DEPRECATED | PRIVATE PREVIEW | array[...(nested)] | A list of parameters for jobs with Python tasks, for example `"python_params": [
              - <value>
            spark_submit_params:  # DEPRECATED | PRIVATE PREVIEW | array[...(nested)] | A list of parameters for jobs with spark submit task, for example `"spark_submit
              - <value>
            sql_params:  # DEPRECATED | PRIVATE PREVIEW | map[string, string] | A map from keys to values for jobs with SQL task, for example `"sql_params": {"n
              <key>: <value>
          spark_jar_task:  # object | The task runs a JAR when the `spark_jar_task` field is present.
            jar_uri: <string>  # DEPRECATED | string | Deprecated since 04/2016. For classic compute, provide a `jar` through the `libr
            main_class_name: <string>  # string | The full name of the class containing the main method to be executed. This class
            parameters:  # array[...(nested)] | Parameters passed to the main method.
              - <value>
            run_as_repl: <bool>  # DEPRECATED | bool | Deprecated. A value of `false` is no longer supported.
          spark_python_task:  # object | The task runs a Python file when the `spark_python_task` field is present.
            parameters:  # array[...(nested)] | Command line parameters passed to the Python file.
              - <value>
            python_file: <string>  # REQUIRED | string | The Python file to be executed. Cloud file URIs (such as dbfs:/, s3:/, adls:/, g
            source: <...(nested)>  # ...(nested) | Optional location type of the Python file. When set to `WORKSPACE` or not specif
          spark_submit_task:  # DEPRECATED | object | (Legacy) The task runs the spark-submit script when the spark_submit_task field
            parameters:  # array[...(nested)] | Command-line parameters passed to spark submit.
              - <value>
          sql_task:  # object | The task runs a SQL query or file, or it refreshes a SQL alert or a legacy SQL d
            alert: <...(nested)>  # ...(nested) | If alert, indicates that this job must refresh a SQL alert.
            dashboard: <...(nested)>  # ...(nested) | If dashboard, indicates that this job must refresh a SQL dashboard.
            file: <...(nested)>  # ...(nested) | If file, indicates that this job runs a SQL file in a remote Git repository.
            parameters:  # map[string, string] | Parameters to be used for each run of this job. The SQL alert task does not supp
              <key>: <value>
            query: <...(nested)>  # ...(nested) | If query, indicates that this job must execute a SQL query.
            warehouse_id: <string>  # REQUIRED | string | The canonical identifier of the SQL warehouse. Recommended to use with serverles
          task_key: <string>  # REQUIRED | string | A unique name for the task. This field is used to refer to this task from other
          timeout_seconds: <int>  # int | An optional timeout applied to each run of this job task. A value of `0` means n
          webhook_notifications:  # object | A collection of system notification IDs to notify when runs of this task begin o
            on_duration_warning_threshold_exceeded:  # array[...(nested)] | An optional list of system notification IDs to call when the duration of a run e
              - <value>
            on_failure:  # array[...(nested)] | An optional list of system notification IDs to call when the run fails. A maximu
              - <value>
            on_start:  # array[...(nested)] | An optional list of system notification IDs to call when the run starts. A maxim
              - <value>
            on_streaming_backlog_exceeded:  # array[...(nested)] | An optional list of system notification IDs to call when any streaming backlog t
              - <value>
            on_success:  # array[...(nested)] | An optional list of system notification IDs to call when the run completes succe
              - <value>
      timeout_seconds: <int>  # int | An optional timeout applied to each run of this job. A value of `0` means no tim
      trigger:  # object | A configuration to trigger a run when certain conditions are met. The default be
        file_arrival:  # object | File arrival trigger settings.
          min_time_between_triggers_seconds: <int>  # int | If set, the trigger starts a run only after the specified amount of time passed
          url: <string>  # REQUIRED | string | URL to be monitored for file arrivals. The path must point to the root or a subp
          wait_after_last_change_seconds: <int>  # int | If set, the trigger starts a run only after no file activity has occurred for th
        model:  # PRIVATE PREVIEW | object
          aliases:  # array[string] | Aliases of the model versions to monitor. Can only be used in conjunction with c
            - <value>
          condition: MODEL_CREATED  # REQUIRED | enum: MODEL_CREATED, MODEL_VERSION_READY, MODEL_ALIAS_SET | The condition based on which to trigger a job run.
          min_time_between_triggers_seconds: <int>  # int | If set, the trigger starts a run only after the specified amount of time has pas
          securable_name: <string>  # string | Name of the securable to monitor ("mycatalog.myschema.mymodel" in the case of mo
          wait_after_last_change_seconds: <int>  # int | If set, the trigger starts a run only after no model updates have occurred for t
        pause_status: UNPAUSED  # enum: UNPAUSED, PAUSED | Whether this trigger is paused or not.
        periodic:  # object | Periodic trigger settings.
          interval: <int>  # REQUIRED | int | The interval at which the trigger should run.
          unit: HOURS  # REQUIRED | enum: HOURS, DAYS, WEEKS | The unit of time for the interval.
        table_update:  # object
          condition: ANY_UPDATED  # enum: ANY_UPDATED, ALL_UPDATED | The table(s) condition based on which to trigger a job run.
          min_time_between_triggers_seconds: <int>  # int | If set, the trigger starts a run only after the specified amount of time has pas
          table_names:  # REQUIRED | array[string] | A list of tables to monitor for changes. The table name must be in the format `c
            - <value>
          wait_after_last_change_seconds: <int>  # int | If set, the trigger starts a run only after no table updates have occurred for t
      usage_policy_id: <string>  # PRIVATE PREVIEW | string | The id of the user specified usage policy to use for this job.
      webhook_notifications:  # object | A collection of system notification IDs to notify when runs of this job begin or
        on_duration_warning_threshold_exceeded:  # array[object] | An optional list of system notification IDs to call when the duration of a run e
          -
            id: <string>  # REQUIRED | string
        on_failure:  # array[object] | An optional list of system notification IDs to call when the run fails. A maximu
          -
            id: <string>  # REQUIRED | string
        on_start:  # array[object] | An optional list of system notification IDs to call when the run starts. A maxim
          -
            id: <string>  # REQUIRED | string
        on_streaming_backlog_exceeded:  # array[object] | An optional list of system notification IDs to call when any streaming backlog t
          -
            id: <string>  # REQUIRED | string
        on_success:  # array[object] | An optional list of system notification IDs to call when the run completes succe
          -
            id: <string>  # REQUIRED | string
```

## What to ask the user

- Schedule (cron) or triggered?
- Single notebook or multi-task with dependencies?
- Cluster type — job cluster (default, recommended) or existing all-purpose?
