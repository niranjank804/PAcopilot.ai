import { ApiError, apiRequest } from "@/lib/api-client";

/**
 * Put a file in storage directly, then hand the API its key.
 *
 * The API on Vercel cannot accept a body over 4.5 MB, and a knowledge
 * document, a PAfE workbook or a chat attachment often is. So the browser
 * asks for a signed URL, PUTs the file to S3 itself, and the endpoint
 * that consumes it is given the key. The server reads the bytes from S3,
 * where no such limit applies.
 *
 * Returns null where the server has no S3 configured (a local or Render
 * deployment), and the caller sends the file the old way instead.
 */

export interface UploadedFileRef {
  key: string;
  filename: string;
}

interface UploadTarget {
  key: string;
  url: string;
  headers: Record<string, string>;
  expires_in: number;
}

export async function directUpload(file: File): Promise<UploadedFileRef | null> {
  let target: UploadTarget;

  try {
    target = await apiRequest<UploadTarget>("/uploads", {
      method: "POST",
      body: {
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
      },
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 503) return null;

    throw error;
  }

  // No Authorization header: the URL is the authorization, and a bearer
  // token sent to S3 would be a token sent to the wrong party.
  let response: Response;

  try {
    response = await fetch(target.url, {
      method: "PUT",
      headers: target.headers,
      body: file,
    });
  } catch {
    // The request never reached storage — most often a bucket with no
    // CORS rule for this origin, which the browser reports as a bare
    // network failure. The multipart path still works, so use it rather
    // than fail an upload over a missing configuration line.
    return null;
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      "UPLOAD_FAILED",
      `"${file.name}" could not be uploaded to storage (HTTP ${response.status}).`,
    );
  }

  return { key: target.key, filename: file.name };
}

/** All or nothing: if direct upload is unavailable, none are sent that way. */
export async function directUploadAll(files: File[]): Promise<UploadedFileRef[] | null> {
  const refs: UploadedFileRef[] = [];

  for (const file of files) {
    const ref = await directUpload(file);

    if (!ref) return null;

    refs.push(ref);
  }

  return refs;
}
