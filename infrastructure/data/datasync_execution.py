"""DataSync task execution as Pulumi resources"""
import pulumi
import pulumi_command as command


class DataSyncExecutionComponent(pulumi.ComponentResource):
    """Executes DataSync tasks as part of Pulumi deployment"""

    def __init__(self, name: str, task_arn: pulumi.Output[str], opts=None):
        super().__init__("custom:datasync:Execution", name, {}, opts)

        # Execute DataSync task using Command resource
        # This runs as part of pulumi up/destroy
        self.execution = command.local.Command(
            f"{name}-execution",
            create=pulumi.Output.concat(
                "python -c \"",
                "import boto3; ",
                "client = boto3.client('datasync'); ",
                "response = client.start_task_execution(TaskArn='", task_arn, "'); ",
                "print(response['TaskExecutionArn'])",
                "\""
            ),
            opts=pulumi.ResourceOptions(parent=self)
        )

        self.task_execution_arn = self.execution.stdout

        self.register_outputs({
            "task_execution_arn": self.task_execution_arn
        })
