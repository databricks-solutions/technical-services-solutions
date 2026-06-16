# Databricks Terraform Pre-Check

Ferramenta CLI para validar **credenciais, permissões e recursos** antes de realizar deployments de workspaces Databricks via Terraform em **AWS, Azure e GCP**.

## Por que usar?

Antes de rodar `terraform apply`, esta ferramenta verifica:

- ✅ Credenciais válidas e configuradas corretamente
- ✅ Permissões IAM/RBAC específicas para Databricks
- ✅ Configuração de rede (VPC, Subnets, Security Groups)
- ✅ **Private Link / VPC Endpoints** para conectividade privada
- ✅ Storage para DBFS e Unity Catalog
- ✅ Quotas e limites de recursos
- ✅ KMS/Key Vault para criptografia CMK

## Instalação

```bash
# Criar virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# Instalar dependências
pip install -r requirements.txt
```

## Uso

### Verificar AWS

```bash
python main.py --cloud aws --region us-east-1

# Com profile específico
python main.py --cloud aws --region us-east-1 --profile my-profile
```

### Verificar Azure

```bash
python main.py --cloud azure --subscription-id <subscription-id> --resource-group <resource-group>

# Especificando região
python main.py --cloud azure --subscription-id xxx --region eastus
```

### Verificar GCP

```bash
python main.py --cloud gcp --project <project-id> --region us-central1

# Com arquivo de credenciais
python main.py --cloud gcp --project my-project --credentials-file /path/to/key.json
```

### Verificar todas as clouds configuradas

```bash
python main.py --all
```

### Salvar relatório em arquivo

```bash
python main.py --cloud aws --output report.txt
```

### Opções adicionais

```bash
# Verificar todas as clouds detectadas
python main.py --all

# Modo read-only (sem criação de recursos)
python main.py --cloud aws --region us-east-1 --verify-only

# Dry-run (mostra o que seria testado, sem criar nada)
python main.py --cloud aws --region us-east-1 --dry-run

# Limpar recursos de teste órfãos
python main.py --cleanup-orphans --cloud aws --region us-east-1

# Relatório Markdown amigável ao cliente (veredito em linguagem clara + remediação)
python main.py --cloud aws --region us-east-1 --format markdown --output report.md

# Gating estrito de CI: sai com código != 0 também em warnings / NOT-VERIFIED
python main.py --cloud aws --region us-east-1 --strict --json --quiet

# Escopar a validação de rede BYO a um VPC e/ou security group (AWS)
python main.py --cloud aws --region us-east-1 --vpc-id vpc-xxxxxxxx --sg-id sg-xxxxxxxx

# Validar o conteúdo de TRUST da role cross-account (AWS)
python main.py --cloud aws --region us-east-1 --databricks-account-id <uuid-da-conta-databricks>

# Validar uma VNet existente para VNet injection, incl. cross-subscription (Azure)
python main.py --cloud azure --subscription-id <id> --vnet-id "<resource-group>/<nome-da-vnet>"

# Logging de debug
python main.py --cloud aws --region us-east-1 --log-level debug --log-file debug.log
```

### Validação direcionada / BYO-network

| Flag | Cloud | O que valida |
|------|-------|--------------|
| `--vpc-id` | AWS | Escopa as checagens de rede a um VPC: contagem de subnets privadas, distribuição em AZs, tamanho da subnet (/17–/26) e NAT/egress para deployments sem PrivateLink. |
| `--sg-id` | AWS | Valida as regras de um security group existente (ingress/egress intra-SG de todo o tráfego + egress para o control plane). |
| `--databricks-account-id` | AWS | Valida o *conteúdo* do trust da role cross-account (principal de assinatura da Databricks `414351767826` + sua conta como ExternalId), não apenas que você consegue criar a role. |
| `--vnet-id` | Azure | Valida uma VNet existente para VNet injection: subnets delegadas à Databricks, associação de NSG e tamanho da subnet. Aceita id ARM completo ou `<rg>/<nome-da-vnet>`. |

### Formatos de saída

```bash
--format text        # padrão: relatório rico no terminal
--format markdown    # relatório amigável ao cliente (veredito, itens de ação, links de docs)
--format json        # legível por máquina, para CI/CD
--json               # atalho para --format json
```

As linhas de progresso/status vão para o **stderr**, então o `--json` no **stdout** é JSON puro e parseável, e um relatório Markdown redirecionado não vem com ruído de progresso — seguro para pipe direto em CI (`... --json --quiet > report.json`).

### Modo verify-only

A flag `--verify-only` roda checagens de permissão read-only sem criar nenhum recurso temporário. Útil quando:

- A criação de recursos exige aprovação da sua organização
- Você quer uma validação rápida de credenciais e recursos existentes
- Você está num ambiente restrito onde a criação de recursos é bloqueada

