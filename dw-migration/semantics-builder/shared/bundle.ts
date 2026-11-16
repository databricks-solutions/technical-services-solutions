/** The CI/CD bundle of a promoted view: null until a version is promoted to the current target. */
export interface BundleView {
  bundle: {
    target: string;
    version: number;
    fileName: string;
    /** Path to text, for the preview. */
    files: Record<string, string>;
    /** The same files as a zip, base64. */
    zip: string;
  } | null;
}
