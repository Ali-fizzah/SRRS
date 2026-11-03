import PlaceholderPage from "@/components/PlaceholderPage";
import { routeInfo } from "@/components/routes";

/** Placeholder for a nav route, using its entry in routes.ts. */
export default function RoutePlaceholder({ path }: { path: string }) {
  const { title, description, task } = routeInfo(path);
  return <PlaceholderPage title={title} description={description} task={task} />;
}
