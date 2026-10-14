variable "aws_region" {
  description = "Region containing the existing backend resources"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile used by Terraform"
  type        = string
  default     = "arrotech"
}

variable "instance_id" {
  description = "ID of the active encrypted backend EC2 instance"
  type        = string
}

variable "rollback_instance_id" {
  description = "ID of the stopped original EC2 instance retained for rollback"
  type        = string
}

variable "vpc_id" {
  description = "ID of the existing VPC containing the backend"
  type        = string
}

variable "subnet_id" {
  description = "ID of the subnet containing the backend"
  type        = string
}

variable "security_group_id" {
  description = "ID of the existing backend security group to import"
  type        = string
}

variable "elastic_ip_allocation_id" {
  description = "Allocation ID of the Elastic IP associated with the backend"
  type        = string
}

variable "backend_ami_id" {
  description = "AMI ID used by the active encrypted backend instance"
  type        = string
}

variable "rollback_ami_id" {
  description = "AMI ID used by the stopped rollback instance"
  type        = string
}

variable "ec2_key_name" {
  description = "EC2 key pair name attached to the instances"
  type        = string
}

variable "ec2_iam_instance_profile" {
  description = "IAM instance profile attached to the instances"
  type        = string
}
