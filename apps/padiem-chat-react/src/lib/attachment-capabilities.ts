/**
 * #5298 — typed access to the operational attachment capability contract.
 *
 * `apps/padiem-chat/static/attachment-capabilities.js` is the single source for
 * the accepted attachment formats, their size limits and the Korean composer
 * note. The clone consumes that source instead of restating the formats, so
 * the composer note and the file picker cannot drift from the product.
 */

import "../../../../apps/padiem-chat/static/attachment-capabilities.js";

export interface AttachmentFormat {
  label: string;
  extensions: string[];
  mediaTypes: string[];
}

export interface AttachmentCapabilityCopy {
  imageFormats: string;
  documentFormats: string;
  idleNote: string;
  fileButtonTitle: string;
  unsupportedFormat: string;
  imageTooLarge: string;
  textTooLarge: string;
  textTooLong: string;
  binaryTooLarge: string;
}

export interface AttachmentCapabilities {
  images: AttachmentFormat[];
  textDocuments: AttachmentFormat[];
  binaryDocuments: AttachmentFormat[];
  allDocuments: AttachmentFormat[];
  limits: Record<string, number>;
  accept: string;
  copy(language: string): AttachmentCapabilityCopy;
}

const runtime = globalThis as typeof globalThis & {
  PadiemAttachmentCapabilities?: AttachmentCapabilities;
};

const capabilities = runtime.PadiemAttachmentCapabilities;

if (!capabilities) {
  throw new Error(
    "apps/padiem-chat/static/attachment-capabilities.js did not publish PadiemAttachmentCapabilities",
  );
}

export const attachmentCapabilities: AttachmentCapabilities = capabilities;
