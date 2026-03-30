terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_ami" "al2023_arm" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_security_group" "restaurants" {
  name        = "restaurants-sg"
  description = "Security group for restaurants app"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "restaurants-sg"
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = "${var.aws_region}a"
  size              = var.data_volume_size
  type              = "gp3"

  tags = {
    Name = "restaurants-data"
  }
}

resource "aws_instance" "restaurants" {
  ami                    = data.aws_ami.al2023_arm.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.restaurants.id]
  availability_zone      = "${var.aws_region}a"

  root_block_device {
    volume_size = 10
    volume_type = "gp3"
  }

  tags = {
    Name = "restaurants"
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.restaurants.id
}

resource "aws_eip" "restaurants" {
  instance = aws_instance.restaurants.id
  domain   = "vpc"

  tags = {
    Name = "restaurants-eip"
  }
}
