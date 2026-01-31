from fastapi import FastAPI, Depends, HTTPException, status
from loguru import logger
from pathlib import Path
from typing import Annotated
from datetime import datetime, timedelta, timezone
import jwt
from jwt.exceptions import InvalidTokenError

from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
import json
import requests
from discord_notifier import notify_async

from pwdlib import PasswordHash
from pulumi import automation as auto
import time

import os

from dotenv import load_dotenv
load_dotenv()

ACCESS_TOKEN_EXPIRE_MINUTES = 30


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class User(BaseModel):
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool | None = None


class UserInDB(User):
    hashed_password: str

def create_pulumi_program():
    import pulumi
    import os
    from config.config import config
    from infrastructure.networking.vpc import VpcComponent
    from infrastructure.networking.security_groups import SecurityGroupsComponent
    from infrastructure.storage.efs import EfsComponent
    from infrastructure.ecs.ecs import EcsComponent
    from infrastructure.data.datasync import DataSyncComponent
    from infrastructure.data.datasync_provider import DataSyncExecution
    from infrastructure.ecs.ecs_service_provider import EcsServiceManager
    from infrastructure.dns.ddns_provider import DynamicDnsUpdate

    # Create infrastructure components
    vpc = VpcComponent("main", config)
    security_groups = SecurityGroupsComponent("main", config, vpc)
    efs = EfsComponent("main", config, vpc, security_groups)
    ecs = EcsComponent("main", config, vpc, security_groups, efs)
    datasync = DataSyncComponent("main", config, vpc, security_groups, efs)

    # STEP 1: S3 -> EFS - Load world data after infrastructure is created
    s3_to_efs_execution = DataSyncExecution(
        "s3-to-efs-auto",
        task_arn=datasync.s3_to_efs_task.arn,
        task_name="S3 to EFS (load world data)",
        run_on_create=True,   # Execute during 'pulumi up'
        run_on_delete=False,  # Skip during 'pulumi destroy'
        opts=pulumi.ResourceOptions(depends_on=[datasync.s3_to_efs_task])
    )

    # STEP 2: Start ECS service AFTER data is loaded
    ecs_service_manager = EcsServiceManager(
        "ecs-service-manager",
        cluster_name=ecs.cluster.name,
        service_name=ecs.service.name,
        opts=pulumi.ResourceOptions(
            depends_on=[s3_to_efs_execution]  # Wait for data to be loaded
        )
    )

    # STEP 3: Update Dynamic DNS AFTER service starts
    ddns_update = DynamicDnsUpdate(
        "ddns-update",
        hostname=os.getenv("HOSTNAME", "tetranet.ddns.net"),
        ip_address=ecs_service_manager.public_ip,
        username=os.getenv("NOIP_USERNAME"),
        password=os.getenv("NOIP_PASSWORD"),
        opts=pulumi.ResourceOptions(
            depends_on=[ecs_service_manager]  # Wait for service to get public IP
        )
    )

    # STEP 4 (during destroy): EFS -> S3 - Save world data BEFORE destroying infrastructure
    # This runs during 'pulumi destroy' AFTER the service is stopped (delete order is reverse)
    efs_to_s3_execution = DataSyncExecution(
        "efs-to-s3-auto",
        task_arn=datasync.efs_to_s3_task.arn,
        task_name="EFS to S3 (save world data)",
        run_on_create=False,  # Skip during 'pulumi up'
        run_on_delete=True,   # Execute during 'pulumi destroy'
        opts=pulumi.ResourceOptions(depends_on=[datasync.efs_to_s3_task])
    )

    # Export outputs
    pulumi.export("efs_to_s3_task_arn", datasync.efs_to_s3_task.arn)
    pulumi.export("s3_to_efs_task_arn", datasync.s3_to_efs_task.arn)
    pulumi.export("ecs_cluster_name", ecs.cluster.name)
    pulumi.export("ecs_service_name", ecs.service.name)
    pulumi.export("public_ip", ecs_service_manager.public_ip)
    pulumi.export("hostname", ddns_update.hostname)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI()


