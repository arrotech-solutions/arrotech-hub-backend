# Arrotech Hub on AWS: Infrastructure and Terraform Learning Guide

This guide explains how Arrotech Hub's backend is hosted, how a code change
reaches production, what Terraform currently manages, and how to reason about
the AWS services involved. It is written for someone learning AWS and Terraform
from the beginning, using this project as the example.

> **Important: distinguish the running design from the Terraform boundary.**
> The production backend is designed to run on one EC2 virtual machine using
> Docker Compose. The Terraform in `terraform/` describes only a small set of
> EC2-related resources and expects an existing AWS account/network. It does
> not create a complete new environment. Read the Terraform safety notes before
> running `terraform apply`.

## What you will learn

After working through this guide, you should be able to explain:

- What an AWS account, region, IAM role, VPC, subnet, security group, EC2
  instance, EBS volume, Elastic IP, S3 bucket, and Systems Manager do here.
- How a request travels from a browser to the Arrotech Hub API.
- How Docker Compose runs the application and its supporting services.
- How GitHub Actions deploys code without opening SSH to GitHub.
- What Terraform manages today, how Terraform state and plans work, and what
  must be checked before changing a real environment.
- Which pieces are intentionally not AWS-managed services in the current
  design.

## 1. The short version

Arrotech Hub's production backend is a Dockerized FastAPI application hosted
on an Ubuntu EC2 instance. A public Elastic IP gives the host a stable address.
The instance's security group allows inbound web traffic on ports 80 and 443.
Nginx accepts that traffic, handles HTTPS certificates, and forwards API
requests to the app container on port 8000. PostgreSQL, Redis, Celery workers,
and the scheduler are separate containers on the same host; their ports are
not published to the internet.

On a push to `main`, GitHub Actions runs the required checks, uses GitHub
OpenID Connect (OIDC) to assume a narrowly scoped AWS role, and asks AWS
Systems Manager (SSM) to run the deployment commands on the EC2 host. The host
fetches the latest Git commit, builds the Docker images, restarts the relevant
containers, and checks health.

Terraform is used to describe and reconcile selected existing AWS resources.
It is not currently the full environment builder: the VPC, subnet, IAM roles,
S3 backup bucket, DNS, certificate, host operating system, and Docker services
are outside its declared resources.

## 2. Architecture at a glance

```text
User / browser / external webhook
              |
              | HTTPS: prod.api.arrotechsolutions.com
              v
      DNS A record (managed outside this Terraform)
              |
              v
      Elastic IP (stable public IPv4)
              |
              v
      EC2 security group: inbound TCP 80 and 443
              |
              v
      Ubuntu EC2 instance (t3.small)
       Docker Compose production network
       ┌──────────────────────────────────────────────┐
       │ Nginx :80/:443                               │
       │   └── forwards API traffic to app :8000      │
       │ FastAPI app :8000 (container-only)            │
       │ PostgreSQL :5432 (container-only)             │
       │ Redis :6379 (container-only)                  │
       │ Celery worker and Celery Beat                 │
       │ Alembic database migrator                    │
       └──────────────────────────────────────────────┘
          Docker named volumes on the EC2 host disk
              |
              +---- scheduled database dump ----> S3 backup bucket

GitHub Actions --OIDC--> IAM deployment role --SSM--> EC2 host
```

This is a single-host architecture. It is easy to understand and relatively
inexpensive, but the EC2 host is a single point of failure. The Compose
production file describes the backend stack; frontend hosting is separate.
The frontend repository has Vercel configuration, but the exact live hosting
account and deployment settings are not established by this backend
configuration.

## 3. AWS building blocks, from first principles

### AWS account and region

An AWS account is the administrative and billing boundary for resources. A
region is a geographic area in which AWS runs services. The Terraform provider
defaults to `us-east-1`, and the production workflow examples also use that
region. Resource IDs such as EC2 instance IDs and VPC IDs are specific to an
account and region.

Before running AWS commands, verify the identity and region rather than
assuming the active credentials are correct:

```powershell
aws sts get-caller-identity
aws configure list
```

Terraform's AWS provider uses the profile selected by `aws_profile` in
`terraform.tfvars`; do not paste credentials into Terraform files. The default
profile name in `variables.tf` is `arrotech`.

