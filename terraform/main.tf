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

# Canonical's official AWS account; Ubuntu 24.04 LTS (Noble) ARM64.
data "aws_ami" "ubuntu_2404_arm" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
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

  lifecycle {
    ignore_changes = [ami]
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.restaurants.id
}

resource "aws_eip" "restaurants" {
  instance = aws_instance.restaurants_ubuntu.id
  domain   = "vpc"

  tags = {
    Name = "restaurants-eip"
  }
}

# --- Ubuntu migration sibling resources ---
# Temporary infrastructure for the AL2023 -> Ubuntu migration. After cutover
# (EIP re-associated to restaurants_ubuntu, old host destroyed), rename these
# to the canonical names and delete the AL2023 resources above.

resource "aws_ebs_volume" "data_ubuntu" {
  availability_zone = "${var.aws_region}a"
  size              = var.data_volume_size
  type              = "gp3"

  tags = {
    Name = "restaurants-data-ubuntu"
  }
}

resource "aws_instance" "restaurants_ubuntu" {
  ami                    = data.aws_ami.ubuntu_2404_arm.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.restaurants.id]
  availability_zone      = "${var.aws_region}a"

  root_block_device {
    volume_size = 10
    volume_type = "gp3"
  }

  tags = {
    Name = "restaurants-ubuntu"
  }

  lifecycle {
    ignore_changes = [ami]
  }
}

resource "aws_volume_attachment" "data_ubuntu" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.data_ubuntu.id
  instance_id = aws_instance.restaurants_ubuntu.id
}

# --- Backups ---

resource "aws_s3_bucket" "backups" {
  bucket = var.backup_bucket_name

  tags = {
    Name = "restaurants-backups"
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket = aws_s3_bucket.backups.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_user" "backup" {
  name = "restaurants-backup"
}

resource "aws_iam_access_key" "backup" {
  user = aws_iam_user.backup.name
}

resource "aws_iam_user_policy" "backup" {
  name = "restaurants-backup-s3"
  user = aws_iam_user.backup.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.backups.arn,
          "${aws_s3_bucket.backups.arn}/*",
        ]
      }
    ]
  })
}
