(() => {
  "use strict";

  const freezeFormat = (format) => Object.freeze({
    ...format,
    extensions: Object.freeze([...(format.extensions || [])]),
    mediaTypes: Object.freeze([...(format.mediaTypes || [])]),
  });

  const images = Object.freeze([
    freezeFormat({ label: "JPEG", extensions: [".jpg", ".jpeg"], mediaTypes: ["image/jpeg"] }),
    freezeFormat({ label: "PNG", extensions: [".png"], mediaTypes: ["image/png"] }),
    freezeFormat({ label: "WebP", extensions: [".webp"], mediaTypes: ["image/webp"] }),
  ]);

  const textDocuments = Object.freeze([
    freezeFormat({ label: "TXT", extensions: [".txt"], mediaTypes: ["text/plain"] }),
    freezeFormat({ label: "Markdown", extensions: [".md", ".markdown"], mediaTypes: ["text/markdown"] }),
    freezeFormat({ label: "CSV", extensions: [".csv"], mediaTypes: ["text/csv"] }),
    freezeFormat({ label: "JSON", extensions: [".json"], mediaTypes: ["application/json"] }),
  ]);

  const binaryDocuments = Object.freeze([
    freezeFormat({ label: "PDF", extensions: [".pdf"], mediaTypes: ["application/pdf"] }),
    freezeFormat({ label: "DOCX", extensions: [".docx"], mediaTypes: ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"] }),
    freezeFormat({ label: "PPTX", extensions: [".pptx"], mediaTypes: ["application/vnd.openxmlformats-officedocument.presentationml.presentation"] }),
    freezeFormat({ label: "XLSX", extensions: [".xlsx"], mediaTypes: ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"] }),
  ]);

  // #4379: an attached image or binary document carries no PADIEM byte
  // total. The platform request limit and the provider limit are the real
  // ceilings, and the route reader stays incremental instead of applying a
  // product-side maximum. The text bounds below are a data shape, not a total.
  const limits = Object.freeze({
    textBytes: 96 * 1024,
    textChars: 40000,
  });

  const allDocuments = Object.freeze([...textDocuments, ...binaryDocuments]);

  // #2824: the runtime is the authority for whether binary parsing can run in
  // this deployment. Unknown defaults to supported, so a transient health
  // failure never hides a capability the server would accept.
  let binaryEnabled = true;

  function activeDocuments() {
    return binaryEnabled ? allDocuments : textDocuments;
  }

  function buildAccept() {
    const acceptedTokens = [];
    [...images, ...activeDocuments()].forEach((format) => {
      format.mediaTypes.forEach((value) => acceptedTokens.push(value));
      format.extensions.forEach((value) => acceptedTokens.push(value));
    });
    return Array.from(new Set(acceptedTokens)).join(",");
  }

  const labelsFor = (formats, separator) => formats.map((format) => format.label).join(separator);

  function copy(lang) {
    const language = lang === "en" ? "en" : "ko";
    const imageLabels = labelsFor(images, language === "en" ? ", " : "·");
    const documentLabels = labelsFor(activeDocuments(), language === "en" ? ", " : "·");
    const textLabels = labelsFor(textDocuments, language === "en" ? ", " : "·");
    const binaryLabels = labelsFor(binaryDocuments, language === "en" ? ", " : "·");
    const textLimit = language === "en" ? "up to 96 KiB / 40,000 characters" : "최대 96 KiB/40,000자";
    const documentDetail = binaryEnabled
      ? `${textLabels}, ${textLimit}; ${binaryLabels}`
      : `${textLabels}, ${textLimit}`;

    if (language === "en") {
      return Object.freeze({
        imageFormats: imageLabels,
        documentFormats: documentLabels,
        idleNote: `Attach one image (${imageLabels}) or document (${documentLabels}).`,
        fileButtonTitle: `Attach one image (${imageLabels}) or document (${documentDetail}).`,
        unsupportedFormat: `Supported attachment formats: ${imageLabels}, ${documentLabels}.`,
        textTooLarge: "Text documents must be 96 KiB or smaller.",
        textTooLong: "Text documents must be 40,000 characters or fewer.",
      });
    }

    return Object.freeze({
      imageFormats: imageLabels,
      documentFormats: documentLabels,
      idleNote: `사진(${imageLabels}) 또는 문서(${documentLabels}) 한 개를 첨부할 수 있습니다.`,
      fileButtonTitle: `사진(${imageLabels}) 또는 문서(${documentDetail}) 한 개를 첨부합니다.`,
      unsupportedFormat: `지원 첨부 형식: ${imageLabels}·${documentLabels}.`,
      textTooLarge: "텍스트 문서는 96 KiB 이하만 첨부할 수 있습니다.",
      textTooLong: "텍스트 문서는 40,000자 이하만 첨부할 수 있습니다.",
    });
  }

  window.PadiemAttachmentCapabilities = Object.freeze({
    images,
    textDocuments,
    binaryDocuments,
    allDocuments,
    limits,
    get accept() {
      return buildAccept();
    },
    get binarySupported() {
      return binaryEnabled;
    },
    setBinarySupport(value) {
      binaryEnabled = value !== false;
    },
    copy,
  });
})();
