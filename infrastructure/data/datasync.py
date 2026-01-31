import pulumi_aws as aws
from pulumi import ComponentResource, ResourceOptions
import pulumi


class DataSyncComponent(ComponentResource):
    def __init__(
        self,
        name: str,
        config,
        vpc_component,
        security_groups,
        efs_component,
        opts: ResourceOptions = None,
    ):
        super().__init__("custom:data:DataSync", name, None, opts)

        # Get current account ID
        current_account = aws.get_caller_identity()
        self.account_id = current_account.account_id
        self.region = aws.get_region().region

        # S3 Location
        self.s3_location = aws.datasync.S3Location(
            f"{name}-s3-location",
            s3_bucket_arn=config.s3_bucket_name.apply(
                lambda bucket_name: f"arn:aws:s3:::{bucket_name}"
            ),
            s3_config={
                "bucket_access_role_arn": pulumi.Output.all(
                    role_template=config.datasync_s3_bucket_access_role,
                    account_id=self.account_id
                ).apply(
                    lambda args: args["role_template"].replace("{account_id}", args["account_id"])
                ),
            },
            s3_storage_class="STANDARD",
            subdirectory="/",
            opts=ResourceOptions(parent=self),
        )

        # EFS Location
        self.efs_location = aws.datasync.EfsLocation(
            f"{name}-efs-location",
            ec2_config={
                "security_group_arns": [security_groups.efs_sg.arn],
                "subnet_arn": vpc_component.public_subnet.arn,
            },
            efs_file_system_arn=efs_component.efs.arn,
            in_transit_encryption="NONE",
            opts=ResourceOptions(
                parent=self, depends_on=[efs_component.efs_mount_target]
            ),
        )

        # EFS to S3 Task (Backup)
        self.efs_to_s3_task = aws.datasync.Task(
            f"{name}-efs-to-s3",
            cloudwatch_log_group_arn=pulumi.Output.all(
                self.region, self.account_id
            ).apply(
                lambda args: f"arn:aws:logs:{args[0]}:{args[1]}:log-group:/aws/datasync"
            ),
            destination_location_arn=self.s3_location.arn,
            includes={
                "filter_type": "SIMPLE_PATTERN",
                "value": "/world|/config",
            },
            name="EFS - S3",
            options={
                "atime": "BEST_EFFORT",
                "gid": "INT_VALUE",
                "log_level": "BASIC",
                "mtime": "PRESERVE",
                "object_tags": "PRESERVE",
                "overwrite_mode": "ALWAYS",
                "posix_permissions": "PRESERVE",
                "preserve_deleted_files": "PRESERVE",
                "preserve_devices": "NONE",
                "security_descriptor_copy_flags": "NONE",
                "task_queueing": "ENABLED",
                "transfer_mode": "CHANGED",
                "uid": "INT_VALUE",
                "verify_mode": "ONLY_FILES_TRANSFERRED",
            },
            source_location_arn=self.efs_location.arn,
            opts=ResourceOptions(parent=self),
        )

        # S3 to EFS Task (Restore)
        self.s3_to_efs_task = aws.datasync.Task(
            f"{name}-s3-to-efs",
            cloudwatch_log_group_arn=pulumi.Output.all(
                self.region, self.account_id
            ).apply(
                lambda args: f"arn:aws:logs:{args[0]}:{args[1]}:log-group:/aws/datasync"
            ),
            destination_location_arn=self.efs_location.arn,
            includes={
                "filter_type": "SIMPLE_PATTERN",
                "value": "/world|/config",
            },
            name="S3 - EFS",
            options={
                "atime": "BEST_EFFORT",
                "gid": "INT_VALUE",
                "log_level": "BASIC",
                "mtime": "PRESERVE",
                "object_tags": "PRESERVE",
                "overwrite_mode": "ALWAYS",
                "posix_permissions": "PRESERVE",
                "preserve_deleted_files": "PRESERVE",
                "preserve_devices": "NONE",
                "security_descriptor_copy_flags": "NONE",
                "task_queueing": "ENABLED",
                "transfer_mode": "CHANGED",
                "uid": "INT_VALUE",
                "verify_mode": "ONLY_FILES_TRANSFERRED",
            },
            source_location_arn=self.s3_location.arn,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs(
            {
                "efs_to_s3_task_arn": self.efs_to_s3_task.arn,
                "s3_to_efs_task_arn": self.s3_to_efs_task.arn,
            }
        )
