import GlAccountsGrid from "@/components/master/GlAccountsGrid";
import MasterPage from "@/components/master/MasterPage";
import { routeInfo } from "@/components/routes";

export default function Page() {
  const { title, description } = routeInfo("/master-data/accounts");
  return (
    <MasterPage title={title} description={description}>
      <GlAccountsGrid />
    </MasterPage>
  );
}
