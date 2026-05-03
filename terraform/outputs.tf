output "public_ip" {
  description = "Elastic IP address"
  value       = aws_eip.restaurants.public_ip
}

output "instance_id" {
  value = aws_instance.restaurants.id
}

output "ssh_command" {
  value = "ssh ubuntu@${aws_eip.restaurants.public_ip}"
}

output "backup_aws_access_key_id" {
  description = "AWS access key ID for the backup IAM user"
  value       = aws_iam_access_key.backup.id
}

output "backup_aws_secret_access_key" {
  description = "AWS secret access key for the backup IAM user"
  value       = aws_iam_access_key.backup.secret
  sensitive   = true
}

# --- Ubuntu migration outputs ---

output "ubuntu_public_ip" {
  description = "Auto-assigned public IP of the new Ubuntu instance (used for testing before EIP swap)"
  value       = aws_instance.restaurants_ubuntu.public_ip
}

output "ubuntu_instance_id" {
  value = aws_instance.restaurants_ubuntu.id
}

output "ubuntu_ssh_command" {
  value = "ssh ubuntu@${aws_instance.restaurants_ubuntu.public_ip}"
}
