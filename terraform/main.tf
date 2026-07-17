# Scoped IAM identity for slowlog-agent, plus a data-source reference to the
# slow-query log group it reads. The log group itself is expected to already
# exist (created by the CloudWatch agent running on the MySQL host) — this
# config never creates or deletes it, only grants read-only access to it.

terraform {
  required_version = ">= 1.5"

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

data "aws_cloudwatch_log_group" "slow_query" {
  name = var.log_group_name
}

resource "aws_iam_user" "slowlog_agent" {
  name = var.iam_user_name
  path = "/slowlog-agent/"

  tags = {
    ManagedBy = "terraform"
    Project   = "slowlog-agent"
  }
}

# Read-only, single-log-group-scoped policy. slowlog-agent never needs write
# access to AWS or to the database it analyzes — see README's Security Model.
resource "aws_iam_user_policy" "slowlog_agent_logs_readonly" {
  name = "slowlog-agent-logs-readonly"
  user = aws_iam_user.slowlog_agent.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SlowlogAgentReadOnlyLogs"
        Effect = "Allow"
        Action = [
          "logs:FilterLogEvents",
          "logs:GetLogEvents",
          "logs:StartQuery",
          "logs:GetQueryResults",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
        ]
        Resource = [
          data.aws_cloudwatch_log_group.slow_query.arn,
          "${data.aws_cloudwatch_log_group.slow_query.arn}:*",
        ]
      }
    ]
  })
}

resource "aws_iam_access_key" "slowlog_agent" {
  user = aws_iam_user.slowlog_agent.name
}
