import { createFileRoute } from "@tanstack/react-router";
import { Playground } from "@/components/dashboard/Playground";

export const Route = createFileRoute("/_authenticated/dashboard/qa")({
  component: AdminPlaygroundPage,
  validateSearch: (search: Record<string, unknown>) => ({
    agentId: typeof search.agentId === "string" ? search.agentId : undefined,
  }),
});

function AdminPlaygroundPage() {
  const { agentId } = Route.useSearch();
  return <Playground initialAgentId={agentId} />;
}
