resource "aws_security_group" "backend" {
  name        = "arrotech-hub-sg"
  description = "Arrotech Hub Backend"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
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

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_instance" "backend" {
  ami                    = var.backend_ami_id
  instance_type          = "t3.small"
  key_name               = var.ec2_key_name
  iam_instance_profile   = var.ec2_iam_instance_profile
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.backend.id]

  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "arrotech-hub-prod-encrypted"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_instance" "backend_rollback" {
  ami                    = var.rollback_ami_id
  instance_type          = "t3.small"
  key_name               = var.ec2_key_name
  iam_instance_profile   = var.ec2_iam_instance_profile
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.backend.id]

  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    encrypted             = false
    delete_on_termination = true
  }

  tags = {
    Name = "arrotech-hub-prod"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_eip" "backend" {
  domain   = "vpc"
  instance = aws_instance.backend.id

  lifecycle {
    prevent_destroy = true
  }
}
