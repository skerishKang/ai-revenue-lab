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

  const allDocuments = Object.freeze([...textDocuments, ...binaryDocuments]);
  const acceptedTokens = [];
  [...images, ...allDocuments].forEach((format) => {
    format.mediaTypes.forEach((value) => acceptedTokens.push(value));
    format.extensions.forEach((value) => acceptedTokens.push(value));
  });
  const accept = Object.freeze(Array.from(new Set(acceptedTokens))).join(",");

  const labelsFor = (formats, separator) => formats.map((format) => format.label).join(separator);

  function copy(lang) {
    const language = lang === "en" ? "en" : "ko";
    const imageLabels = labelsFor(images, language === "en" ? ", " : "·");
    const documentLabels = labelsFor(allDocuments, language === "en" ? ", " : "·");
    const textLabels = labelsFor(textDocuments, language === "en" ? ", " : "·");
    const binaryLabels = labelsFor(binaryDocuments, language === "en" ? ", " : "·");

    if (language === "en") {
      return Object.freeze({
        imageFormats: imageLabels,
        documentFormats: documentLabels,
        idleNote: `Attach one image (${imageLabels}) or document (${documentLabels}).`,
        fileButtonTitle: `Attach one image (${imageLabels}) or document (${textLabels}, ${binaryLabels}).`,
        unsupportedFormat: `Supported attachment formats: ${imageLabels}, ${documentLabels}.`,
      });
    }

    return Object.freeze({
      imageFormats: imageLabels,
      documentFormats: documentLabels,
      idleNote: `사진(${imageLabels}) 또는 문서(${documentLabels}) 한 개를 첨부할 수 있습니다.`,
      fileButtonTitle: `사진(${imageLabels}) 또는 문서(${textLabels}, ${binaryLabels}) 한 개를 첨부합니다.`,
      unsupportedFormat: `지원 첨부 형식: ${imageLabels}·${documentLabels}.`,
    });
  }

  window.PadiemAttachmentCapabilities = Object.freeze({
    images,
    textDocuments,
    binaryDocuments,
    allDocuments,
    accept,
    copy,
  });
})();
