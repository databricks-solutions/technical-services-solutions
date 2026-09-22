# Resource: `clusters`

All-purpose compute clusters. Generally **prefer job clusters** (defined inline in `jobs`) — only declare standalone clusters when multiple humans/jobs share them.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#cluster

## Complete schema reference

```yaml
resources:
  clusters:
    <cluster_name>:
      apply_policy_default_values: <bool>  # bool | When set to true, fixed and default values from the policy will be used for fiel
      autoscale:  # object | Parameters needed in order to automatically scale clusters up and down based on
        max_workers: <int>  # int | The maximum number of workers to which the cluster can scale up when overloaded.
        min_workers: <int>  # int | The minimum number of workers to which the cluster can scale down when underutil
      autotermination_minutes: <int>  # int | Automatically terminates the cluster after it is inactive for this time in minut
      aws_attributes:  # object | Attributes related to clusters running on Amazon Web Services.
        availability: SPOT  # enum: SPOT, ON_DEMAND, SPOT_WITH_FALLBACK | Availability type used for all subsequent nodes past the `first_on_demand` ones.
        ebs_volume_count: <int>  # int | The number of volumes launched for each instance. Users can choose up to 10 volu
        ebs_volume_iops: <int>  # int | If using gp3 volumes, what IOPS to use for the disk. If this is not set, the max
        ebs_volume_size: <int>  # int | The size of each EBS volume (in GiB) launched for each instance. For general pur
        ebs_volume_throughput: <int>  # int | If using gp3 volumes, what throughput to use for the disk. If this is not set, t
        ebs_volume_type: GENERAL_PURPOSE_SSD  # enum: GENERAL_PURPOSE_SSD, THROUGHPUT_OPTIMIZED_HDD | The type of EBS volumes that will be launched with this cluster.
        first_on_demand: <int>  # int | The first `first_on_demand` nodes of the cluster will be placed on on-demand ins
        instance_profile_arn: <string>  # string | Nodes for this cluster will only be placed on AWS instances with this instance p
        spot_bid_price_percent: <int>  # int | The bid price for AWS spot instances, as a percentage of the corresponding insta
        zone_id: <string>  # string | Identifier for the availability zone/datacenter in which the cluster resides.
      azure_attributes:  # object | Attributes related to clusters running on Microsoft Azure.
        availability: SPOT_AZURE  # enum: SPOT_AZURE, ON_DEMAND_AZURE, SPOT_WITH_FALLBACK_AZURE | Availability type used for all subsequent nodes past the `first_on_demand` ones.
        capacity_reservation_group: <string>  # string | The Azure capacity reservation group resource ID to use for launching VMs.
        first_on_demand: <int>  # int | The first `first_on_demand` nodes of the cluster will be placed on on-demand ins
        log_analytics_info:  # object | Defines values necessary to configure and run Azure Log Analytics agent
          log_analytics_primary_key: <string>  # string | The primary key for the Azure Log Analytics agent configuration
          log_analytics_workspace_id: <string>  # string | The workspace ID for the Azure Log Analytics agent configuration
        spot_bid_max_price: <float>  # float | The max bid price to be used for Azure spot instances.
      cluster_log_conf:  # object | The configuration for delivering spark logs to a long-term storage destination.
        dbfs:  # object | destination needs to be provided. e.g.
          destination: <string>  # REQUIRED | string | dbfs destination, e.g. `dbfs:/my/path`
        s3:  # object | destination and either the region or endpoint need to be provided. e.g.
          canned_acl: <string>  # string | (Optional) Set canned access control list for the logs, e.g. `bucket-owner-full-
          destination: <string>  # REQUIRED | string | S3 destination, e.g. `s3://my-bucket/some-prefix` Note that logs will be deliver
          enable_encryption: <bool>  # bool | (Optional) Flag to enable server side encryption, `false` by default.
          encryption_type: <string>  # string | (Optional) The encryption type, it could be `sse-s3` or `sse-kms`. It will be us
          endpoint: <string>  # string | S3 endpoint, e.g. `https://s3-us-west-2.amazonaws.com`. Either region or endpoin
          kms_key: <string>  # string | (Optional) Kms key which will be used if encryption is enabled and encryption ty
          region: <string>  # string | S3 region, e.g. `us-west-2`. Either region or endpoint needs to be set. If both
        volumes:  # object | destination needs to be provided, e.g.
          destination: <string>  # REQUIRED | string | UC Volumes destination, e.g. `/Volumes/catalog/schema/vol1/init-scripts/setup-da
      cluster_name: <string>  # string | Cluster name requested by the user. This doesn't have to be unique.
      custom_tags:  # map[string, string] | Additional tags for cluster resources. Databricks will tag all cluster resources
        <key>: <value>
      data_security_mode: NONE  # enum: NONE, SINGLE_USER, USER_ISOLATION, LEGACY_TABLE_ACL, LEGACY_PASSTHROUGH, LEGACY_SINGLE_USER, ... | Data security mode decides what data governance model to use when accessing data
      docker_image:  # object | Custom docker image BYOC
        basic_auth:  # object | Basic auth with username and password
          password: <string>  # string | Password of the user
          username: <string>  # string | Name of the user
        url: <string>  # string | URL of the docker image.
      driver_instance_pool_id: <string>  # string | The optional ID of the instance pool for the driver of the cluster belongs.
      driver_node_type_flexibility:  # object | Flexible node type configuration for the driver node.
        alternate_node_type_ids:  # array[string] | A list of node type IDs to use as fallbacks when the primary node type is unavai
          - <value>
      driver_node_type_id: <string>  # string | The node type of the Spark driver.
      enable_elastic_disk: <bool>  # bool | Autoscaling Local Storage: when enabled, this cluster will dynamically acquire a
      enable_local_disk_encryption: <bool>  # bool | Whether to enable LUKS on cluster VMs' local disks
      gcp_attributes:  # object | Attributes related to clusters running on Google Cloud Platform.
        availability: PREEMPTIBLE_GCP  # enum: PREEMPTIBLE_GCP, ON_DEMAND_GCP, PREEMPTIBLE_WITH_FALLBACK_GCP | This field determines whether the spark executors will be scheduled to run on pr
        boot_disk_size: <int>  # int | Boot disk size in GB
        confidential_compute_type: CONFIDENTIAL_COMPUTE_TYPE_NONE  # PRIVATE PREVIEW | enum: CONFIDENTIAL_COMPUTE_TYPE_NONE, SEV_SNP | The confidential computing technology for this cluster's instances.
        first_on_demand: <int>  # int | The first `first_on_demand` nodes of the cluster will be placed on on-demand ins
        google_service_account: <string>  # string | If provided, the cluster will impersonate the google service account when access
        local_ssd_count: <int>  # int | If provided, each node (workers and driver) in the cluster will have this number
        use_preemptible_executors: <bool>  # DEPRECATED | bool | This field determines whether the spark executors will be scheduled to run on pr
        zone_id: <string>  # string | Identifier for the availability zone in which the cluster resides.
      init_scripts:  # array[object] | The configuration for storing init scripts. Any number of destinations can be sp
        -
          abfss:  # object | Contains the Azure Data Lake Storage destination path
            destination: <string>  # REQUIRED | string | abfss destination, e.g. `abfss://<container-name>@<storage-account-name>.dfs.cor
          dbfs:  # DEPRECATED | object | destination needs to be provided. e.g.
            destination: <string>  # REQUIRED | string | dbfs destination, e.g. `dbfs:/my/path`
          file:  # object | destination needs to be provided, e.g.
            destination: <string>  # REQUIRED | string | local file destination, e.g. `file:/my/local/file.sh`
          gcs:  # object | destination needs to be provided, e.g.
            destination: <string>  # REQUIRED | string | GCS destination/URI, e.g. `gs://my-bucket/some-prefix`
          s3:  # object | destination and either the region or endpoint need to be provided. e.g.
            canned_acl: <string>  # string | (Optional) Set canned access control list for the logs, e.g. `bucket-owner-full-
            destination: <string>  # REQUIRED | string | S3 destination, e.g. `s3://my-bucket/some-prefix` Note that logs will be deliver
            enable_encryption: <bool>  # bool | (Optional) Flag to enable server side encryption, `false` by default.
            encryption_type: <string>  # string | (Optional) The encryption type, it could be `sse-s3` or `sse-kms`. It will be us
            endpoint: <string>  # string | S3 endpoint, e.g. `https://s3-us-west-2.amazonaws.com`. Either region or endpoin
            kms_key: <string>  # string | (Optional) Kms key which will be used if encryption is enabled and encryption ty
            region: <string>  # string | S3 region, e.g. `us-west-2`. Either region or endpoint needs to be set. If both
          volumes:  # object | destination needs to be provided. e.g.
            destination: <string>  # REQUIRED | string | UC Volumes destination, e.g. `/Volumes/catalog/schema/vol1/init-scripts/setup-da
          workspace:  # object | destination needs to be provided, e.g.
            destination: <string>  # REQUIRED | string | wsfs destination, e.g. `workspace:/cluster-init-scripts/setup-datadog.sh`
      instance_pool_id: <string>  # string | The optional ID of the instance pool to which the cluster belongs.
      is_single_node: <bool>  # bool | This field can only be used when `kind = CLASSIC_PREVIEW`.
      kind: CLASSIC_PREVIEW  # enum: CLASSIC_PREVIEW | The kind of compute described by this compute specification.
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
        started: <bool>  # bool | Lifecycle setting to deploy the resource in started mode. Only supported for app
      node_type_id: <string>  # string | This field encodes, through a single value, the resources available to each of
      num_workers: <int>  # int | Number of worker nodes that this cluster should have. A cluster has one Spark Dr
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      policy_id: <string>  # string | The ID of the cluster policy used to create the cluster if applicable.
      remote_disk_throughput: <int>  # int | If set, what the configurable throughput (in Mb/s) for the remote disk is. Curre
      runtime_engine: NULL  # enum: NULL, STANDARD, PHOTON | Determines the cluster's runtime engine, either standard or Photon.
      single_user_name: <string>  # string | Single user name if data_security_mode is `SINGLE_USER`
      spark_conf:  # map[string, string] | An object containing a set of optional, user-specified Spark configuration key-v
        <key>: <value>
      spark_env_vars:  # map[string, string] | An object containing a set of optional, user-specified environment variable key-
        <key>: <value>
      spark_version: <string>  # string | The Spark version of the cluster, e.g. `3.3.x-scala2.11`.
      ssh_public_keys:  # array[string] | SSH public key contents that will be added to each Spark node in this cluster. T
        - <value>
      total_initial_remote_disk_size: <int>  # int | If set, what the total initial volume size (in GB) of the remote disks should be
      use_ml_runtime: <bool>  # bool | This field can only be used when `kind = CLASSIC_PREVIEW`.
      worker_node_type_flexibility:  # object | Flexible node type configuration for worker nodes.
        alternate_node_type_ids:  # array[string] | A list of node type IDs to use as fallbacks when the primary node type is unavai
          - <value>
      workload_type:  # object | Cluster Attributes showing for clusters workload types.
        clients:  # REQUIRED | object | defined what type of clients can use the cluster. E.g. Notebooks, Jobs
          jobs: <bool>  # bool | With jobs set, the cluster can be used for jobs
          notebooks: <bool>  # bool | With notebooks set, this cluster can be used for notebooks
```

## What to ask the user

- Single-user or shared (USER_ISOLATION)?
- Fixed workers or autoscale?
- Init scripts or custom libraries?