**Limitações do modo verify-only:**
- Não verifica completamente permissões de escrita (ex.: criar bucket, criar VNet)
- Usa simulação de política IAM quando disponível, que pode não refletir todas as condições
- Algumas checagens aparecem como "WARNING" em vez de pass/fail definitivo

## Matriz de Compatibilidade de Deployment

Desde a v1.2.0, a ferramenta roda **todas as checagens automaticamente** e produz uma matriz de compatibilidade ao final de cada relatório. Não é preciso a flag `--mode` — o relatório diz quais tipos de deployment suas permissões atuais suportam.

Cada tipo de deployment é reportado com um de quatro estados honestos:

| Estado | Significado |
|--------|-------------|
| **SUPPORTED** | Todas as áreas que o modo precisa foram verificadas e estão OK. |
| **NOT SUPPORTED** | Uma área necessária tem um bloqueador real (permissão faltando / falha ao criar). O detalhe lista qual área. |
| **REVIEW** | As permissões foram verificadas, mas uma área necessária tem um aviso acionável (ex.: subnet pequena demais, sem NAT/egress) — não é bloqueador, mas vale revisar antes do deploy. |
| **NOT VERIFIED** | Não foi possível confirmar uma área necessária (simulação IAM indisponível — ex.: sob SSO — `--verify-only`, ou nenhum recurso alvo informado). A ferramenta nunca reporta isso silenciosamente como SUPPORTED. |

```
║  Standard               SUPPORTED                                    ║
║  PrivateLink            NOT SUPPORTED (missing perms)                ║
║  Unity Catalog          REVIEW (advisories, no blockers)            ║
║  Full                   NOT VERIFIED                                 ║
```

A linha de detalhe de cada modo sempre nomeia o motivo **real** (qual área, e se foi bloqueador, aviso ou apenas não-verificável) em vez de uma mensagem genérica.

## Verificações Específicas para Databricks

### AWS

| Categoria | Verificações |
|-----------|--------------|
| **Credenciais** | STS GetCallerIdentity, Account ID, Region |
| **IAM** | Simulação de políticas (ec2, s3, iam, kms), Cross-account role permissions |
| **Rede** | VPC DNS settings, Subnets (private/public), Security Groups, NAT Gateways, AZs |
| **PrivateLink** | VPC Endpoints existentes, S3/STS/Kinesis endpoints, Permissões de criação |
| **Storage** | S3 buckets, DBFS/Unity Catalog permissions, Public access block |
| **Quotas** | VPCs, Elastic IPs, Security Groups, vCPUs |

### Azure

| Categoria | Verificações |
|-----------|--------------|
| **Credenciais** | Service Principal, Subscription state, Resource Group |
| **RBAC** | Role assignments, Contributor/Owner, Resource Providers |
| **Rede** | VNet injection readiness, Subnet delegation, NSGs, NAT Gateway |
| **Private Link** | Private Endpoints, Private DNS Zones (azuredatabricks.net, blob, dfs) |
| **Storage** | ADLS Gen2 accounts, HNS enabled, Storage creation |
| **Quotas** | VNets, NSGs, Public IPs, vCPUs |
| **Key Vault** | Vaults, Soft delete, Purge protection |

### GCP

| Categoria | Verificações |
|-----------|--------------|
| **Credenciais** | Service Account, Project state, Project number |
| **APIs** | compute, storage, iam, iamcredentials, serviceusage, container, deploymentmanager, cloudkms, dns (conjunto SRA completo) |
| **IAM** | testIamPermissions dirigido pelo conjunto de permissões SRA completo, subconjuntos deploy-blocking, impersonation (actAs), PSC/DNS |
| **Rede** | Custom VPC, Subnets, Private Google Access, Firewall rules, Cloud NAT |
| **Private Connectivity** | Private Google Access per subnet, Private Service Connect, Cloud NAT |
| **Storage** | GCS buckets, Uniform bucket-level access |
| **Quotas** | Networks, Subnetworks, CPUs, Disks, Instances |
| **KMS** | Key rings, CMEK readiness |

## Formato de Saída