### IAM: identities and permissions

IAM controls who or what can call AWS APIs. This deployment has two different
IAM relationships:

1. **GitHub Actions deployment identity:** GitHub obtains a short-lived OIDC
   token and assumes an AWS IAM role. That role can send an SSM command to the
   production instance and retrieve its command result. It avoids storing
   long-lived AWS access keys in GitHub.
2. **EC2 instance identity:** an IAM instance profile attaches a role to EC2.
   The backend documentation requires an instance profile named
   `arrotech-hub-ec2-ssm-role` with `AmazonSSMManagedInstanceCore`. This lets
   the instance register with Systems Manager. The role also needs only the
   additional permissions actually required by the host, such as narrowly
   scoped write access to the backup bucket if the host uploads backups.

These are not interchangeable. The GitHub role lets CI request a deployment;
the EC2 role lets the machine communicate with AWS services. Avoid personal
access keys, broad `AdministratorAccess`, and credentials embedded in a Docker
image.

The backend README contains the example OIDC trust and deployment permission
policies used to configure GitHub Actions. Treat them as templates: replace
the placeholders, scope them to the actual account, repository, environment,
and instance, and review them against the current workflow before use.

### VPC, subnet, routes, and security group

A VPC is a private network boundary in an AWS region. A subnet is a range of
IP addresses inside that VPC. Route tables determine where traffic goes. For
an instance to be reachable directly from the public internet, its network
placement and routes must support public connectivity (commonly a public
subnet with a route to an Internet Gateway and a public IPv4 address).

The current Terraform variables take an existing `vpc_id` and `subnet_id`.
There is no `aws_vpc`, subnet, route table, or Internet Gateway resource in
the Terraform configuration. Verify these existing network prerequisites in
AWS; do not infer that Terraform will create them.

A security group is a stateful virtual firewall attached to a network
interface. The Terraform security group allows:

| Direction | Protocol / port | Source / destination | Purpose |
|---|---|---|---|
| Inbound | TCP 80 | `0.0.0.0/0` | HTTP and HTTP-based certificate validation |
| Inbound | TCP 443 | `0.0.0.0/0` | Public HTTPS |
| Outbound | All | `0.0.0.0/0` | Updates, Git fetch, package/API access, and other egress |

The Terraform security group does **not** allow inbound SSH on port 22. That
matches the SSM-based GitHub deployment and avoids opening SSH to the world.
The separate historical `scripts/provision-aws.ps1` script does open port 22
to `0.0.0.0/0`; do not use that script as the production security baseline.
For emergency human access, prefer SSM Session Manager. If SSH is explicitly
required, restrict it to a trusted source address and review the rule.

### EC2, EBS, and Elastic IP

EC2 is AWS's virtual-machine service. The configured application host is
`t3.small` (2 vCPU and 2 GiB RAM according to the production Compose comments).
The instance runs Ubuntu and Docker; application services are containers on
that host.

EBS is block storage attached to an EC2 instance. The active Terraform
instance declares a 30 GiB `gp3` root volume with encryption enabled and
delete-on-termination enabled. Docker's named volumes for PostgreSQL, Redis,
uploads, and logs are local to the instance and ultimately depend on its
attached storage. A volume is not the same thing as a backup: deleting or
losing the instance can still lose local data.

The configuration also describes a rollback EC2 instance whose root volume is
declared unencrypted. It is retained as an infrastructure rollback resource;
it should not be treated as a preferred current host. Confirm its actual
status and data-handling needs before any changes.

An Elastic IP (EIP) is a stable public IPv4 address that can be associated
with an EC2 instance. It lets DNS keep pointing at the same address when an
instance is replaced. The current Terraform EIP is associated with the active
backend instance. EIP allocation and association can have AWS charges; check
current AWS pricing and avoid leaving unused addresses allocated.

### S3

S3 is object storage. `scripts/backup-db.sh` makes a compressed PostgreSQL
dump and uploads it below the `db-backups` prefix in the
`arrotech-hub-backups-prod` bucket. The bucket is **not** declared in the
current Terraform files. The provisioning script tries to create it, but that
is a separate, historical, non-idempotent provisioning path.

