import pulumi
import pulumi_aws as aws
from pulumi import ComponentResource, ResourceOptions

class VpcComponent(ComponentResource):
    def __init__(self, name: str, config, opts: ResourceOptions = None):
        super().__init__("custom:networking:VPC", name, None, opts)

        self.vpc = aws.ec2.Vpc(
            "vpc",
            cidr_block=config.vpc_cidr,
            enable_dns_hostnames=True,
            enable_dns_support=True,
            opts=ResourceOptions(parent=self),
        )

        self.public_subnet = aws.ec2.Subnet(
            "publicSubnet",
            vpc_id=self.vpc.id,
            cidr_block=config.vpc_cidr,
            map_public_ip_on_launch=True,
            opts=ResourceOptions(parent=self),
        )

        # Create an Internet Gateway
        self.igw = aws.ec2.InternetGateway(
            "igw",
            vpc_id=self.vpc.id,
            opts=ResourceOptions(parent=self),
        )

        # Create a route table
        self.route_table = aws.ec2.RouteTable(
            "routeTable",
            vpc_id=self.vpc.id,
            routes=[
                {
                    "cidr_block": "0.0.0.0/0",
                    "gateway_id": self.igw.id,
                }
            ],
            opts=ResourceOptions(parent=self),
        )

        # Associate the route table with the public subnet
        self.route_table_association = aws.ec2.RouteTableAssociation(
            "routeTableAssociation",
            subnet_id=self.public_subnet.id,
            route_table_id=self.route_table.id,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({
            "vpc_id": self.vpc.id,
            "public_subnet_id": self.public_subnet.id,
            "public_subnet_arn": self.public_subnet.arn,
        })
