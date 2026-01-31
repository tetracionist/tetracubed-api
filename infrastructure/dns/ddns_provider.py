"""Pulumi Dynamic Provider for Dynamic DNS updates"""
import pulumi
from pulumi.dynamic import ResourceProvider, CreateResult, UpdateResult, Resource
import requests
import os
from loguru import logger
from typing import Optional


class DynamicDnsProvider(ResourceProvider):
    """
    Dynamic provider that updates Dynamic DNS (No-IP) with the ECS task's public IP.

    - create(): Updates DNS when infrastructure is created
    - update(): Updates DNS when public IP changes
    - delete(): No-op (DNS record stays)
    """

    def _update_dns(self, hostname: str, ip_address: str, username: str, password: str) -> str:
        """Update No-IP Dynamic DNS with new IP address"""
        try:
            logger.info(f"[DDNS] Updating {hostname} to {ip_address}")

            response = requests.get(
                url="https://dynupdate.no-ip.com/nic/update",
                params={
                    "hostname": hostname,
                    "myip": ip_address,
                },
                auth=(username, password),
                timeout=30
            )

            response.raise_for_status()
            result = response.text.strip()

            logger.info(f"[DDNS] No-IP response: {result}")

            # No-IP response codes:
            # good <IP> - Update successful
            # nochg <IP> - No change needed (IP already set)
            # nohost - Hostname doesn't exist
            # badauth - Invalid credentials
            # badagent - Client disabled
            # !donator - Feature not available
            # abuse - Hostname blocked for abuse

            if result.startswith("good") or result.startswith("nochg"):
                logger.info(f"[DDNS] ✓ DNS updated successfully: {result}")
                return result
            else:
                raise Exception(f"DDNS update failed: {result}")

        except requests.exceptions.RequestException as e:
            logger.exception(f"[DDNS] HTTP request failed: {e}")
            raise Exception(f"DDNS HTTP request failed: {str(e)}")
        except Exception as e:
            logger.exception(f"[DDNS] Update failed: {e}")
            raise

    def create(self, props: dict) -> CreateResult:
        """Update DNS when infrastructure is created"""
        hostname = props["hostname"]
        ip_address = props["ip_address"]
        username = props["username"]
        password = props["password"]

        result = self._update_dns(hostname, ip_address, username, password)

        return CreateResult(
            id_=f"{hostname}-{ip_address}",
            outs={
                "hostname": hostname,
                "ip_address": ip_address,
                "result": result,
                "status": "SUCCESS"
            }
        )

    def update(self, id_: str, old_props: dict, new_props: dict) -> UpdateResult:
        """Update DNS when public IP changes"""
        hostname = new_props["hostname"]
        ip_address = new_props["ip_address"]
        username = new_props["username"]
        password = new_props["password"]

        # Only update if IP changed
        if old_props.get("ip_address") != ip_address:
            logger.info(f"[DDNS] IP changed: {old_props.get('ip_address')} -> {ip_address}")
            result = self._update_dns(hostname, ip_address, username, password)
        else:
            logger.info(f"[DDNS] No IP change, skipping update")
            result = "nochg (no update needed)"

        return UpdateResult(
            outs={
                "hostname": hostname,
                "ip_address": ip_address,
                "result": result,
                "status": "SUCCESS"
            }
        )

    def delete(self, id_: str, props: dict) -> None:
        """No-op on delete - leave DNS record in place"""
        logger.info(f"[DDNS] Delete called - DNS record will remain active")
        # Don't remove DNS record when destroying infrastructure
        pass


class DynamicDnsUpdate(Resource):
    """
    Pulumi custom resource for Dynamic DNS updates.

    Usage:
        ddns = DynamicDnsUpdate(
            "ddns-update",
            hostname=pulumi.Config().require("hostname"),
            ip_address=ecs_service_manager.public_ip,
            username=pulumi.Config().require("noip_username"),
            password=pulumi.Config().require_secret("noip_password"),
            opts=pulumi.ResourceOptions(
                depends_on=[ecs_service_manager]
            )
        )

    The DNS will be updated:
    - During 'pulumi up' (after ECS service starts)
    - When the public IP changes
    - NOT removed during 'pulumi destroy' (record stays active)
    """

    hostname: pulumi.Output[str]
    ip_address: pulumi.Output[str]
    result: pulumi.Output[str]
    status: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        hostname: pulumi.Input[str],
        ip_address: pulumi.Input[str],
        username: pulumi.Input[str],
        password: pulumi.Input[str],
        opts: Optional[pulumi.ResourceOptions] = None
    ):
        super().__init__(
            DynamicDnsProvider(),
            name,
            {
                "hostname": hostname,
                "ip_address": ip_address,
                "username": username,
                "password": password,
                "result": None,  # Will be populated by provider
                "status": None,
            },
            opts
        )