The backup script keeps local dumps for seven days. Its comments expect S3
lifecycle management for remote retention, but neither the bucket nor its
lifecycle policy is configured in the Terraform shown here. A successful
upload is not enough to prove recoverability: periodically download a backup
and perform a restore test in a safe environment. The bucket should have
public access blocked, encryption enabled, access limited to the instance
role, and a deliberate retention/lifecycle policy.

### Systems Manager (SSM)

SSM is AWS's managed way to run commands on registered instances. The
production GitHub workflow sends an `AWS-RunShellScript` command to the
configured instance ID, waits for the command result, and reports failure if
the command fails or times out. For this to work:

- The EC2 instance must have a functioning SSM Agent.
- Its instance profile must allow SSM core operations.
- The host needs network access to the SSM service endpoints (usually through
  internet egress or configured VPC endpoints).
- The GitHub OIDC role must trust the intended repository/environment and
  have the needed `ssm:SendCommand` and result-read permissions.

SSM is the transport for the deployment command; it does not build or store
the app image. The host fetches code and builds images itself.

### DNS, TLS, and Nginx

DNS maps the API hostname `prod.api.arrotechsolutions.com` to the EIP using an
A record. The DNS zone is not managed in this Terraform configuration.

Certbot obtains a Let's Encrypt certificate on the host. Nginx runs in a
container, publishes ports 80 and 443, terminates HTTPS, and proxies requests
to the FastAPI container on port 8000. The certificate files are read from
`/etc/letsencrypt` on the host. The SSL setup script includes a renewal
schedule that restarts Nginx after renewal. Before relying on automatic
renewal, verify the ACME challenge directory end to end:
`ssl-setup.sh` writes challenges to the host's `/var/www/certbot`, while
`docker-compose.prod.yml` mounts a Docker named volume at the Nginx container's
`/var/www/certbot`. Those are different storage locations unless synchronized,
so renewal through the live Nginx container may fail. Confirm renewal with a
dry run and align the mounts before treating it as operational.

## 4. What actually runs on the EC2 host

The production stack is described in
[`docker-compose.prod.yml`](../docker-compose.prod.yml):

| Compose service | Role | Publicly exposed? |
|---|---|---|
| `nginx` | Internet-facing reverse proxy and TLS termination | Yes: host ports 80 and 443 |
| `app` | FastAPI API process | No; reachable inside Compose on port 8000 |
| `migrator` | Runs Alembic database migrations before the app starts | No |
| `postgres` | PostgreSQL 15 application database | No; container network only |
| `redis` | Cache, Celery broker/backend, and related app state | No; container network only |
| `celery-worker` | Runs asynchronous background jobs | No |
| `celery-beat` | Schedules periodic Celery tasks | No |

Compose health checks and restart policies help detect or restart individual
containers. Named volumes persist data across a container recreation, but
they remain on this one EC2 host. The EC2 host itself is memory-constrained;
Compose limits are intentional and should be reassessed before adding
services.

Do not describe this as RDS, ElastiCache, ECS, or Kubernetes. The current
production database and cache are Docker containers, not managed AWS database
services. Do not describe the production Compose configuration as using
CloudWatch logging either: it configures the Docker `json-file` logging
driver with local rotation. The comments in Compose contrast production with
the larger local observability stack; they do not configure CloudWatch Logs.

## 5. How a production deployment works

The deployment workflow is in
[`ci.yml`](../.github/workflows/ci.yml). Its production path is:

1. A push to `main` runs the workflow's required security, architecture, and
   test jobs.
2. The deploy job is restricted to pushes on `main` and uses the GitHub
   `production` environment. It requests an OIDC token (`id-token: write`)
   and assumes the role named by the `AWS_DEPLOY_ROLE_ARN` environment secret.
3. GitHub sends an SSM command to the instance ID in
   `EC2_INSTANCE_ID`, in the region in `AWS_REGION`.
4. On the EC2 host, the command runs as the `ubuntu` user, fetches
   `origin/main`, and resets the checkout to that commit.
5. Docker Compose builds the `app` and `celery-worker` images, then restarts
   `app`, `celery-worker`, `celery-beat`, and `nginx`. The Compose file's
   migrator dependency runs database migrations before the app becomes
   healthy.
