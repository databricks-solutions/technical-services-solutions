# Resource: `external_locations`

Unity Catalog external locations — pointers to cloud storage paths secured by a storage credential.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#external_location

## Complete schema reference

Required fields: `credential_name`, `name`, `url`

```yaml
resources:
  external_locations:
    <external_location_name>:
      comment: <string>  # string | User-provided free-form text description.
      credential_name: <string>  # REQUIRED | string | Name of the storage credential used with this location.
      enable_file_events: <bool>  # bool | Whether to enable file events on this external location. Default to `true`. Set
      encryption_details:  # object | Encryption options that apply to clients connecting to cloud storage.
        sse_encryption_details:  # object | Server-Side Encryption properties for clients communicating with AWS s3.
          algorithm: AWS_SSE_S3  # enum: AWS_SSE_S3, AWS_SSE_KMS, AWS_SSE_KMS, AWS_SSE_S3 | Sets the value of the 'x-amz-server-side-encryption' header in S3 request.
          aws_kms_key_arn: <string>  # string | Optional. The ARN of the SSE-KMS key used with the S3 location, when algorithm =
      fallback: <bool>  # bool | Indicates whether fallback mode is enabled for this external location. When fall
      file_event_queue:  # object | File event queue settings. If `enable_file_events` is not `false`, must be defin
        managed_aqs:  # object
          queue_url: <string>  # string | The AQS queue url in the format https://{storage account}.queue.core.windows.net
          resource_group: <string>  # string | Optional resource group for the queue, event grid subscription, and external loc
          subscription_id: <string>  # string | Optional subscription id for the queue, event grid subscription, and external lo
        managed_pubsub:  # object
          subscription_name: <string>  # string | The Pub/Sub subscription name in the format projects/{project}/subscriptions/{su
        managed_sqs:  # object
          queue_url: <string>  # string | The AQS queue url in the format https://sqs.{region}.amazonaws.com/{account id}/
        provided_aqs:  # object
          queue_url: <string>  # string | The AQS queue url in the format https://{storage account}.queue.core.windows.net
          resource_group: <string>  # string | Optional resource group for the queue, event grid subscription, and external loc
          subscription_id: <string>  # string | Optional subscription id for the queue, event grid subscription, and external lo
        provided_pubsub:  # object
          subscription_name: <string>  # string | The Pub/Sub subscription name in the format projects/{project}/subscriptions/{su
        provided_sqs:  # object
          queue_url: <string>  # string | The AQS queue url in the format https://sqs.{region}.amazonaws.com/{account id}/
      grants:  # array[object] | The Unity Catalog privileges to grant to principals on this securable.
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[string] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Name of the external location.
      read_only: <bool>  # bool | Indicates whether the external location is read-only.
      skip_validation: <bool>  # bool | Skips validation of the storage credential associated with the external location
      url: <string>  # REQUIRED | string | Path URL of the external location.
```

## What to ask the user

- Cloud storage URL (s3://, abfss://, gs://)?
- Existing storage credential name?
