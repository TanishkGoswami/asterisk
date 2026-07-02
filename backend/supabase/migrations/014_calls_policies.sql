-- Migration to allow authenticated users to read and write calls and call_messages

CREATE POLICY "Allow authenticated users to manage calls"
ON public.calls
FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);

CREATE POLICY "Allow authenticated users to manage call_messages"
ON public.call_messages
FOR ALL
TO authenticated
USING (true)
WITH CHECK (true);