6. The workflow checks the local app health endpoint and the external
   production HTTPS endpoint. On failure, it resets the Git checkout to the
   previous commit, rebuilds/restarts services, and reports failure.
7. GitHub polls SSM for the command status and fails the job for failed,
   timed-out, or undeliverable commands. A following job performs a production
   health check.

GitHub needs the `production` Environment configured with:

- Secret `AWS_DEPLOY_ROLE_ARN`.
- Variables `AWS_REGION` and `EC2_INSTANCE_ID`.
- The existing `PROD_API_URL` secret used by the post-deployment health check.

The trust policy should limit OIDC assumption to the exact repository and
`production` environment. Restrict that GitHub environment to `main` and
consider requiring approval. The existing workflow is the authoritative
implementation; `scripts/deploy.sh` is a separate manual deployment helper
and is not the same path as the current SSM workflow.

## 6. Terraform fundamentals through this project

Terraform is an Infrastructure as Code (IaC) tool. You write declarations in
`.tf` files describing the intended resources. The AWS provider translates
those declarations into AWS API operations.

### The basic Terraform cycle

1. **Configuration** (`.tf`): resource declarations, provider settings, and
   variables. In this project, see [`main.tf`](../terraform/main.tf),
   [`ec2.tf`](../terraform/ec2.tf), and
   [`variables.tf`](../terraform/variables.tf).
2. **Initialization** (`terraform init`): downloads the declared provider and
   initializes the working directory.
3. **Planning** (`terraform plan`): compares configuration, Terraform state,
   and observed AWS resources; displays proposed actions. Planning does not
   apply infrastructure changes.
4. **Apply** (`terraform apply`): executes the approved plan against AWS.
5. **State** (`terraform.tfstate`): Terraform's mapping between configuration
   resource addresses and real AWS object IDs, plus resource attributes.

A Terraform resource address is a name in configuration, for example
`aws_instance.backend`. An AWS instance ID is the real resource identifier,
such as `i-...`. Importing connects an already-existing AWS resource to a
Terraform address/state entry; it does not, by itself, make the configuration
match that resource.

### What the files declare

[`main.tf`](../terraform/main.tf):

- Requires Terraform `>= 1.5.0`.
- Uses the HashiCorp AWS provider version constraint `~> 5.0`.
- Configures the provider with `aws_region` and `aws_profile`.

[`ec2.tf`](../terraform/ec2.tf):

- Declares a security group called `arrotech-hub-sg` in the supplied VPC.
- Declares an active `t3.small` EC2 instance with an encrypted 30 GiB gp3 root
  disk, supplied AMI/key/profile/subnet, and the declared security group.
- Declares a second rollback instance with an unencrypted 30 GiB gp3 disk.
- Declares an EIP associated with the active instance.
- Sets `prevent_destroy = true` on the security group, both instances, and EIP.

`prevent_destroy` is a Terraform guard against plans that would destroy those
resources while the lifecycle rule remains in configuration. It does not
prevent all changes, data loss, manual AWS Console changes, or accidental
resource replacement outside Terraform.

[`variables.tf`](../terraform/variables.tf) declares the region, profile, and
values such as instance IDs, VPC/subnet IDs, AMI IDs, key-pair name, and
instance-profile name. The example file,
[`terraform.tfvars.example`](../terraform/terraform.tfvars.example), contains
placeholder values only.

### Critical caveat: the current configuration is not a ready-made import

The backend README describes this Terraform directory as an import of existing
resources. However, the `.tf` configuration itself does not contain Terraform
`import` blocks. Also, some declared input variables (including the supplied
instance IDs, existing security-group ID, and EIP allocation ID) are not used
by the resource declarations shown. Those declarations describe resources to
create or reconcile; they do not automatically attach themselves to existing
IDs merely because IDs are present in `terraform.tfvars`.

Therefore:

- Do not run `terraform apply` on a first checkout and assume it will only
  import resources.
- Do not assume `terraform plan` is harmless; it can propose creating, updating,
  or replacing real AWS resources.
- Do not add existing resources by importing until you have verified that each
  Terraform resource's arguments match the live AWS resource and state has
  been inspected by the infrastructure owner.
- The Terraform tree must be reconciled with the actual account and the
  October 2026 encryption cutover before it can be safely treated as a
  reproducible production definition.

