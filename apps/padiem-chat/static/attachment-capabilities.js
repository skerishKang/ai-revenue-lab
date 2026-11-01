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
    freezeFormat({ label: "HWPX", extensions: [".hwpx"], mediaTypes: ["application/hwp+zip"] }),
    freezeFormat({ label: "XLSX", extensions: [".xlsx"], mediaTypes: ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"] }),
  ]);

  // #4379 removed the PADIEM byte total for an image or a binary document, and
  // #5734 removed the ones that counted a document's own length — the 96 KiB and
  // 40,000-character text bounds. The platform request limit and the Provider's
  // own limit are the real ceilings, and each reports itself. This file
  // therefore carries no size or length number for any attachment kind.
  const allDocuments = Object.freeze([...textDocuments, ...binaryDocuments]);

  // #2824: the runtime is the authority for whether binary parsing can run in
  // this deployment. Until the health check succeeds, do not promise binary
  // formats whose configured file lane has not yet been confirmed.
  let binaryEnabled = false;
  let fileLaneEnabled = false;

  function activeDocuments() {
    return binaryEnabled || fileLaneEnabled ? allDocuments : textDocuments;
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
    const documentDetail = binaryEnabled ? `${textLabels}; ${binaryLabels}` : documentLabels;

    if (language === "en") {
      return Object.freeze({
        imageFormats: imageLabels,
        documentFormats: documentLabels,
        idleNote: `Attach one image (${imageLabels}) or document (${documentLabels}).`,
        fileButtonTitle: `Attach one image (${imageLabels}) or document (${documentDetail}).`,
        unsupportedFormat: `Supported attachment formats: ${imageLabels}, ${documentLabels}.`,
      });
    }

    return Object.freeze({
      imageFormats: imageLabels,
      documentFormats: documentLabels,
      idleNote: `사진(${imageLabels}) 또는 문서(${documentLabels}) 한 개를 첨부할 수 있습니다.`,
      fileButtonTitle: `사진(${imageLabels}) 또는 문서(${documentDetail}) 한 개를 첨부합니다.`,
      unsupportedFormat: `지원 첨부 형식: ${imageLabels}·${documentLabels}.`,
    });
  }

  window.PadiemAttachmentCapabilities = Object.freeze({
    images,
    textDocuments,
    binaryDocuments,
    allDocuments,
    get accept() {
      return buildAccept();
    },
    get binarySupported() {
      return binaryEnabled;
    },
    get fileLaneSupported() { return fileLaneEnabled; },
    setFileLaneSupport(value) { fileLaneEnabled = value === true; },
    setBinarySupport(value) {
      binaryEnabled = value !== false;
    },
    copy,
  });
})();
