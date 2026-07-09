-- Create scheduled_task_logs table
CREATE TABLE IF NOT EXISTS scheduled_task_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_task_id UUID NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL, -- e.g., 'success', 'failed', 'retrying'
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    duration_ms INT,
    attempt_number INT NOT NULL DEFAULT 1,
    result JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE scheduled_task_logs ENABLE ROW LEVEL SECURITY;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_task_logs_task_id ON scheduled_task_logs(scheduled_task_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_created_at ON scheduled_task_logs(created_at DESC);

-- Policy to ensure users can only see logs for tasks they own
-- Assuming users can see tasks in their workspaces
CREATE POLICY "Users can view logs for tasks in their workspaces"
ON scheduled_task_logs
FOR SELECT
USING (
    scheduled_task_id IN (
        SELECT id FROM scheduled_tasks WHERE workspace_id IN (
            SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
        )
    )
);
