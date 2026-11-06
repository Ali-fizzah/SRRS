import ContractDetail from "@/components/contracts/ContractDetail";

export default async function ContractPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ContractDetail id={id} />;
}
