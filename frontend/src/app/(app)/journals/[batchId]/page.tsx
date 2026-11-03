import PlaceholderPage from "@/components/PlaceholderPage";

export default async function Page({ params }: { params: Promise<{ batchId: string }> }) {
  const { batchId } = await params;
  return (
    <PlaceholderPage
      title={`Journal batch ${batchId}`}
      description="Entries and lines, balance check, reverse action."
      task="P4-T5"
    />
  );
}
