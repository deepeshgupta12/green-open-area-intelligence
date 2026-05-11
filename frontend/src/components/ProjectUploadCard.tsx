import { FileInput } from "./FileInput";

type ProjectUploadCardProps = {
  slot: "A" | "B" | "C";
  title: string;
  jsonFile: File | null;
  imageFile: File | null;
  setJsonFile: (file: File | null) => void;
  setImageFile: (file: File | null) => void;
};

export function ProjectUploadCard({
  slot,
  title,
  jsonFile,
  imageFile,
  setJsonFile,
  setImageFile,
}: ProjectUploadCardProps) {
  return (
    <section className="upload-card">
      <div className="slot-pill">Project {slot}</div>
      <h3>{title}</h3>
      <FileInput
        label="Datacenter JSON"
        accept=".json,application/json"
        file={jsonFile}
        onChange={setJsonFile}
      />
      <FileInput
        label="Master Plan Image"
        accept="image/png,image/jpeg,image/jpg,image/webp"
        file={imageFile}
        onChange={setImageFile}
      />
    </section>
  );
}
