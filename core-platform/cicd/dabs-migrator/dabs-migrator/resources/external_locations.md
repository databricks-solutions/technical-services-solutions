# Resource: `external_locations`

Unity Catalog external locations — pointers to cloud storage paths secured by a storage credential.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#external_location

## Complete schema reference

Required fields: `credential_name`, `name`, `url`

```yaml
resources:
  external_locations:
    <external_location_name>:
      comment: <string>  # string
      credential_name: <string>  # REQUIRED | string
      enable_file_events: <bool>  # bool
      encryption_details:  # object
        sse_encryption_details:  # object
          algorithm: AWS_SSE_S3  # enum: AWS_SSE_S3, AWS_SSE_KMS, AWS_SSE_KMS, AWS_SSE_S3
          aws_kms_key_arn: <string>  # string
      fallback: <bool>  # bool
      file_event_queue:  # object
        managed_aqs:  # object
          queue_url: <string>  # string
          resource_group: <string>  # string
          subscription_id: <string>  # string
        managed_pubsub:  # object
          subscription_name: <string>  # string
        managed_sqs:  # object
          queue_url: <string>  # string
        provided_aqs:  # object
          queue_url: <string>  # string
          resource_group: <string>  # string
          subscription_id: <string>  # string
        provided_pubsub:  # object
          subscription_name: <string>  # string
        provided_sqs:  # object
          queue_url: <string>  # string
      grants:  # array[object]
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[enum] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string
      read_only: <bool>  # bool
      skip_validation: <bool>  # bool
      url: <string>  # REQUIRED | string
```

## What to ask the user

- Cloud storage URL (s3://, abfss://, gs://)?
- Existing storage credential name?
