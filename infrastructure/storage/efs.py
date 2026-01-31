import pulumi
import pulumi_aws as aws
from pulumi import ComponentResource, ResourceOptions


class EfsComponent(ComponentResource):
    def __init__(self, name: str, config, vpc_component, security_groups, opts: ResourceOptions = None):
        super().__init__("custom:storage:EFS", name, None, opts)

        self.efs = aws.efs.FileSystem(
            "minecraftEFS",
            lifecycle_policies=[
                {
                    "transitionToIa": "AFTER_30_DAYS",
                }
            ],
            # No creation_token - AWS auto-generates a stable one (prevents rotation on updates)
            tags={"Name": "minecraft-efs"},
            opts=ResourceOptions(parent=self)  # No protection - EFS is ephemeral storage
        )

        self.efs_mount_target = aws.efs.MountTarget(
            "efsMountTarget",
            file_system_id=self.efs.id,
            subnet_id=vpc_component.public_subnet.id,
            security_groups=[security_groups.efs_sg.id],
            opts=ResourceOptions(parent=self)
        )

        self.register_outputs({
            "efs_id": self.efs.id,
            "efs_arn": self.efs.arn,
            "efs_mount_target_id": self.efs_mount_target.id,
        })