The old README's import-only expectation is not guaranteed by these
declarations. Treat the actual plan as authoritative and stop if it proposes
anything unexpected.

### Safe first-time Terraform workflow

These commands are for a Windows PowerShell terminal in the backend
repository. Use only an authorized AWS profile. This workflow initializes and
plans; it intentionally does not include an unconditional apply command.

```powershell
Set-Location .\terraform
Copy-Item .\terraform.tfvars.example .\terraform.tfvars
# Edit terraform.tfvars with verified values using a secure local editor.
terraform init
terraform fmt -check
terraform validate
terraform plan -out=tfplan
terraform show tfplan
```

Before anyone applies:

1. Confirm `aws sts get-caller-identity` is the intended AWS account.
2. Confirm the selected region and profile.
3. Confirm whether the resources are already in Terraform state.
4. Verify the live EC2, security group, EIP, AMI, subnet, instance profile,
   and EBS encryption settings against the configuration.
5. Read the entire plan. Any unexpected create, in-place update, replacement,
   or destroy is a stop condition. Ask the infrastructure owner to reconcile
   configuration/state first.
6. Get an independent review for production changes. Apply only the reviewed
   saved plan, and record the resulting state securely.

If importing is needed, an authorized operator must import each pre-existing
resource under the correct resource address using the resource's actual AWS
identifier (for example, `aws_instance.backend` with the instance ID or
`aws_eip.backend` with the EIP allocation ID), then run and review a new plan.
Importing is not a substitute for matching the resource configuration. Do not
copy IDs from another account or environment, and do not repeat an import if
the resource is already tracked in state.

### Terraform state is sensitive infrastructure data

Terraform state can contain resource identifiers, network topology, and
provider-returned attributes; for other projects it can also include secret
values. This repository's `.gitignore` excludes state, local `.tfvars`, and
plan files. Keep those protections in place:

- Never commit or share `terraform.tfstate`, backups, `.tfvars`, or saved plans.
- Keep local state on an access-controlled, encrypted workstation and make
  protected backups before state operations.
- Local state does not provide team collaboration or remote locking. Do not
  let multiple operators run Terraform against the same local state.
- For a team-managed production setup, design a remote backend (for example,
  a restricted S3 state bucket with versioning, encryption, and locking
  supported by the selected Terraform version) and migration/restore process
  before multiple people operate it.
- A saved plan can reveal infrastructure details. Protect it and remove it
  when no longer needed.

## 7. From a fresh AWS account to an Arrotech deployment

This section is a learning sequence, not a claim that the checked-in
Terraform provisions all of these steps. The project expects several
prerequisites to exist outside Terraform today.

### Step 1: establish account access and guardrails

Use a dedicated AWS account or approved environment, enable MFA for human
access, and avoid root-user access for routine work. Choose a region
consistently. Create an operator role/profile with only the permissions
needed for the learning exercise. Confirm account identity before creating
billable resources.

### Step 2: provide the network

Create or select a VPC, subnet, route table, and Internet Gateway if the
backend is to be directly public. Decide whether a public IPv4 on the host is
acceptable; a more controlled design may put the host behind a load balancer
or use private subnets and managed access. This is an architectural decision,
not a resource currently defined by this Terraform directory.

### Step 3: create host access and permissions

Attach an EC2 instance profile that enables Systems Manager. Confirm SSM
Agent registration and connectivity before depending on SSM. Grant the
instance only the permissions it needs, including scoped S3 backup access
when backups are enabled. Avoid public SSH ingress.

### Step 4: prepare host and application

The project bootstrap helper is
[`server-setup.sh`](../scripts/server-setup.sh). It installs Docker,
Docker Compose, AWS CLI, Certbot, and utilities on Ubuntu; configures swap
and Docker logs; and prints follow-up steps. Review a bootstrap script before
running it on a production server. Clone the backend repository, create the
ignored `.env.production` file with production secrets, and never put that
file in source control.

The production Compose file starts the app and backing containers. Database
passwords and Redis credentials must be strong and unique; the Compose
configuration requires `POSTGRES_PASSWORD` but has a fallback Redis password
that must be overridden for production.

### Step 5: configure DNS and HTTPS

