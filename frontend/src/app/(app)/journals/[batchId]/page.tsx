import BatchDetail from "@/components/journals/BatchDetail";

export default async function Page({ params }: { params: Promise<{ batchId: string }> }) {
  const { batchId } = await params;
  return <BatchDetail id={batchId} />;
}
