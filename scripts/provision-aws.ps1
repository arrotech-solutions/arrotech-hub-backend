$ErrorActionPreference = "Stop"

$aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"

Write-Host "1/6 Creating Key Pair..."
& $aws ec2 create-key-pair --key-name arrotech-hub-key --query 'KeyMaterial' --output text | Out-File -FilePath arrotech-hub-key.pem -Encoding ascii
# Note: On Windows, chmod 400 is not strictly necessary or easily done via one command, but AWS might complain if permissions are too open. We'll set basic ACLs later if needed, but for now we just create the file.

Write-Host "2/6 Creating Security Group..."
$sgId = & $aws ec2 create-security-group --group-name arrotech-hub-sg --description "Arrotech Hub Backend" --query 'GroupId' --output text

Write-Host "Authorizing Security Group Ingress..."
& $aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 22 --cidr 0.0.0.0/0 | Out-Null
& $aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 80 --cidr 0.0.0.0/0 | Out-Null
& $aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 443 --cidr 0.0.0.0/0 | Out-Null

Write-Host "3/6 Launching EC2 Instance..."
$instanceInfo = & $aws ec2 run-instances `
    --image-id ami-0c7217cdde317cfec `
    --instance-type t3.small `
    --key-name arrotech-hub-key `
    --security-group-ids $sgId `
    --block-device-mappings '[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":30,\"VolumeType\":\"gp3\"}}]' `
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=arrotech-hub-prod}]' `
    --query 'Instances[0].InstanceId' `
    --output text

$instanceId = $instanceInfo.Trim()
Write-Host "Instance ID: $instanceId"

Write-Host "Waiting for instance to enter running state..."
& $aws ec2 wait instance-running --instance-ids $instanceId

Write-Host "4/6 Allocating Elastic IP..."
$allocInfo = & $aws ec2 allocate-address --domain vpc --output json | ConvertFrom-Json
$allocId = $allocInfo.AllocationId
$publicIp = $allocInfo.PublicIp
Write-Host "Allocated IP: $publicIp"

Write-Host "5/6 Associating Elastic IP..."
& $aws ec2 associate-address --instance-id $instanceId --allocation-id $allocId | Out-Null

Write-Host "6/6 Creating S3 Bucket..."
# Try to create bucket, ignore if it already exists
try {
    & $aws s3 mb s3://arrotech-hub-backups-prod --region us-east-1
} catch {
    Write-Host "Bucket might already exist or name taken, trying with random suffix..."
    $suffix = Get-Random -Maximum 99999
    & $aws s3 mb s3://arrotech-hub-backups-$suffix --region us-east-1
}

Write-Host "======================================"
Write-Host "AWS Provisioning Complete!"
Write-Host "Public IP: $publicIp"
Write-Host "======================================"

$outputObj = @{
    PublicIp = $publicIp
    InstanceId = $instanceId
}
$outputObj | ConvertTo-Json | Out-File -FilePath aws-provision-result.json
