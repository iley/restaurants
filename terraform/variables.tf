variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t4g.micro"
}

variable "key_name" {
  description = "Name of the SSH key pair (must already exist in AWS)"
  type        = string
  default     = "default"
}

variable "data_volume_size" {
  description = "Size of the EBS data volume in GB"
  type        = number
  default     = 20
}
