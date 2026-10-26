# Research: Cromwell AWS CDK Migration

## R8: AWS Batch compute AMI family

**Status**: Decision for T022a (2026-10-26)

**Decision**: Use the AWS Batch-managed Amazon ECS-optimized Amazon Linux 2023 image family, explicitly selecting the Batch image type `ECS_AL2023` in each EC2 managed compute environment. Do not pin a customer AMI ID or embed an AMI ID in the launch template. The launch template in T022 may customize block-device mappings and user data, while leaving AMI selection to AWS Batch. ECS AL2023 uses a single root volume for the OS and Docker images/metadata, so T022 must encrypt and size this shared volume rather than add a separate Docker data disk.

**Rationale**:

- AWS Batch documentation recommends the default Amazon ECS-optimized AMI for compute resources and identifies `ECS_AL2023` as an available image type.
- AWS changed the default for new ECS compute environments to Amazon Linux 2023 on 2026-01-12 and blocks new Batch-provided ECS Amazon Linux 2 environments after 2026-06-30. The project is being implemented after that cutoff, so AL2 is not a valid new-deployment target.
- Batch-managed AMIs provide AWS visibility for update availability and allow AMI refresh through the supported compute-environment infrastructure update process. A fixed AMI ID would transfer patching, image lifecycle, and update-status responsibilities to this project.
- The project requires host-level additions, but those are delivered as launch-template user data and scripts rather than by baking a custom AMI; therefore a custom AMI is not currently justified.
- The configured Batch instance types are `m5.large` and `m5.xlarge`, both x86_64 families compatible with the standard ECS AL2023 image. If future configuration enables Graviton instance families, the project must explicitly add and test the corresponding ARM image type rather than assuming the x86 image applies.

**Update policy**: Keep AWS-managed image updates eligible by using the Batch-supported `ECS_AL2023` image type and avoid an AMI ID override. For compute environments, set `updateToLatestImageVersion` when supported by the chosen allocation strategy and CDK construct/API. Batch infrastructure updates replace compute instances and can interrupt jobs; deployment documentation and operational policy must account for that. Exact safe update settings should be checked against T023/T024 allocation strategies before wiring.

**Launch-template constraints for T022**:

- Do not set a custom `ImageId` in the launch template; it takes precedence over the managed selection and would defeat this decision.
- Use Batch-compatible multipart MIME user data so custom cloud-init content merges with Batch-managed configuration.
- Do not set or overwrite Batch-reserved ECS values, including `ECS_CLUSTER` and `ECS_INSTANCE_ATTRIBUTES`.
- ECS AL2023 stores both OS and Docker data on its single root EBS volume. Encrypt
	and size the root mapping; do not assume an AL2-style separate Docker disk or
	add an unused data volume. T022 verifies the documented AL2023 device mapping.
- Let AWS Batch manage Spot market configuration; do not move Spot settings into the launch template.

**Alternatives considered**:

1. **Pin a specific AWS-published AL2023 AMI ID** — rejected because AMI IDs vary by region and become stale; it removes Batch-managed update status and shifts patch/update management into this project.
2. **Use an ECS AL2 image** — rejected because AWS ended support on 2026-06-30 and disallows creation of new Batch-managed AL2 ECS compute environments after that date.
3. **Build and pin a project-owned custom AMI** — rejected for the current requirements because user-data bootstrap can provide the needed host additions, while a custom image introduces a separate image build, security patch, provenance, and rollout lifecycle.
4. **Rely implicitly on the Batch default without declaring an image type** — rejected in favor of an explicit `ECS_AL2023` contract so the supported family is reviewable and tested.

**References**:

- AWS Batch compute resource AMIs: https://docs.aws.amazon.com/batch/latest/userguide/compute_resource_AMIs.html
- AWS Batch AMI selection order: https://docs.aws.amazon.com/batch/latest/userguide/ami-selection-order.html
- AWS Batch AMI lifecycle and update behavior: https://docs.aws.amazon.com/batch/latest/userguide/managing-ami-versions.html
- AWS Batch launch templates, multipart user data, and reserved ECS configuration: https://docs.aws.amazon.com/batch/latest/userguide/launch-templates.html
- AWS Batch Amazon Linux 2 ECS AMI deprecation: https://docs.aws.amazon.com/batch/latest/userguide/ecs-al2-ami-deprecation.html
- AWS Batch AMI specification: https://docs.aws.amazon.com/batch/latest/userguide/batch-ami-spec.html
- Amazon ECS-optimized AL2023 storage configuration: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-optimized_AMI.html
