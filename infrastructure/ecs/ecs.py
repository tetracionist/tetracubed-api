import pulumi_aws as aws
from pulumi import ComponentResource, ResourceOptions
import pulumi
import json


class EcsComponent(ComponentResource):
    def __init__(
        self,
        name: str,
        config,
        vpc_component,
        security_groups,
        efs_component,
        opts: ResourceOptions = None,
    ):
        super().__init__("custom:compute:ECS", name, None, opts)

        self.current_account = aws.get_caller_identity().account_id

        self.cluster = aws.ecs.Cluster(
            config.ecs_cluster_name, opts=ResourceOptions(parent=self)
        )

        self.ecs_task_execution_role = aws.iam.Role(
            "ecsTaskExecutionRole",
            assume_role_policy="""{
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "sts:AssumeRole",
                        "Principal": {
                            "Service": "ecs-tasks.amazonaws.com"
                        },
                        "Effect": "Allow",
                        "Sid": ""
                    }
                ]
            }""",
            opts=ResourceOptions(parent=self),
        )

        self.ecs_task_execution_role_policy = aws.iam.RolePolicyAttachment(
            "ecsTaskExecutionRolePolicy",
            role=self.ecs_task_execution_role.name,
            policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
            opts=ResourceOptions(parent=self),
        )

        # Create an IAM Role
        self.ecs_task_role = aws.iam.Role(
            "ecsTaskRole",
            assume_role_policy=f"""
        {{
            "Version": "2012-10-17",
            "Statement": [
                {{
                    "Effect": "Allow",
                    "Principal": {{
                        "Service": [
                            "ecs-tasks.amazonaws.com"
                        ]
                    }},
                    "Action": "sts:AssumeRole",
                    "Condition": {{
                        "ArnLike": {{
                        "aws:SourceArn": "arn:aws:ecs:eu-west-2:{self.current_account}:*"
                        }},
                        "StringEquals": {{
                            "aws:SourceAccount": "{self.current_account}"
                        }}
                    }}
                }}
            ]
        }}
        """,
            opts=ResourceOptions(parent=self),
        )

        container_def_json = pulumi.Output.all(config.ops_list, config.rcon_startup_commands, config.modrinth_projects).apply(
            lambda args: json.dumps([
                {
                    "name": "minecraft",
                    "image": "itzg/minecraft-server",
                    "cpu": int(config.ecs_task_cpu),
                    "memory": int(config.ecs_task_memory),
                    "essential": True,
                    "environment": [
                        {"name": "EULA", "value": "TRUE"},
                        {"name": "MOTD", "value": "Hello There!"},
                        {"name": "TYPE", "value": "FABRIC"},
                        {"name": "VERSION", "value": str(config.minecraft_version)},
                        {"name": "MAX_PLAYERS", "value": str(config.minecraft_max_players)},
                        {"name": "MEMORY", "value": f"{config.ecs_task_memory}M"},
                        {"name": "OPS", "value": ",".join(args[0])},
                        {"name": "DIFFICULTY", "value": "hard"},
                        {"name": "ENABLE_AUTOPAUSE", "value": "FALSE"},
                        {"name": "RCON_CMDS_STARTUP", "value": "\n".join(args[1])},
                        {"name": "MODRINTH_PROJECTS", "value": "\n".join(args[2])},
                    ],
                    "portMappings": [
                        {"containerPort": 25565, "hostPort": 25565, "protocol": "tcp"}
                    ],
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": "/ecs/minecraft",
                            "awslogs-region": "eu-west-2",
                            "awslogs-stream-prefix": "ecs",
                            "awslogs-create-group": "true",
                        },
                    },
                    "mountPoints": [
                        {"containerPath": "/data", "sourceVolume": "minecraft_data"}
                    ],
                }
            ])
        )



        # Create ECS Task Definition
        task_definition = aws.ecs.TaskDefinition(
            "minecraft-task",
            family="minecraft",
            container_definitions=container_def_json,  # NOTE: Output, no json.dumps here
            runtime_platform={
                "operating_system_family": "LINUX",
                "cpu_architecture": config.ecs_cpu_architecture,
            },
            requires_compatibilities=["FARGATE"],
            network_mode="awsvpc",
            cpu=str(config.ecs_task_cpu),
            memory=str(config.ecs_task_memory),
            task_role_arn=self.ecs_task_role.arn,
            execution_role_arn=self.ecs_task_execution_role.arn,
            volumes=[{
                "name": "minecraft_data",
                "efsVolumeConfiguration": {"fileSystemId": efs_component.efs.id},
            }],
            opts=ResourceOptions(
                depends_on=[efs_component.efs_mount_target],
                parent=self
            ),
        )


        self.service = aws.ecs.Service(
            "minecraft-service",
            cluster=self.cluster.arn,
            task_definition=task_definition.arn,
            desired_count=0,
            launch_type="FARGATE",
            network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
                subnets=[vpc_component.public_subnet.id],
                security_groups=[security_groups.minecraft_sg.id],
                assign_public_ip=True,
            ),
            opts=ResourceOptions(parent=self),
        )
