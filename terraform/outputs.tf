output "public_ip" {
  description = "Elastic IP address"
  value       = aws_eip.restaurants.public_ip
}

output "instance_id" {
  value = aws_instance.restaurants.id
}

output "ssh_command" {
  value = "ssh ec2-user@${aws_eip.restaurants.public_ip}"
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
