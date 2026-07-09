-- Create task_status enum
DO $$ BEGIN
    CREATE TYPE task_status AS ENUM (
        'scheduled',
        'running',
        'completed',
        'failed',
        'cancelled',
        'paused'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create scheduled_tasks table
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    task_type VARCHAR(50) NOT NULL DEFAULT 'voice_call',
    title VARCHAR(255) NOT NULL,
    description TEXT,
    scheduled_time_utc TIMESTAMPTZ NOT NULL,
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
    recurrence_rule TEXT, 
    status task_status NOT NULL DEFAULT 'scheduled',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE scheduled_tasks ENABLE ROW LEVEL SECURITY;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user_id ON scheduled_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_workspace_id ON scheduled_tasks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status ON scheduled_tasks(status);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(next_run_at) WHERE status = 'scheduled';

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DO $$ BEGIN
    CREATE TRIGGER update_scheduled_tasks_updated_at
        BEFORE UPDATE ON scheduled_tasks
        FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;
-- RLS Policies
CREATE POLICY "Users can view their own scheduled tasks"
ON scheduled_tasks FOR SELECT
USING (auth.uid() = user_id);

CREATE POLICY "Users can create their own scheduled tasks"
ON scheduled_tasks FOR INSERT
WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own scheduled tasks"
ON scheduled_tasks FOR UPDATE
USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own scheduled tasks"
ON scheduled_tasks FOR DELETE
USING (auth.uid() = user_id);
