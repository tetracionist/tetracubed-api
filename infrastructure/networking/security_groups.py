import pulumi
import pulumi_aws as aws
from pulumi import ComponentResource, ResourceOptions

class SecurityGroupsComponent(ComponentResource):
    def __init__(self, name: str, config, vpc_component, opts: ResourceOptions = None):
        super().__init__("custom:networking:SecurityGroups", name, None, opts)

        self.minecraft_sg = aws.ec2.SecurityGroup(
            "securityGroup",
            vpc_id=vpc_component.vpc.id,
            ingress=[
                {
                    "protocol": "tcp",
                    "from_port": 25565,
                    "to_port": 25565,
                    "cidr_blocks": ["0.0.0.0/0"],
                },
                {
                    "protocol": "tcp",
                    "from_port": 8123,
                    "to_port": 8123,
                    "cidr_blocks": ["0.0.0.0/0"],
                },
            ],
            egress=[
                {
                    "protocol": "-1",
                    "from_port": 0,
                    "to_port": 0,
                    "cidr_blocks": ["0.0.0.0/0"],
                }
            ],
            opts=ResourceOptions(parent=self)
        )

        self.efs_sg = aws.ec2.SecurityGroup(
            "securityGroupEFS",
            vpc_id=vpc_component.vpc.id,
            ingress=[
                {
                    "protocol": "tcp",
                    "from_port": 2049,  # Port for NFS
                    "to_port": 2049,
                    "cidr_blocks": ["0.0.0.0/0"],
                }
            ],
            egress=[
                {
                    "protocol": "tcp",
                    "from_port": 2049,  # Port for NFS
                    "to_port": 2049,
                    "cidr_blocks": ["0.0.0.0/0"],
                }
            ],
            opts=ResourceOptions(parent=self)
        )

        self.register_outputs({
            "minecraft_sg_id": self.minecraft_sg.id,
            "efs_sg_id": self.efs_sg.id,
            "efs_sg_arn": self.efs_sg.arn,
        })

