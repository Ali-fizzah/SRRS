import ApiHealth from "@/components/ApiHealth";
import PlaceholderPage from "@/components/PlaceholderPage";
import { routeInfo } from "@/components/routes";

export default function DashboardPage() {
  const { title, description, task } = routeInfo("/");
  return (
    <PlaceholderPage title={title} description={description} task={task}>
      <ApiHealth />
    </PlaceholderPage>
  );
}
