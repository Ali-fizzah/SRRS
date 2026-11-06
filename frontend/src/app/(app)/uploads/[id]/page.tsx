import UploadDetail from "@/components/uploads/UploadDetail";

export default async function UploadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <UploadDetail id={id} />;
}
