-- Initialize Mini-Hub database
-- This script runs when the PostgreSQL container starts

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Set timezone
SET timezone = 'UTC';

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);

-- Create views for analytics
CREATE OR REPLACE VIEW daily_usage_summary AS
SELECT 
    user_id,
    DATE(created_at) as usage_date,
    COUNT(*) as total_requests,
    COUNT(CASE WHEN success = true THEN 1 END) as successful_requests,
    COUNT(CASE WHEN success = false THEN 1 END) as failed_requests,
    AVG(response_time_ms) as avg_response_time
FROM usage_logs 
GROUP BY user_id, DATE(created_at);

-- Create function for usage tracking
CREATE OR REPLACE FUNCTION log_usage(
    p_user_id INTEGER,
    p_tool_name TEXT,
    p_arguments TEXT,
    p_response_time_ms INTEGER,
    p_success BOOLEAN,
    p_error_message TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    INSERT INTO usage_logs (
        user_id, tool_name, arguments, response_time_ms, 
        success, error_message, created_at
    ) VALUES (
        p_user_id, p_tool_name, p_arguments, p_response_time_ms,
        p_success, p_error_message, NOW()
    );
END;
$$ LANGUAGE plpgsql;

-- Create function to get user usage
CREATE OR REPLACE FUNCTION get_user_usage(
    p_user_id INTEGER,
    p_date DATE DEFAULT CURRENT_DATE
) RETURNS TABLE(
    total_requests BIGINT,
    successful_requests BIGINT,
    failed_requests BIGINT,
    avg_response_time NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*) as total_requests,
        COUNT(CASE WHEN success = true THEN 1 END) as successful_requests,
        COUNT(CASE WHEN success = false THEN 1 END) as failed_requests,
        AVG(response_time_ms) as avg_response_time
    FROM usage_logs 
    WHERE user_id = p_user_id 
    AND DATE(created_at) = p_date;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO minihub;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO minihub;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO minihub; 