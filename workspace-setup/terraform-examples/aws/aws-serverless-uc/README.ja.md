# AWS Serverless Workspace セットアップガイド

この Terraform サンプルは、Unity Catalog を使用する Databricks Workspace を AWS 上に Serverless Compute モードでデプロイします。Customer-managed VPC や Network Connectivity Configuration（NCC）は作成・割り当てしません。Workspace の作成、新規または既存の Unity Catalog Metastore の割り当てを行い、オプションで専用の S3 Bucket、IAM Role、Storage Credential、External Location を持つユーザー定義 Catalog も作成します。

Serverless Compute から AWS リソースへの Private Connectivity が必要な場合は、代わりに [`aws-serverless-ncc`](../aws-serverless-ncc/) を使用してください。

English documentation is available in [README.md](README.md).

## 要件

- Terraform ~> 1.3 がローカル環境にインストールされていること：[リンク](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)
- AWS CLI がインストールされ、適切な認証情報が設定されていること
- Serverless Workspace が有効な Databricks Account（E2 Account）が作成済みであること
- OAuth M2M 認証情報を持つ Databricks Account Admin の Service Principal
- `new_catalog = true` の場合、IAM と S3 リソースを作成できる AWS 権限
- 既存 Metastore を使用する場合、Terraform の Service Principal がその Metastore 上で Storage Credential と External Location を作成できること

## はじめる前に

設定値は Terraform Variable として定義されています。`tf/terraform.tfvars.example` を `tf/terraform.tfvars` にコピーし、Databricks Account ID、AWS Account ID、Region、Metastore の設定を入力してください。Terraform は `terraform.tfvars` を自動的に読み込みます。

デフォルトではユーザー定義 Catalog も作成します。Workspace と Metastore Assignment のみが必要な場合は `new_catalog = false` を設定してください。

## 認証

### AWS 認証

#### オプション 1：環境変数

```sh
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_SESSION_TOKEN="your-session-token" # 一時認証情報を使用する場合
```

#### オプション 2：AWS CLI Profile

```sh
export AWS_PROFILE="your-profile"
```

#### オプション 3：AWS SSO Login

```sh
aws sso login --profile your-profile
```

### Databricks 認証

Account Level の操作には Account Admin の Service Principal を使用します。

```sh
export DATABRICKS_CLIENT_ID="your-client-id"
export DATABRICKS_CLIENT_SECRET="your-client-secret"
```

