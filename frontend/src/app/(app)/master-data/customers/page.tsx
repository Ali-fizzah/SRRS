import CustomersGrid from "@/components/master/CustomersGrid";
import MasterPage from "@/components/master/MasterPage";
import { routeInfo } from "@/components/routes";

export default function Page() {
  const { title, description } = routeInfo("/master-data/customers");
  return (
    <MasterPage title={title} description={description}>
      <CustomersGrid />
    </MasterPage>
  );
}
