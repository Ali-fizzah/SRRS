import PlaceholderPage from "@/components/PlaceholderPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <PlaceholderPage
      title={`Contract ${id}`}
      description="Versions timeline, lines, POs and allocation, schedule, billing, journal lines, source rows."
      task="P2-T5 / P3-T8"
    />
  );
}
