type FileInputProps = {
  label: string;
  accept: string;
  file: File | null;
  onChange: (file: File | null) => void;
};

export function FileInput({ label, accept, file, onChange }: FileInputProps) {
  return (
    <label className="file-input">
      <span>{label}</span>
      <input
        type="file"
        accept={accept}
        onChange={(event) => onChange(event.target.files?.[0] || null)}
      />
      <small>{file ? file.name : "No file selected"}</small>
    </label>
  );
}
