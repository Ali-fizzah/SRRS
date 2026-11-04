import ProductsGrid from "@/components/master/ProductsGrid";
import MasterPage from "@/components/master/MasterPage";
import { routeInfo } from "@/components/routes";

export default function Page() {
  const { title, description } = routeInfo("/master-data/products");
  return (
    <MasterPage title={title} description={description}>
      <ProductsGrid />
    </MasterPage>
  );
}
