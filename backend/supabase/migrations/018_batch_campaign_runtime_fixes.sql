-- Migration 018: Batch campaign runtime fixes

-- 1. Check for orphaned workspace_id references in batch_call_runs
DO $$
DECLARE
    orphan_count integer;
BEGIN
    SELECT COUNT(*) INTO orphan_count
    FROM public.batch_call_runs
    WHERE workspace_id NOT IN (SELECT id FROM public.workspaces);
    
    IF orphan_count > 0 THEN
        RAISE EXCEPTION 'Migration aborted: Found % orphaned workspace_id references in batch_call_runs. Please perform manual database review.', orphan_count;
    END IF;

    -- Check for orphaned workspace_id references in batch_call_items
    SELECT COUNT(*) INTO orphan_count
    FROM public.batch_call_items
    WHERE workspace_id NOT IN (SELECT id FROM public.workspaces);
    
    IF orphan_count > 0 THEN
        RAISE EXCEPTION 'Migration aborted: Found % orphaned workspace_id references in batch_call_items. Please perform manual database review.', orphan_count;
    END IF;
END $$;

-- 2. Clean up orphaned agent_id references (set to NULL as agent_id is nullable)
UPDATE public.batch_call_runs 
SET agent_id = NULL 
WHERE agent_id IS NOT NULL 
  AND agent_id NOT IN (SELECT id FROM public.agents);

UPDATE public.batch_call_items 
SET agent_id = NULL 
WHERE agent_id IS NOT NULL 
  AND agent_id NOT IN (SELECT id FROM public.agents);

-- 3. Normalize legacy status values
-- Update runs from pending -> queued
UPDATE public.batch_call_runs 
SET status = 'queued' 
WHERE status = 'pending';

-- Update runs from stopped -> cancelled
UPDATE public.batch_call_runs 
SET status = 'cancelled' 
WHERE status = 'stopped';

-- Update items from stopped -> cancelled
UPDATE public.batch_call_items 
SET status = 'cancelled' 
WHERE status = 'stopped';

-- 4. Apply status check constraints to batch_call_runs
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT conname 
        FROM pg_constraint 
        WHERE conrelid = 'public.batch_call_runs'::regclass AND conname LIKE '%status%'
    ) LOOP
        EXECUTE 'ALTER TABLE public.batch_call_runs DROP CONSTRAINT ' || quote_ident(r.conname);
    END LOOP;
END $$;

ALTER TABLE public.batch_call_runs
ADD CONSTRAINT chk_batch_call_runs_status
CHECK (status IN ('draft', 'queued', 'running', 'paused', 'completed', 'cancelled', 'failed'));

-- 5. Add foreign key constraints with safe behaviors
ALTER TABLE public.batch_call_runs
DROP CONSTRAINT IF EXISTS fk_batch_call_runs_workspace,
DROP CONSTRAINT IF EXISTS fk_batch_call_runs_agent;

ALTER TABLE public.batch_call_runs
ADD CONSTRAINT fk_batch_call_runs_workspace
FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE RESTRICT;

ALTER TABLE public.batch_call_runs
ADD CONSTRAINT fk_batch_call_runs_agent
FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;

ALTER TABLE public.batch_call_items
DROP CONSTRAINT IF EXISTS fk_batch_call_items_run,
DROP CONSTRAINT IF EXISTS fk_batch_call_items_workspace,
DROP CONSTRAINT IF EXISTS fk_batch_call_items_agent;

ALTER TABLE public.batch_call_items
ADD CONSTRAINT fk_batch_call_items_run
FOREIGN KEY (batch_run_id) REFERENCES public.batch_call_runs(id) ON DELETE CASCADE;

ALTER TABLE public.batch_call_items
ADD CONSTRAINT fk_batch_call_items_workspace
FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE RESTRICT;

ALTER TABLE public.batch_call_items
ADD CONSTRAINT fk_batch_call_items_agent
FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;

-- 6. Reload schema for PostgREST
NOTIFY pgrst, 'reload schema';
