import requests
import os

def update_dynamic_dns(ecs_ip):
    response = requests.get(
        url="https://dynupdate.no-ip.com/nic/update",
        params = {
            "hostname": os.getenv("HOSTNAME"),
            "myip": ecs_ip,
        },
        auth=(os.getenv("NOIP_USERNAME"), os.getenv("NOIP_PASSWORD"))
    )

    print(response.text)