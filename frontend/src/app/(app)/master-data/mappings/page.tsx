import GlMappingsGrid from "@/components/master/GlMappingsGrid";
import MasterPage from "@/components/master/MasterPage";
import { routeInfo } from "@/components/routes";

export default function Page() {
  const { title, description } = routeInfo("/master-data/mappings");
  return (
    <MasterPage title={title} description={description}>
      <GlMappingsGrid />
    </MasterPage>
  );
}