project_name = "tetracubed-api"
stack_name = os.getenv("PULUMI_STACK_NAME", "dev")
work_dir = os.path.dirname(os.path.abspath(__file__))

def get_user(username: str):
    db = json.loads(os.getenv("USERS_DB"))
    if username in db:
        user_dict = db[username]
        return UserInDB(**user_dict)

def authenticate_user(username, password):
    users_db = json.loads(os.getenv("USERS_DB"))



    if username not in users_db.keys():
        return False

    password_hash = PasswordHash.recommended()

    if password_hash.verify(password, users_db[username]["hashed_password"]) is False:
        return False
    
    
    return UserInDB(**users_db[username])
    



def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, os.getenv("JWT_SECRET_KEY"), algorithm="HS256")
    return encoded_jwt


@app.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, os.getenv("JWT_SECRET_KEY"), algorithms=["HS256"])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except InvalidTokenError:
        raise credentials_exception
    user = get_user(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user



@app.post("/tetracubed/start")
async def tetracubed_start(current_user: str = Depends(get_current_user)):
    """
    Starts the Tetracubed Server
    """

    await notify_async("Provisioning Tetracubed Server...")

    try:
        # Create workspace using local program (__main__.py)
        stack = auto.create_or_select_stack(stack_name=stack_name, project_name="tetracubed-api", program=create_pulumi_program, work_dir=work_dir)
        stack.add_environments("tetracubed-api/dev")

        logger.info(f"Stack created/selected: {stack.name}")

        # REQUIRE Pulumi ESC - fail fast if not configured
        environments = stack.list_environments()

        if not environments or len(environments) == 0:
            error_msg = (
                f"Pulumi ESC environment is REQUIRED but not configured for stack '{stack_name}'. "
                f"Please configure ESC using: pulumi config env add <environment-name> "
                f"See PULUMI_ESC_SETUP.md for instructions."
            )
            logger.error(error_msg)
            await notify_async(f"❌ Provisioning failed: ESC not configured")
            raise HTTPException(
                status_code=500,
                detail=error_msg
            )

        logger.info(f"✓ Using Pulumi ESC environment(s): {environments}")

        # OPTIONAL: Override ESC config with environment variables
        # ESC is REQUIRED as the base config source (validated above)
        # Environment variables here allow runtime overrides for testing/debugging
        # This is optional - remove this section if you want pure ESC with no overrides
        config_values = {}

        # AWS region
        if "AWS_DEFAULT_REGION" in os.environ:
            stack.set_config("aws:region", auto.ConfigValue(os.environ["AWS_DEFAULT_REGION"]))

        # Required secrets (must be set either in Pulumi config or environment)
        if "S3_BUCKET_NAME" in os.environ:
            config_values["s3_bucket_name"] = auto.ConfigValue(os.environ["S3_BUCKET_NAME"], secret=True)

        if "DATASYNC_S3_BUCKET_ACCESS_ROLE" in os.environ:
            config_values["datasync_s3_bucket_access_role"] = auto.ConfigValue(os.environ["DATASYNC_S3_BUCKET_ACCESS_ROLE"], secret=True)

        if "OPS_LIST" in os.environ:
            config_values["ops_list"] = auto.ConfigValue(os.environ["OPS_LIST"], secret=True)

        # Optional overrides for non-secret values
        if "VPC_CIDR" in os.environ:
            config_values["vpc_cidr"] = auto.ConfigValue(os.environ["VPC_CIDR"])

        if "ECS_CLUSTER_NAME" in os.environ:
            config_values["cluster_name"] = auto.ConfigValue(os.environ["ECS_CLUSTER_NAME"])

        if "ECS_TASK_CPU" in os.environ:
            config_values["cpu"] = auto.ConfigValue(os.environ["ECS_TASK_CPU"])

        if "ECS_TASK_MEMORY" in os.environ:
            config_values["memory"] = auto.ConfigValue(os.environ["ECS_TASK_MEMORY"])

        if "ECS_CPU_ARCHITECTURE" in os.environ:
            config_values["cpu_architecture"] = auto.ConfigValue(os.environ["ECS_CPU_ARCHITECTURE"])

        if "MINECRAFT_VERSION" in os.environ:
            config_values["minecraft_version"] = auto.ConfigValue(os.environ["MINECRAFT_VERSION"])

        if "MINECRAFT_MAX_PLAYERS" in os.environ:
            config_values["minecraft_max_players"] = auto.ConfigValue(os.environ["MINECRAFT_MAX_PLAYERS"])

        if "RCON_STARTUP_COMMANDS" in os.environ:
            config_values["startup_commands"] = auto.ConfigValue(os.environ["RCON_STARTUP_COMMANDS"])

        if "MODRINTH_PROJECTS" in os.environ:
            config_values["modrinth_projects"] = auto.ConfigValue(os.environ["MODRINTH_PROJECTS"])

        # Only set config values if there are any overrides
        if config_values:
            stack.set_all_config(config_values)
            logger.info(f"Applied {len(config_values)} config overrides from environment variables")

        logger.info("Running stack.up()...")
        up_res = stack.up(on_output=print)

        logger.info(f"Stack update complete. Summary: {up_res.summary}")

        outputs = stack.outputs()
        logger.info(f"Stack outputs: {outputs}")

        # Everything executed automatically during pulumi up:
        # 1. ✓ World data loaded from S3 to EFS
        # 2. ✓ ECS service started
        # 3. ✓ DNS updated
        public_ip = outputs["public_ip"].value
        hostname = outputs["hostname"].value

        logger.info(f"✓ World data loaded from S3 to EFS")
        logger.info(f"✓ ECS service started")
        logger.info(f"✓ Public IP: {public_ip}")
        logger.info(f"✓ DNS updated: {hostname} -> {public_ip}")

        await notify_async(f"Tetracubed Has Been Successfully Provisioned!\n{hostname} -> {public_ip}")

        return {"message": "Tetracubed server started successfully", "public_ip": public_ip}

    except Exception as e:
        logger.exception(f"Failed to provision: {e}")  # Changed to .exception() for full traceback
        await notify_async(f"Failed To Provision Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    



@app.post("/tetracubed/stop")
async def tetracubed_stop(current_user: str = Depends(get_current_user)):
    """
    Stops the Tetracubed Server
    """

    await notify_async("Deprovisioning Tetracubed Server...")
    try:
        # Select existing stack using local program
        stack = auto.create_or_select_stack(stack_name=stack_name, project_name="tetracubed-api", program=create_pulumi_program, work_dir=work_dir)
        stack.add_environments("tetracubed-api/dev")

        await notify_async("Destroying Infrastructure (ECS will stop, then data will be saved)...")

        # During pulumi destroy:
        # 1. ECS service stops automatically (desired count -> 0)
        # 2. DataSync EFS->S3 saves world data
        # 3. Infrastructure is destroyed
        destroy_res = stack.destroy(on_output=print)

        logger.info(f"Stack destroyed. Summary: {destroy_res.summary}")

        await notify_async("Tetracubed Has Been Successfully Deprovisioned!")

        return {"message": "Tetracubed server stopped successfully"}

    except Exception as e:
        logger.exception(f"Failed to deprovision: {e}")  # Changed to .exception() for full traceback
        await notify_async(f"Failed To Deprovision Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tetracubed/resources")
def show_resources(current_user: str = Depends(get_current_user)):
    """Shows All Tetracubed Resources"""
    try:
        # Select stack using local program
        stack = auto.create_or_select_stack(stack_name=stack_name, project_name="tetracubed-api", program=create_pulumi_program, work_dir=work_dir)
        stack.add_environments("tetracubed-api/dev")

        outputs = stack.outputs()

        return {
            "stack_name": stack.name,
            "outputs": {k: v.value for k, v in outputs.items()}
        }
    except auto.StackNotFoundError:
        return {"message": "No resources found. Stack does not exist."}
    except Exception as e:
        logger.error(f"Failed to get resources: {e}")
        raise HTTPException(status_code=500, detail=str(e))
