"""Pulumi Dynamic Provider for DataSync task execution"""
import pulumi
from pulumi.dynamic import ResourceProvider, CreateResult, Resource
import boto3
from botocore.waiter import WaiterModel, create_waiter_with_client
from loguru import logger
from typing import Any, Optional


def create_waiter_config():
    """Creates custom waiter config for DataSync task completion"""
    return {
        "version": 2,
        "waiters": {
            "TaskExecutionComplete": {
                "delay": 30,
                "maxAttempts": 60,  # approx. 30 min timeout
                "operation": "DescribeTaskExecution",
                "acceptors": [
                    {
                        "matcher": "path",
                        "argument": "Status",
                        "expected": "SUCCESS",
                        "state": "success",
                    },
                    {
                        "matcher": "path",
                        "argument": "Status",
                        "expected": "ERROR",
                        "state": "failure",
                    },
                    {
                        "matcher": "path",
                        "argument": "Status",
                        "expected": "CANCELED",
                        "state": "failure",
                    },
                ],
            }
        },
    }


class DataSyncExecutionProvider(ResourceProvider):
    """
    Dynamic provider that executes DataSync tasks during Pulumi operations.
    Inherits AWS credentials from Pulumi's AWS provider (including OIDC).

    - create(): Runs during 'pulumi up' (e.g., S3 -> EFS to load data)
    - delete(): Runs during 'pulumi destroy' (e.g., EFS -> S3 to save data)
    """

    def _execute_task(self, task_arn: str, task_name: str, operation: str) -> str:
        """Common logic to execute and wait for DataSync task"""
        try:
            # Create boto3 client - inherits credentials from environment
            # If Pulumi is using OIDC, boto3 will use the same credentials
            datasync_client = boto3.client('datasync')

            logger.info(f"[{operation}] Starting DataSync task: {task_name}")

            # Start task execution
            response = datasync_client.start_task_execution(TaskArn=task_arn)
            task_execution_arn = response["TaskExecutionArn"]

            logger.info(f"[{operation}] Task started: {task_execution_arn}")

            # Wait for completion using custom waiter
            waiter_config = create_waiter_config()
            model = WaiterModel(waiter_config)
            waiter = create_waiter_with_client(
                "TaskExecutionComplete", model, datasync_client
            )

            logger.info(f"[{operation}] Waiting for completion (max 30 minutes)...")
            waiter.wait(TaskExecutionArn=task_execution_arn)

            logger.info(f"[{operation}] ✓ Task completed successfully: {task_execution_arn}")

            return task_execution_arn

        except Exception as e:
            logger.exception(f"[{operation}] DataSync task failed: {e}")
            raise Exception(f"DataSync {operation} failed for {task_name}: {str(e)}")

    def create(self, props: dict) -> CreateResult:
        """
        Executes DataSync task during 'pulumi up'.
        Use this for S3 -> EFS (load data after infrastructure is created).
        """
        task_arn = props["task_arn"]
        task_name = props.get("task_name", "datasync-task")
        run_on_create = props.get("run_on_create", True)

        if not run_on_create:
            logger.info(f"Skipping execution on create for: {task_name}")
            return CreateResult(
                id_=f"{task_name}-skipped",
                outs={"task_arn": task_arn, "status": "SKIPPED"}
            )

        task_execution_arn = self._execute_task(task_arn, task_name, "CREATE")

        return CreateResult(
            id_=task_execution_arn,
            outs={
                "task_execution_arn": task_execution_arn,
                "task_arn": task_arn,
                "status": "SUCCESS"
            }
        )

    def delete(self, id_: str, props: dict) -> None:
        """
        Executes DataSync task during 'pulumi destroy'.
        Use this for EFS -> S3 (save data before infrastructure is destroyed).
        """
        task_arn = props["task_arn"]
        task_name = props.get("task_name", "datasync-task")
        run_on_delete = props.get("run_on_delete", False)

        if not run_on_delete:
            logger.info(f"Skipping execution on delete for: {task_name}")
            return

        self._execute_task(task_arn, task_name, "DELETE")


class DataSyncExecution(Resource):
    """
    Pulumi custom resource for DataSync task execution.

    Usage:
        s3_to_efs_execution = DataSyncExecution(
            "s3-to-efs-execution",
            task_arn=datasync.s3_to_efs_task.arn,
            task_name="s3-to-efs",
            opts=pulumi.ResourceOptions(depends_on=[datasync])
        )
    """

    task_execution_arn: pulumi.Output[str]
    status: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        task_arn: pulumi.Input[str],
        task_name: Optional[str] = None,
        opts: Optional[pulumi.ResourceOptions] = None
    ):
        full_args = {
            "task_arn": task_arn,
            "task_name": task_name or name,
        }

        super().__init__(
            DataSyncExecutionProvider(),
            name,
            full_args,
            opts
        )
