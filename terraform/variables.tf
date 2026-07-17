variable "aws_region" {
  description = "AWS region the CloudWatch Logs log group lives in."
  type        = string
}

variable "log_group_name" {
  description = "Name of the existing MySQL slow-query CloudWatch Logs log group (created by the CloudWatch agent) that slowlog-agent should be scoped to read."
  type        = string
}

variable "iam_user_name" {
  description = "Name of the scoped IAM user created for slowlog-agent."
  type        = string
  default     = "slowlog-agent"
}
