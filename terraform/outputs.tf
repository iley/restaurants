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
