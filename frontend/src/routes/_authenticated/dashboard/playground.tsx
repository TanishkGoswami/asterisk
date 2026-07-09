import { createFileRoute } from "@tanstack/react-router";
import { Playground } from "@/components/dashboard/Playground";

export const Route = createFileRoute("/_authenticated/dashboard/playground")({
  component: DashboardPlaygroundPage,
});

function DashboardPlaygroundPage() {
  return <Playground />;
}
