# Resource: `model_serving_endpoints`

REST endpoints for serving registered models.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#model_serving_endpoint

## Complete schema reference

Required fields: `name`

```yaml
resources:
  model_serving_endpoints:
    <model_serving_endpoint_name>:
      ai_gateway:  # object | The AI Gateway configuration for the serving endpoint. NOTE: External model, pro
        fallback_config:  # object | Configuration for traffic fallback which auto fallbacks to other served entities
          enabled: <bool>  # REQUIRED | bool | Whether to enable traffic fallback. When a served entity in the serving endpoint
        guardrails:  # object | Configuration for AI Guardrails to prevent unwanted data and unsafe data in requ
          input:  # object | Configuration for input guardrail filters.
            invalid_keywords: <...(nested)>  # DEPRECATED | ...(nested) | List of invalid keywords.
            pii: <...(nested)>  # ...(nested) | Configuration for guardrail PII filter.
            safety: <...(nested)>  # ...(nested) | Indicates whether the safety filter is enabled.
            valid_topics: <...(nested)>  # DEPRECATED | ...(nested) | The list of allowed topics.
          output:  # object | Configuration for output guardrail filters.
            invalid_keywords: <...(nested)>  # DEPRECATED | ...(nested) | List of invalid keywords.
            pii: <...(nested)>  # ...(nested) | Configuration for guardrail PII filter.
            safety: <...(nested)>  # ...(nested) | Indicates whether the safety filter is enabled.
            valid_topics: <...(nested)>  # DEPRECATED | ...(nested) | The list of allowed topics.
        inference_table_config:  # object | Configuration for payload logging using inference tables.
          catalog_name: <string>  # string | The name of the catalog in Unity Catalog. Required when enabling inference table
          enabled: <bool>  # bool | Indicates whether the inference table is enabled.
          schema_name: <string>  # string | The name of the schema in Unity Catalog. Required when enabling inference tables
          table_name_prefix: <string>  # string | The prefix of the table in Unity Catalog.
        rate_limits:  # array[object] | Configuration for rate limits which can be set to limit endpoint traffic.
          -
            calls: <int>  # int | Used to specify how many calls are allowed for a key within the renewal_period.
            key: <...(nested)>  # ...(nested) | Key field for a rate limit. Currently, 'user', 'user_group, 'service_principal',
            principal: <string>  # string | Principal field for a user, user group, or service principal to apply rate limit
            renewal_period: <...(nested)>  # REQUIRED | ...(nested) | Renewal period field for a rate limit. Currently, only 'minute' is supported.
            tokens: <int>  # int | Used to specify how many tokens are allowed for a key within the renewal_period.
        usage_tracking_config:  # object | Configuration to enable usage tracking using system tables.
          enabled: <bool>  # bool | Whether to enable usage tracking.
      budget_policy_id: <string>  # string | The budget policy to be applied to the serving endpoint.
      config:  # object | The core config of the serving endpoint.
        auto_capture_config:  # object | Configuration for Inference Tables which automatically logs requests and respons
          catalog_name: <string>  # string | The name of the catalog in Unity Catalog. NOTE: On update, you cannot change the
          enabled: <bool>  # bool | Indicates whether the inference table is enabled.
          schema_name: <string>  # string | The name of the schema in Unity Catalog. NOTE: On update, you cannot change the
          table_name_prefix: <string>  # string | The prefix of the table in Unity Catalog. NOTE: On update, you cannot change the
        served_entities:  # array[object] | The list of served entities under the serving endpoint config.
          -
            burst_scaling_enabled: <bool>  # bool | Whether burst scaling is enabled. When enabled (default), the endpoint can autom
            entity_name: <string>  # string | The name of the entity to be served. The entity may be a model in the Databricks
            entity_version: <string>  # string
            environment_vars:  # map[string, string] | An object containing a set of optional, user-specified environment variable key-
              <key>: <value>
            external_model: <...(nested)>  # ...(nested) | The external model to be served. NOTE: Only one of external_model and (entity_na
            instance_profile_arn: <string>  # string | ARN of the instance profile that the served entity uses to access AWS resources.
            max_provisioned_concurrency: <int>  # int | The maximum provisioned concurrency that the endpoint can scale up to. Do not us
            max_provisioned_throughput: <int>  # int | The maximum tokens per second that the endpoint can scale up to.
            min_provisioned_concurrency: <int>  # int | The minimum provisioned concurrency that the endpoint can scale down to. Do not
            min_provisioned_throughput: <int>  # int | The minimum tokens per second that the endpoint can scale down to.
            name: <string>  # string | The name of a served entity. It must be unique across an endpoint. A served enti
            provisioned_model_units: <int>  # int | The number of model units provisioned.
            scale_to_zero_enabled: <bool>  # bool | Whether the compute resources for the served entity should scale down to zero.
            workload_size: <string>  # string | The workload size of the served entity. The workload size corresponds to a range
            workload_type: <...(nested)>  # ...(nested) | The workload type of the served entity. The workload type selects which type of
        served_models:  # array[object] | (Deprecated, use served_entities instead) The list of served models under the se
          -
            burst_scaling_enabled: <bool>  # bool | Whether burst scaling is enabled. When enabled (default), the endpoint can autom
            environment_vars:  # map[string, string] | An object containing a set of optional, user-specified environment variable key-
              <key>: <value>
            instance_profile_arn: <string>  # string | ARN of the instance profile that the served entity uses to access AWS resources.
            max_provisioned_concurrency: <int>  # int | The maximum provisioned concurrency that the endpoint can scale up to. Do not us
            max_provisioned_throughput: <int>  # int | The maximum tokens per second that the endpoint can scale up to.
            min_provisioned_concurrency: <int>  # int | The minimum provisioned concurrency that the endpoint can scale down to. Do not
            min_provisioned_throughput: <int>  # int | The minimum tokens per second that the endpoint can scale down to.
            model_name: <string>  # REQUIRED | string
            model_version: <string>  # REQUIRED | string
            name: <string>  # string | The name of a served entity. It must be unique across an endpoint. A served enti
            provisioned_model_units: <int>  # int | The number of model units provisioned.
            scale_to_zero_enabled: <bool>  # REQUIRED | bool | Whether the compute resources for the served entity should scale down to zero.
            workload_size: <string>  # string | The workload size of the served entity. The workload size corresponds to a range
            workload_type: <...(nested)>  # ...(nested) | The workload type of the served entity. The workload type selects which type of
        traffic_config:  # object | The traffic configuration associated with the serving endpoint config.
          routes:  # array[...(nested)] | The list of routes that define traffic to each served entity.
            - <value>
      description: <string>  # string
      email_notifications:  # object | Email notification settings.
        on_update_failure:  # array[string] | A list of email addresses to be notified when an endpoint fails to update its co
          - <value>
        on_update_success:  # array[string] | A list of email addresses to be notified when an endpoint successfully updates i
          - <value>
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | The name of the serving endpoint. This field is required and must be unique acro
      permissions:  # array[object]
        -
          group_name: <string>  # string
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_QUERY, CAN_VIEW
          service_principal_name: <string>  # string
          user_name: <string>  # string
      rate_limits:  # DEPRECATED | array[object] | Rate limits to be applied to the serving endpoint. NOTE: this field is deprecate
        -
          calls: <int>  # REQUIRED | int | Used to specify how many calls are allowed for a key within the renewal_period.
          key: user  # enum: user, endpoint | Key field for a serving endpoint rate limit. Currently, only 'user' and 'endpoin
          renewal_period: minute  # REQUIRED | enum: minute | Renewal period field for a serving endpoint rate limit. Currently, only 'minute'
      route_optimized: <bool>  # bool | Enable route optimization for the serving endpoint.
      tags:  # array[object] | Tags to be attached to the serving endpoint and automatically propagated to bill
        -
          key: <string>  # REQUIRED | string | Key field for a serving endpoint tag.
          value: <string>  # string | Optional value field for a serving endpoint tag.
```

## What to ask the user

- Which registered model + version(s)?
- Workload size and scale-to-zero?
- Traffic split if multiple models?
