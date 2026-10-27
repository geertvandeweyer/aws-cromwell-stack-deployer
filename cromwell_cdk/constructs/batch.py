"""AWS Batch EC2 launch-template configuration."""

from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class BatchLaunchTemplate(Construct):
    """Create a secure EC2 launch template for AWS Batch compute resources.

    The template deliberately does not select an AMI. AWS Batch owns the
    ``ECS_AL2023`` image selection and update lifecycle, as recorded in research
    decision R8. ECS_AL2023 stores both the operating system and Docker data on
    its root volume, so that single volume is enlarged and encrypted here.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        user_data: Optional multipart MIME user data compatible with AWS Batch.
        root_volume_size_gib: Size of the encrypted root/Docker data volume.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        user_data: str | None = None,
        root_volume_size_gib: int = 100,
    ) -> None:
        super().__init__(scope, construct_id)
        mime_user_data = user_data or self._default_user_data()
        self.launch_template = ec2.LaunchTemplate(
            self,
            "Template",
            require_imdsv2=True,
            http_tokens=ec2.LaunchTemplateHttpTokens.REQUIRED,
            http_endpoint=True,
            http_put_response_hop_limit=1,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        root_volume_size_gib,
                        encrypted=True,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=True,
                    ),
                ),
            ],
            user_data=ec2.UserData.custom(mime_user_data),
        )

    @staticmethod
    def _default_user_data() -> str:
        """Return a valid empty multipart archive for Batch user-data merging.

        Returns:
            MIME multipart content containing a harmless cloud-config part.
        """
        return (
            "MIME-Version: 1.0\n"
            'Content-Type: multipart/mixed; boundary="==CROMWELL-BATCH=="\n'
            "\n"
            "--==CROMWELL-BATCH==\n"
            'Content-Type: text/cloud-config; charset="us-ascii"\n'
            "\n"
            "#cloud-config\n"
            "\n"
            "--==CROMWELL-BATCH==--\n"
        )
