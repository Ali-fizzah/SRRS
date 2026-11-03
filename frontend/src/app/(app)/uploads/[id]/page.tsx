import PlaceholderPage from "@/components/PlaceholderPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <PlaceholderPage
      title={`Upload ${id}`}
      description="Validation log for one upload, with CSV download."
      task="P1-T10"
    />
  );
}
