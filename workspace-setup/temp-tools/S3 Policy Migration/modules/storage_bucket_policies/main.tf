locals {
  bucket_name_map = {
    for name, arn in var.bucket_arns :
    name => (startswith(arn, "arn:aws:s3:::") ? replace(arn, "arn:aws:s3:::", "") : arn)
  }
}

data "aws_s3_bucket_policy" "this" {
  for_each = local.bucket_name_map

  bucket = each.value
}

# Extract and filter bucket policy statements that are relevant to Databricks
# or that enforce network/account guardrails we need to preserve.
locals {
  vpce_org_path = "o-g29axo4oyt/r-gu8r/ou-gu8r-g4va1rkr/ou-gu8r-hvyilq7g/*"

  # Case-insensitive pattern; we lowercase the encoded statement before matching.
  # Focus on network guardrails (SourceVpce/SourceVPC/SourceIp) and Databricks markers.
  # PrincipalAccount is treated as optional; statements without it still match via the
  # network conditions. Values may be arrays; regex over the JSON-encoded statement
  # covers both scalars and lists.
  policy_filter_pattern = "databricks|aws:principaltag/databricksaccountid|aws:sourcevpce|aws:sourcevpc|aws:sourceip|stringnotequalsifexists|notipaddressifexists|foranyvalue:stringnotlikeifexists|stringnotlikeifexists|arn:aws:iam::[0-9]{12}:root|aws:principalaccount"

  bucket_policy_documents = {
    for name, policy in data.aws_s3_bucket_policy.this :
    name => try(jsondecode(policy.policy), null)
  }

  # Build updated policies as JSON strings to avoid Terraform object-type mismatches
  # when conditionally adding new keys (e.g., StringNotEqualsIfExists).
  bucket_policy_statement_jsons_updated = {
    for name, doc in local.bucket_policy_documents :
    name => [
      for stmt in try(doc.Statement, []) : (
        (
          length(regexall(local.policy_filter_pattern, lower(jsonencode(stmt)))) > 0
          && try(stmt.Condition["StringNotEqualsIfExists"], null) != null
          && try(stmt.Condition["NotIpAddressIfExists"], null) != null
          &&
          (
            # Update if:
            # - old (invalid) aws:VpceOrgPaths exists under StringNotEqualsIfExists, OR
            # - new ForAnyValue:StringNotLikeIfExists missing required org path
            try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null) != null
            ||
            !contains(
              (
                (
                  try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)
                ) == null ?
                [] :
                (
                  can(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)[0]) ?
                  [for v in try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null) : tostring(v)] :
                  [tostring(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null))]
                )
              ),
              local.vpce_org_path
            )
          )
        )
        ?
        jsonencode(
          merge(
            stmt,
            {
              Condition = merge(
                try(stmt.Condition, {}),
                {
                  # Remove invalid aws:VpceOrgPaths from StringNotEqualsIfExists (AWS rejects it there)
                  StringNotEqualsIfExists = {
                    for k, v in try(try(stmt.Condition, {})["StringNotEqualsIfExists"], {}) :
                    k => v
                    if k != "aws:VpceOrgPaths"
                  }
                  # Add org-path guardrail using an operator AWS accepts for this key
                  "ForAnyValue:StringNotLikeIfExists" = merge(
                    try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {}),
                    {
                      "aws:VpceOrgPaths" = distinct(
                        concat(
                          (
                            (
                              try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)
                            ) == null ?
                            [] :
                            (
                              can(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)[0]) ?
                              [for v in try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null) : tostring(v)] :
                              [tostring(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null))]
                            )
                          ),
                          (
                            (
                              try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null)
                            ) == null ?
                            [] :
                            (
                              can(try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null)[0]) ?
                              [for v in try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null) : tostring(v)] :
                              [tostring(try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null))]
                            )
                          ),
                          [local.vpce_org_path]
                        )
                      )
                    }
                  )
                }
              )
            }
          )
        )
        :
        jsonencode(stmt)
      )
    ]
    if doc != null
  }

  bucket_policy_needs_update = {
    for name, doc in local.bucket_policy_documents :
    name => length([
      for stmt in try(doc.Statement, []) : 1
      if length(regexall(local.policy_filter_pattern, lower(jsonencode(stmt)))) > 0 &&
         try(stmt.Condition["StringNotEqualsIfExists"], null) != null &&
         try(stmt.Condition["NotIpAddressIfExists"], null) != null &&
         (
           try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null) != null
           ||
           !contains(
             (
               (
                 try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)
               ) == null ?
               [] :
               (
                 can(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)[0]) ?
                 [for v in try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null) : tostring(v)] :
                 [tostring(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null))]
               )
             ),
             local.vpce_org_path
           )
         )
    ]) > 0
    if doc != null
  }

  bucket_policies_updated = {
    for name, doc in local.bucket_policy_documents :
    name => (
      local.bucket_policy_needs_update[name] ?
      format(
        "{\"Version\":%s,\"Statement\":[%s]}",
        jsonencode(try(doc.Version, "2012-10-17")),
        join(",", local.bucket_policy_statement_jsons_updated[name])
      )
      :
      data.aws_s3_bucket_policy.this[name].policy
    )
    if doc != null
  }

  # Target buckets: policies that contain the IPDeny-style guardrail statement.
  # We keep managing these buckets after the change so we don't risk deleting policies
  # by dropping them from for_each on subsequent runs.
  bucket_policy_statement_jsons_targeted = {
    for name, doc in local.bucket_policy_documents :
    name => [
      for stmt in try(doc.Statement, []) : jsonencode(stmt)
      if length(regexall(local.policy_filter_pattern, lower(jsonencode(stmt)))) > 0 &&
         try(stmt.Condition["StringNotEqualsIfExists"], null) != null &&
         try(stmt.Condition["NotIpAddressIfExists"], null) != null
    ]
    if doc != null
  }

  bucket_policies_targeted = {
    for name, stmts_json in local.bucket_policy_statement_jsons_targeted :
    name => local.bucket_policies_updated[name]
    if length(stmts_json) > 0
  }

  # Filtered output should only include buckets/statements that STILL need the change.
  bucket_policy_statement_jsons_filtered = {
    for name, doc in local.bucket_policy_documents :
    name => [
      for stmt in try(doc.Statement, []) :
      jsonencode(
        merge(
          stmt,
          {
            Condition = merge(
              try(stmt.Condition, {}),
              {
                # Remove invalid aws:VpceOrgPaths from StringNotEqualsIfExists (AWS rejects it there)
                StringNotEqualsIfExists = {
                  for k, v in try(try(stmt.Condition, {})["StringNotEqualsIfExists"], {}) :
                  k => v
                  if k != "aws:VpceOrgPaths"
                }
                # Add org-path guardrail using an operator AWS accepts for this key
                "ForAnyValue:StringNotLikeIfExists" = merge(
                  try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {}),
                  {
                    "aws:VpceOrgPaths" = distinct(
                      concat(
                        (
                          (
                            try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)
                          ) == null ?
                          [] :
                          (
                            can(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)[0]) ?
                            [for v in try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null) : tostring(v)] :
                            [tostring(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null))]
                          )
                        ),
                        (
                          (
                            try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null)
                          ) == null ?
                          [] :
                          (
                            can(try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null)[0]) ?
                            [for v in try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null) : tostring(v)] :
                            [tostring(try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null))]
                          )
                        ),
                        [local.vpce_org_path]
                      )
                    )
                  }
                )
              }
            )
          }
        )
      )
      if length(regexall(local.policy_filter_pattern, lower(jsonencode(stmt)))) > 0 &&
         try(stmt.Condition["StringNotEqualsIfExists"], null) != null &&
         try(stmt.Condition["NotIpAddressIfExists"], null) != null &&
         (
           # Still needs update if old invalid placement exists OR new placement is missing required org path
           try(try(stmt.Condition, {})["StringNotEqualsIfExists"]["aws:VpceOrgPaths"], null) != null
           ||
           !contains(
             (
               (
                 try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)
               ) == null ?
               [] :
               (
                 can(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null)[0]) ?
                 [for v in try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null) : tostring(v)] :
                 [tostring(try(try(try(stmt.Condition, {})["ForAnyValue:StringNotLikeIfExists"], {})["aws:VpceOrgPaths"], null))]
               )
             ),
             local.vpce_org_path
           )
         )
    ]
    if doc != null
  }

  bucket_policies_filtered = {
    for name, stmts_json in local.bucket_policy_statement_jsons_filtered :
    name => format(
      "{\"Version\":%s,\"Statement\":[%s]}",
      jsonencode(try(local.bucket_policy_documents[name].Version, "2012-10-17")),
      join(",", stmts_json)
    )
    if length(stmts_json) > 0
  }
}

resource "aws_s3_bucket_policy" "updated" {
  for_each = local.bucket_policies_targeted

  bucket = local.bucket_name_map[each.key]
  policy = each.value

  lifecycle {
    prevent_destroy = true
  }
}
