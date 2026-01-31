import pulumi
import json

from dotenv import load_dotenv
load_dotenv()

class Config:
    def __init__(self):
        self.config = pulumi.Config()

        self.s3_bucket_name = self.config.require_secret("s3_bucket_name")
        self.datasync_s3_bucket_access_role = self.config.require_secret("datasync_s3_bucket_access_role")

        # networking
        self.vpc_cidr = self.config.get("vpc_cidr")
        self.public_subnet_cidr = self.config.get("public_subnet_cidr")

        # ecs
        self.ecs_cluster_name = self.config.get("cluster_name")
        self.ecs_task_cpu = self.config.get("cpu")
        self.ecs_task_memory = self.config.get("memory")
        self.ecs_cpu_architecture = self.config.get("cpu_architecture") or "ARM64"
        self.rcon_startup_commands = self.config.get_object("startup_commands")
        self.modrinth_projects = self.config.get_object("modrinth_projects")
        self.ops_list = self.config.require_secret("ops_list").apply(json.loads)
        self.minecraft_version = self.config.get("minecraft_version")
        self.minecraft_motd = self.config.get("minecraft_motd") or "Hello There!"
        self.minecraft_max_players= self.config.get("minecraft_max_players") or 20
        self.noip_username = self.config.require_secret("noip_username")
        self.noip_password = self.config.require_secret("noip_password")
        self.noip_hostname = self.config.require_secret("noip_hostname")

config = Config()