Point the API hostname's DNS A record to the EIP, wait for DNS propagation,
and verify that ports 80 and 443 reach Nginx. Run
[`ssl-setup.sh`](../scripts/ssl-setup.sh) after checking its domain and email
settings. It requests a certificate and configures renewal. Do not request
repeated production certificates during testing; use its staging option
first when appropriate.

### Step 6: make backups recoverable

Create and secure the S3 backup bucket outside Terraform, grant the EC2 role
only the required bucket/prefix actions, and configure a retention lifecycle.
Review and schedule [`backup-db.sh`](../scripts/backup-db.sh). Test restores.
The script's comments suggest a daily 3 AM UTC cron entry, but scheduling,
bucket policy, lifecycle, and restore testing are operator responsibilities
in the current configuration.

### Step 7: configure GitHub OIDC and SSM deployment

Create the GitHub OIDC identity provider and deployment role with a trust
policy restricted to this repository and its `production` environment.
Attach permissions limited to the intended instance and SSM document. Add the
required secret and variables to GitHub's `production` environment. Ensure
the environment only accepts intended `main` deployments and has appropriate
review controls.

### Step 8: reconcile and operate Terraform

Use the Terraform safety workflow above to inspect the existing resources and
state. Establish a reviewed, reliable state strategy before using Terraform
for repeated production changes. The current configuration is not the
greenfield recipe for all prerequisite steps.

## 8. Historical provisioning script: read before use

[`provision-aws.ps1`](../scripts/provision-aws.ps1) is a separate AWS CLI
script, not Terraform. It attempts to create a key pair, security group,
EC2 instance, EIP, and S3 bucket. It is not aligned with the safer current
deployment assumptions:

- It opens SSH port 22 to `0.0.0.0/0`.
- It hard-codes an AMI ID and assumes a region/default network context.
- It does not attach the SSM instance profile described in the production
  deployment documentation.
- It creates resources separately from Terraform and can cause duplicate
  resources or ownership drift.
- Its bucket handling does not configure access controls, encryption,
  lifecycle, or a Terraform-managed policy.

Do not run this script in a production account as a shortcut or alongside
Terraform without a reviewed migration plan. Use it only as historical
context; build a complete, reviewed IaC configuration if a new environment
must be provisioned.

## 9. Operations and troubleshooting

### Check application and container health

On the EC2 host:

```bash
cd /home/ubuntu/arrotech-hub-backend
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail 100 app
curl -fsS http://localhost:8000/health
```

The `app` health endpoint is inside the host/container network. Check the
public TLS endpoint separately:

```bash
curl -fsS https://prod.api.arrotechsolutions.com/health
```

### Common symptoms

| Symptom | First checks |
|---|---|
| Host unreachable | Instance state, subnet route, EIP association, security-group ports 80/443, and DNS |
| HTTPS certificate fails | DNS points to the EIP, port 80 is reachable for ACME, certificate files exist, Nginx config is valid |
| GitHub deploy cannot reach instance | SSM Agent status, instance profile, SSM network egress/endpoints, correct region/instance ID |
| GitHub cannot assume role | OIDC provider, role trust conditions, GitHub environment secret, repository/environment spelling |
| App fails after deployment | SSM command output, Compose status/logs, environment file, migration health, host disk/memory |
| Database or Redis unavailable | Container health, Compose dependency status, credentials, local volume/disk health |
| Backups absent | Cron configuration, script logs, AWS CLI identity on host, bucket policy/role permissions, upload path |

### Monitoring limitations

The production Compose file uses Docker's local rotating JSON logs. The
resource checker script inspects local disk, memory, and container health,
and can attempt email alerts if a mail command is configured. This is not
equivalent to centralized monitoring: CloudWatch alarms/log groups, metrics
dashboards, on-call notifications, and backup alarms are not provisioned by
the Terraform shown here. Decide explicitly how production alerts and logs
will be retained and monitored.

## 10. Security, availability, and cost concepts

### Security responsibilities

- Keep `.env.production`, private keys, AWS credentials, Terraform state, and
  plans out of source control and chat.
- Prefer OIDC and IAM roles over long-lived access keys.
- Keep database and Redis ports private to the Docker network.
- Restrict security-group rules to only required ports.
- Encrypt disks and backups, restrict S3 access, and test restoration.
- Patch the host and base images. An encrypted disk does not replace
  application-level authorization or a backup.