認証情報を `terraform.tfvars` に保存しないでください。詳細は [Databricks Service Principal のドキュメント](https://docs.databricks.com/en/dev-tools/service-principals.html)を参照してください。

## この Terraform コードが行うこと

### 概要

このコードは次のリソースを作成します。

1. **Databricks Workspace** -- `compute_mode = "SERVERLESS"` の E2 Workspace。Customer-managed Network Configuration は割り当てません。
2. **Unity Catalog Metastore** -- `metastore_id` が空の場合は Metastore を作成し、指定されている場合は既存 Metastore を使用して Workspace に割り当てます。
3. **Unity Catalog IAM Role と S3 Bucket** _（`new_catalog = true` の場合）_ -- Catalog Storage 専用の Self-assuming IAM Role と非公開 S3 Bucket を作成します。
4. **Storage Credential と External Location** _（`new_catalog = true` の場合）_ -- IAM Role を使用する Unity Catalog Storage Credential と、S3 Bucket を指す External Location を作成します。
5. **ユーザー定義 Catalog** _（`new_catalog = true` の場合）_ -- External Location を Managed Storage とする Catalog を作成します。

`aws-byovpc-uc` とは異なり、VPC、Subnet、NAT Gateway、VPC Endpoint、Security Group、Workspace Root Storage Bucket、Workspace 用 Cross-account Credential、Classic Cluster は作成しません。

### 変数

`tf/` ディレクトリで `terraform.tfvars.example` を `terraform.tfvars` にコピーし、値を設定してください。`terraform.tfvars` は Commit しないでください。別のファイル名を使用する場合は `-var-file` を指定します。

| 変数 | 説明 |
|------|------|
| `databricks_account_id` | **必須**：Databricks Account ID。 |
| `aws_account_id` | **必須**：Unity Catalog リソースを作成する 12 桁の AWS Account ID。 |
| `region` | **必須**：Workspace と Metastore の AWS Region。[Databricks がサポートする Region](https://docs.databricks.com/en/resources/supported-regions.html)を指定します。 |
| `prefix` | **任意**：Databricks リソース名と Workspace 名の Prefix。デフォルト：`databricks-workspace`。 |
| `resource_prefix` | **任意**：AWS リソース名の Prefix。小文字、数字、ハイフン、ドットのみ、最大 40 文字。デフォルト：`databricks-workspace`。 |
| `tags` | **任意**：AWS リソースに追加する Tag。デフォルト：`{}`。 |
| `metastore_id` | **任意**：既存 Unity Catalog Metastore ID。新規作成する場合は空にします。デフォルト：`""`。 |
| `metastore_name` | **Metastore 新規作成時は必須**：新規 Metastore の名前。デフォルト：`""`。 |
| `new_catalog` | **任意**：S3 Bucket、IAM Role、Storage Credential、External Location、Catalog を作成するか。デフォルト：`true`。 |
| `catalog_name` | **任意**：Catalog 名。デフォルトの `""` では `{prefix}-catalog`。 |
| `external_location_name` | **任意**：External Location 名。デフォルトの `""` では `{resource_prefix}-external-location`。 |
| `storage_credential_name` | **任意**：Storage Credential 名。デフォルトの `""` では `{resource_prefix}-storage-credential`。 |

## デプロイ

```bash
cd tf/

# 設定ファイルをコピーして編集
cp terraform.tfvars.example terraform.tfvars

# Terraform を初期化
terraform init

# 実行計画を確認
terraform plan

# 構成を適用
terraform apply
```

確認を求められたら `yes` を入力します。Workspace と Unity Catalog リソースが利用可能になるまで数分かかる場合があります。

## Workspace へのアクセス

デプロイが成功したら、次を実行します。

```bash
# Workspace URL を取得
terraform output -raw workspace_url

# Workspace ID を取得
terraform output -raw workspace_id
```

Workspace URL を開き、Databricks の認証情報でログインします。

## 検証

デプロイ結果を次の手順で検証します。

1. **Terraform Output** -- `terraform output` を実行し、`workspace_url`、`workspace_id`、`metastore_id` が空でないことを確認します。
2. **Workspace へのアクセス** -- `terraform output -raw workspace_url` を開いてログインします。
3. **Unity Catalog** -- `new_catalog = true` の場合、Catalog Explorer に `catalog_name` が存在することを確認します。
4. **Serverless Access** -- Serverless Notebook または SQL Warehouse を起動し、作成した Catalog のデータを読み書きします。

## クリーンアップ

このシナリオで作成したすべてのリソースを削除するには、次を実行します。

```bash
cd tf
terraform destroy
```

確認を求められたら `yes` を入力します。生成される Catalog と S3 Bucket には `force_destroy = true` が設定されています。データを含むリソースを削除する前に Destroy Plan を確認してください。

## トラブルシューティング

| 問題 | 原因 | 解決策 |
|------|------|--------|
| AWS Provider の認証に失敗する | AWS CLI が未設定、または認証情報が期限切れ | `aws configure`、AWS SSO の再認証、または標準 AWS 認証環境変数を設定します。 |
| Databricks Provider の認証に失敗する | Service Principal の認証情報がない、または無効 | Account Admin の Service Principal に対する `DATABRICKS_CLIENT_ID` と `DATABRICKS_CLIENT_SECRET` を設定します。 |
| 既存 Metastore の割り当てに失敗する | Metastore が別の Region にある | Workspace と同じ Region の Metastore を使用します。 |
| Storage Credential または External Location の作成に失敗する | Service Principal の Metastore 権限不足、または IAM の反映待ち | 必要な Metastore 権限を付与し、`terraform apply` を再実行します。この構成では IAM の反映を 60 秒待機します。 |
| S3 または IAM の作成に失敗する | AWS 権限不足、またはリソース名の重複 | 必要な権限を付与するか、一意の `resource_prefix` を指定します。 |
| Destroy 時に Catalog を削除できない | 構成外で保護された Object が Catalog 内にある | 保護された Object を削除し、`terraform destroy` を再実行します。 |

## ファイル構成

このプロジェクトは `aws-byovpc-uc` と同じ、用途別のフラットな構成です。

```text
tf/
├── versions.tf                 # Terraform と Provider の Version 制約
├── providers.tf                # AWS と Databricks Provider
├── variables.tf                # Input Variable 定義
├── outputs.tf                  # Output 値
├── terraform.tfvars.example    # 設定テンプレート
├── workspace.tf                # Serverless Workspace
├── metastore.tf                # Unity Catalog Metastore と割り当て
└── unity_catalog.tf            # オプションの S3-backed Catalog リソース
```

| ファイル | 目的 |
|----------|------|
| **versions.tf** | AWS、Databricks、Random、Time Provider と Terraform の Version 制約。 |
| **providers.tf** | AWS Provider、Account Level と Workspace Level の Databricks Provider。 |
| **variables.tf** | Databricks、AWS、Metastore、オプション Catalog の入力。 |
| **terraform.tfvars.example** | `terraform.tfvars` にコピーして使用する設定例。 |
| **workspace.tf** | Serverless Workspace の作成と利用可能になるまでの待機。 |
| **metastore.tf** | 新規または既存 Metastore の解決、Region 検証、Workspace Assignment。 |
| **unity_catalog.tf** | オプションの S3 Bucket、IAM Role、Storage Credential、External Location、Catalog。 |
| **outputs.tf** | Workspace、Metastore、Catalog、External Location、Storage Credential の Output。 |

`main.tf` はありません。Terraform はディレクトリ内のすべての `.tf` ファイルを自動的に読み込みます。

## Terraform テンプレートと関連ドキュメント

これらのテンプレートは調査・検証用として AS-IS で提供され、Databricks の Service Level Agreement（SLA）による正式なサポート対象ではありません。

- [Databricks Terraform Provider ドキュメント](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Account API を使用した Serverless Workspace の作成](https://docs.databricks.com/aws/en/admin/workspace/serverless-workspaces)
- [Unity Catalog External Location](https://docs.databricks.com/aws/en/connect/unity-catalog/cloud-storage/s3)
