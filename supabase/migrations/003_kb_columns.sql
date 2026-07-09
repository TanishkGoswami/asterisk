-- Add knowledge base and KB metadata columns to agents table
ALTER TABLE agents ADD COLUMN IF NOT EXISTS knowledge_base TEXT DEFAULT '';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS kb_source_url TEXT;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS kb_metadata JSONB DEFAULT '{}';
