"""Pulumi Dynamic Provider for ECS service lifecycle management"""
import pulumi
from pulumi.dynamic import ResourceProvider, CreateResult, Resource
import boto3
from loguru import logger
from typing import Any, Optional


class EcsServiceManagerProvider(ResourceProvider):
    """
    Dynamic provider that manages ECS service desired count during Pulumi operations.

    - create(): Sets desired count to 1, waits for stability, returns public IP
    - delete(): Sets desired count to 0, waits for tasks to stop
    """

    def _get_public_ip(self, cluster_name: str, service_name: str) -> str:
        """Get the public IP of the running ECS task"""
        try:
            ecs_client = boto3.client('ecs')
            ec2_resource = boto3.resource('ec2')

            logger.info(f"Getting running task for service: {service_name}")

            # List running tasks
            tasks = ecs_client.list_tasks(
                cluster=cluster_name,
                serviceName=service_name,
                desiredStatus="RUNNING"
            )

            if not tasks.get("taskArns"):
                raise Exception(f"No running tasks found for service {service_name}")

            # Describe task to get ENI
            task_details = ecs_client.describe_tasks(
                cluster=cluster_name,
                tasks=tasks["taskArns"]
            )

            if not task_details.get("tasks"):
                raise Exception(f"Could not describe task for service {service_name}")

            # Extract ENI ID from task attachments
            task = task_details["tasks"][0]
            attachments = task.get("attachments", [])

            if not attachments:
                raise Exception("No network attachments found on task")

            eni_id = None
            for detail in attachments[0].get("details", []):
                if detail.get("name") == "networkInterfaceId":
                    eni_id = detail.get("value")
                    break

            if not eni_id:
                raise Exception("Could not find network interface ID in task details")

            logger.info(f"Found ENI: {eni_id}")

            # Get public IP from ENI
            eni = ec2_resource.NetworkInterface(eni_id)

            if not eni.association_attribute or 'PublicIp' not in eni.association_attribute:
                raise Exception(f"No public IP associated with ENI {eni_id}")

            public_ip = eni.association_attribute['PublicIp']
            logger.info(f"Found Public IP: {public_ip}")

            return public_ip

        except Exception as e:
            logger.exception(f"Failed to get public IP: {e}")
            raise

    def create(self, props: dict) -> CreateResult:
        """
        Starts ECS service during 'pulumi up'.
        Sets desired count to 1 and waits for service to be stable.
        """
        cluster_name = props["cluster_name"]
        service_name = props["service_name"]

        try:
            ecs_client = boto3.client('ecs')

            logger.info(f"[CREATE] Starting ECS service: {service_name} in cluster: {cluster_name}")

            # Set desired count to 1
            ecs_client.update_service(
                cluster=cluster_name,
                service=service_name,
                desiredCount=1,
            )

            logger.info(f"[CREATE] Waiting for service to become stable (max 10 minutes)...")

            # Wait for service to be stable
            waiter = ecs_client.get_waiter("services_stable")
            waiter.wait(
                cluster=cluster_name,
                services=[service_name],
                WaiterConfig={
                    "Delay": 10,      # seconds between checks
                    "MaxAttempts": 60  # ~10 minutes total
                }
            )

            logger.info(f"[CREATE] ✓ Service is stable")

            # Get public IP
            public_ip = self._get_public_ip(cluster_name, service_name)

            logger.info(f"[CREATE] ✓ ECS service started with public IP: {public_ip}")

            return CreateResult(
                id_=f"{cluster_name}/{service_name}",
                outs={
                    "cluster_name": cluster_name,
                    "service_name": service_name,
                    "public_ip": public_ip,
                    "desired_count": 1,
                    "status": "RUNNING"
                }
            )

        except Exception as e:
            logger.exception(f"[CREATE] Failed to start ECS service: {e}")
            raise Exception(f"ECS service start failed: {str(e)}")

    def delete(self, id_: str, props: dict) -> None:
        """
        Stops ECS service during 'pulumi destroy'.
        Sets desired count to 0 and waits for tasks to stop.
        """
        cluster_name = props["cluster_name"]
        service_name = props["service_name"]

        try:
            ecs_client = boto3.client('ecs')

            logger.info(f"[DELETE] Stopping ECS service: {service_name} in cluster: {cluster_name}")

            # Set desired count to 0
            ecs_client.update_service(
                cluster=cluster_name,
                service=service_name,
                desiredCount=0,
            )

            logger.info(f"[DELETE] Waiting for tasks to stop (max 10 minutes)...")

            # Wait for service to be stable (all tasks stopped)
            waiter = ecs_client.get_waiter("services_stable")
            waiter.wait(
                cluster=cluster_name,
                services=[service_name],
                WaiterConfig={
                    "Delay": 10,
                    "MaxAttempts": 60
                }
            )

            logger.info(f"[DELETE] ✓ ECS service stopped successfully")

        except Exception as e:
            logger.exception(f"[DELETE] Failed to stop ECS service: {e}")
            raise Exception(f"ECS service stop failed: {str(e)}")


class EcsServiceManager(Resource):
    """
    Pulumi custom resource for ECS service lifecycle management.

    Usage:
        ecs_manager = EcsServiceManager(
            "ecs-service-manager",
            cluster_name=ecs.cluster.name,
            service_name=ecs.service.name,
            opts=pulumi.ResourceOptions(
                depends_on=[s3_to_efs_execution]  # Start after data loaded
            )
        )

    During 'pulumi up':
        - Sets ECS service desired count to 1
        - Waits for service to be stable
        - Returns public IP address

    During 'pulumi destroy':
        - Sets ECS service desired count to 0
        - Waits for tasks to stop
        - Then proceeds with resource deletion
    """

    public_ip: pulumi.Output[str]
    status: pulumi.Output[str]
    desired_count: pulumi.Output[int]

    def __init__(
        self,
        name: str,
        cluster_name: pulumi.Input[str],
        service_name: pulumi.Input[str],
        opts: Optional[pulumi.ResourceOptions] = None
    ):
        super().__init__(
            EcsServiceManagerProvider(),
            name,
            {
                "cluster_name": cluster_name,
                "service_name": service_name,
                "public_ip": None,  # Will be populated by provider
                "status": None,
                "desired_count": None,
            },
            opts
        )