```
======================================================================
  DATABRICKS TERRAFORM PRE-CHECK REPORT
  Cloud: AWS | Region: us-east-1
  Date: 2025-12-03 10:30:00
  Account: 123456789012 | ARN: arn:aws:iam::123456789012:user/admin
======================================================================

[CREDENTIALS]
  AWS Credentials (STS)                        OK - Valid credentials
  Account ID                                   OK - 123456789012
  Region Configuration                         OK - us-east-1

[IAM PERMISSIONS (Databricks-specific)]
  IAM Policy Simulation                        OK - Can simulate policies
  EC2 Permissions                              OK - All 9 critical permissions allowed
  S3 Permissions (DBFS/Unity Catalog)          OK - All 6 critical permissions allowed
  IAM Permissions (Instance Profiles)          OK - All 6 critical permissions allowed
  KMS Permissions (Encryption)                 OK - All encryption permissions allowed

[NETWORK (VPC Configuration)]
  VPC Access                                   OK - Found 3 VPC(s)
  VPC DNS (vpc-12345...)                       OK - DNS support and hostnames enabled
  Subnet Configuration                         OK - 6 total (4 private, 2 public)
  Available IP Addresses                       OK - 1024 IPs available
  Security Group Access                        OK - Found 15 security group(s)
  NAT Gateway (for private subnets)            OK - Found 2 active NAT gateway(s)
  Availability Zones                           OK - 3 AZs available (multi-AZ supported)

[PRIVATELINK / VPC ENDPOINTS]
  Existing VPC Endpoints                       OK - 1 Gateway, 3 Interface
  S3 Gateway Endpoint                          OK - S3 Gateway endpoint configured
  VPC Endpoint Services Access                 OK - Can list available services
  VPC Endpoint Management                      OK - Can create/modify/delete endpoints

[STORAGE (S3 for DBFS/Unity Catalog)]
  S3 Bucket Listing                            OK - Found 12 bucket(s)
  Databricks-related Buckets                   OK - Found 2 Databricks bucket(s)
  S3 Bucket Creation Check                     OK - Can check bucket availability
  S3 Public Access Block                       OK - Account-level public access blocked

[QUOTAS & LIMITS]
  VPC Quota                                    OK - 3/5 used
  Elastic IP Quota                             WARNING - 4/5 used - almost at limit
  Security Groups                              OK - 15 security groups in region
  EC2 On-Demand vCPU Quota                     OK - Limit: 256 vCPUs

======================================================================
  SUMMARY: 25 OK | 1 WARNING | 0 NOT OK
  STATUS: PASSED WITH WARNINGS
======================================================================
```

## Configuração de Credenciais

### AWS

A ferramenta detecta credenciais automaticamente de:

1. **Variáveis de ambiente**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
2. **Arquivo de credenciais**: `~/.aws/credentials`
3. **Instance metadata** (EC2, ECS, Lambda)

### Azure

Credenciais são detectadas de:

1. **Variáveis de ambiente**: `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
2. **Azure CLI**: `az login`
3. **Managed Identity** (quando rodando no Azure)

### GCP

Credenciais são detectadas de:

1. **Variável de ambiente**: `GOOGLE_APPLICATION_CREDENTIALS`
2. **Application Default Credentials**: `gcloud auth application-default login`
3. **Service Account** (quando rodando no GCP)

## Integração com CI/CD

```yaml
# Exemplo GitHub Actions
- name: Databricks Pre-Check
  run: |
    # o stdout é JSON puro (o progresso vai para stderr); --strict faz o job
    # falhar também em warnings / NOT-VERIFIED, não só em bloqueadores.
    python main.py --cloud aws --region us-east-1 --strict --json --quiet > pre-check.json

- name: Upload Report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: pre-check-report
    path: pre-check.json
```

**Códigos de saída:** `0` = passou · `2` = bloqueadores encontrados (permissões negadas) ·
`1` = passou, mas sob `--strict` houve warnings / itens NOT-VERIFIED.

## Permissões Necessárias

### AWS - IAM Policy mínima para rodar o pre-check

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ec2:Describe*",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "iam:ListRoles",
        "iam:ListInstanceProfiles",
        "iam:SimulatePrincipalPolicy",
        "kms:ListKeys",
        "service-quotas:GetServiceQuota"
      ],
      "Resource": "*"
    }
  ]
}
```

### Azure - RBAC mínimo

- **Reader** no Subscription (para verificações)
- Ou **Contributor** para verificações completas

### GCP - IAM roles mínimos

- `roles/viewer` no projeto
- Ou roles específicos: `compute.viewer`, `storage.objectViewer`, `iam.securityReviewer`

## Troubleshooting

### "No credentials found"

```bash
# AWS
aws configure
# ou
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx

# Azure
az login
# ou
export AZURE_CLIENT_ID=xxx
export AZURE_CLIENT_SECRET=xxx
export AZURE_TENANT_ID=xxx

# GCP
gcloud auth application-default login
# ou
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

### "Access Denied" ou "Permission Denied"

Verifique se as credenciais têm as permissões listadas acima. Use o relatório para identificar quais permissões específicas estão faltando.

### SDK não instalado

```bash
# Ativar virtual environment
source venv/bin/activate

# Reinstalar dependências
pip install -r requirements.txt
```

## Licença

MIT
