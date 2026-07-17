output "iam_user_name" {
  description = "Name of the IAM user created for slowlog-agent."
  value       = aws_iam_user.slowlog_agent.name
}

output "iam_user_arn" {
  description = "ARN of the IAM user created for slowlog-agent."
  value       = aws_iam_user.slowlog_agent.arn
}

output "log_group_arn" {
  description = "ARN of the slow-query log group slowlog-agent is scoped to read."
  value       = data.aws_cloudwatch_log_group.slow_query.arn
}

output "access_key_id" {
  description = "AWS access key ID for slowlog-agent. Store it in a named AWS profile (~/.aws/credentials) — never commit it."
  value       = aws_iam_access_key.slowlog_agent.id
}

output "secret_access_key" {
  description = "AWS secret access key for slowlog-agent. Retrieve with `terraform output -raw secret_access_key` and store it directly in a named AWS profile — never commit it, print it in CI logs, or paste it anywhere other than ~/.aws/credentials."
  value       = aws_iam_access_key.slowlog_agent.secret
  sensitive   = true
}