- Protect the production GitHub environment and review deployment permissions.

### Availability and recovery

One EC2 host means host failure, maintenance, or a bad disk can interrupt the
whole backend. Docker restart policies only help with some container failures;
they do not create a second host or high availability. Database backups to S3
are the primary stated off-host recovery mechanism, but restoration must be
practiced. The rollback instance is not a replacement for tested database
recovery or automated failover.

To increase availability, the architecture would need additional design:
for example, a load balancer and multiple app hosts, managed PostgreSQL,
managed Redis, automated image publication, health-based failover, and
multi-AZ network resources. Those services add complexity and cost and are
not part of the current Terraform implementation.

### Cost

The Compose comments state a target budget of roughly `$30-50/month`; treat
that as an estimate, not a quote or guarantee. AWS charges depend on region,
instance runtime, EBS, public IPv4/EIP use, S3 storage and requests, data
transfer, and other enabled services. Use AWS pricing and billing alerts for
the selected region/account. Stop or remove learning resources when finished,
but never destroy production infrastructure without an approved recovery and
change plan.

## 11. Explain it to someone else

> “Arrotech Hub's backend runs as Docker containers on an Ubuntu EC2 server.
> DNS points the API hostname to a stable Elastic IP. The EC2 security group
> exposes only web ports; Nginx handles HTTPS and forwards requests to FastAPI.
> PostgreSQL, Redis, and Celery run privately as Compose services on that same
> host. GitHub Actions tests changes on `main`, uses OIDC to assume a limited
> AWS role, then uses Systems Manager to tell the server to pull, build, and
> restart the application. PostgreSQL dumps are uploaded to S3. Terraform
> currently describes selected EC2-related resources, but not the complete
> VPC, IAM, DNS, S3, or application setup, so we inspect state and plans
> carefully before making infrastructure changes.”

## 12. Glossary

| Term | Meaning in this deployment |
|---|---|
| AWS account | The billing and administrative boundary containing the AWS resources |
| Region | Geographic AWS area; the configured default is `us-east-1` |
| IAM | AWS identity and permission system |
| OIDC | Short-lived identity exchange used by GitHub Actions to assume an AWS role |
| IAM role | Temporary permissions assumed by GitHub Actions or attached to EC2 |
| Instance profile | The mechanism that attaches an IAM role to an EC2 instance |
| VPC | Private virtual network containing the backend subnet |
| Subnet | Address range and placement for the EC2 network interface |
| Security group | Stateful firewall rules for the EC2 instance |
| EC2 | Virtual machine that runs Ubuntu and Docker |
| EBS | Block storage attached to the EC2 instance |
| Elastic IP | Stable public IPv4 address associated with the active EC2 instance |
| S3 | Object storage used as the target for database backup files |
| SSM | Systems Manager; runs remote commands without inbound SSH |
| Docker Compose | Starts and connects the application and its supporting containers |
| Terraform provider | Terraform plugin that talks to AWS APIs |
| Terraform state | Mapping of Terraform resource addresses to real infrastructure |
| Terraform plan | Preview of proposed infrastructure changes |
| Import | Adding an existing AWS resource to Terraform state |
| ECR | AWS container registry; not used by the current host-build deployment |
| RDS | Managed relational database; not used by the current Compose deployment |
| ElastiCache | Managed Redis-compatible cache; not used by the current deployment |
| ECS | AWS container orchestration service; not used by the current deployment |

## References in this repository

- [Backend deployment and GitHub OIDC setup](../README.md#deployment)
- [Production Docker Compose](../docker-compose.prod.yml)
- [Production Nginx configuration](../config/nginx/nginx.prod.conf)
- [Terraform provider configuration](../terraform/main.tf)
- [Terraform EC2 resources](../terraform/ec2.tf)
- [Terraform variables](../terraform/variables.tf)
- [GitHub Actions CI/CD workflow](../.github/workflows/ci.yml)
- [EC2 bootstrap script](../scripts/server-setup.sh)
- [SSL certificate setup script](../scripts/ssl-setup.sh)
- [Database backup script](../scripts/backup-db.sh)
