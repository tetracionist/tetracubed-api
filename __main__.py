"""
Pulumi infrastructure program for Tetracubed.
This file allows the Automation API to use local program pattern.
"""
import pulumi
from config.config import config
from infrastructure.networking.vpc import VpcComponent
from infrastructure.networking.security_groups import SecurityGroupsComponent
from infrastructure.storage.efs import EfsComponent
from infrastructure.ecs.ecs import EcsComponent
from infrastructure.data.datasync import DataSyncComponent

# Create infrastructure components
vpc = VpcComponent("main", config)
security_groups = SecurityGroupsComponent("main", config, vpc)
efs = EfsComponent("main", config, vpc, security_groups)
ecs = EcsComponent("main", config, vpc, security_groups, efs)
datasync = DataSyncComponent("main", config, vpc, security_groups, efs)

# Export outputs
pulumi.export("efs_to_s3_task_arn", datasync.efs_to_s3_task.arn)
pulumi.export("s3_to_efs_task_arn", datasync.s3_to_efs_task.arn)
pulumi.export("ecs_cluster_name", ecs.cluster.name)
pulumi.export("ecs_service_name", ecs.service.name)
