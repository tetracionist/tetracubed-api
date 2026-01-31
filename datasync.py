from loguru import logger
import boto3
from botocore.waiter import WaiterModel, create_waiter_with_client

datasync_client = boto3.client('datasync')

def create_waiter_config():
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


def execute_datasync_task(task_arn):
    response = datasync_client.start_task_execution(
        TaskArn=task_arn
    )

    logger.info(f"Created Task DataSync Task: {response["TaskExecutionArn"]}")

    waiter_config = create_waiter_config()

    model = WaiterModel(waiter_config)
    waiter = create_waiter_with_client("TaskExecutionComplete", model, datasync_client)

    waiter.wait(TaskExecutionArn=response["TaskExecutionArn"])

    logger.info(f"Completed Task DataSync Task: {response["TaskExecutionArn"]}")