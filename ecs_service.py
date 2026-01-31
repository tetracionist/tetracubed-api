import boto3 
from loguru import logger

ecs_client = boto3.client('ecs')


def start_ecs_service(cluster_name, service_name):

    ecs_client.update_service(
        cluster=cluster_name,
        service=service_name,
        desiredCount=1,
    )

    logger.info(f"Waiting for ECS service {service_name} in {cluster_name} to become stable...")
    waiter = ecs_client.get_waiter("services_stable")
    waiter.wait(
        cluster=cluster_name,
        services=[service_name],
        WaiterConfig={
            "Delay": 10,   # seconds between checks
            "MaxAttempts": 60  # ~10 minutes total
        }
    )
    logger.info("Getting task data")

    tasks = ecs_client.list_tasks(
        cluster=cluster_name,
        serviceName=service_name,
        desiredStatus="RUNNING"
    )



    eni_id = ecs_client.describe_tasks(cluster=cluster_name, tasks=tasks["taskArns"])["tasks"][0]["attachments"][0]["details"][1]["value"]

    eni = boto3.resource('ec2').NetworkInterface(eni_id)

    logger.info(f"Found Public IP {eni.association_attribute['PublicIp']}")

    return eni.association_attribute['PublicIp']

def stop_ecs_service(cluster_name, service_name):

    ecs_client.update_service(
        cluster=cluster_name,
        service=service_name,
        desiredCount=0,
    )