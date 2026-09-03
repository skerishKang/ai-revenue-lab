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

  const limits = Object.freeze({
    imageBytes: 4 * 1024 * 1024,
    textBytes: 96 * 1024,
    textChars: 40000,
    binaryBytes: 2 * 1024 * 1024,
  });

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
        fileButtonTitle: `Attach one image (${imageLabels}, up to 4 MiB) or document (${textLabels}, up to 96 KiB / 40,000 characters; ${binaryLabels}, up to 2 MiB).`,
        unsupportedFormat: `Supported attachment formats: ${imageLabels}, ${documentLabels}.`,
        imageTooLarge: "Images must be 4 MiB or smaller.",
        textTooLarge: "Text documents must be 96 KiB or smaller.",
        textTooLong: "Text documents must be 40,000 characters or fewer.",
        binaryTooLarge: `${binaryLabels} documents must be 2 MiB or smaller.`,
      });
    }

    return Object.freeze({
      imageFormats: imageLabels,
      documentFormats: documentLabels,
      idleNote: `사진(${imageLabels}) 또는 문서(${documentLabels}) 한 개를 첨부할 수 있습니다.`,
      fileButtonTitle: `사진(${imageLabels}, 최대 4 MiB) 또는 문서(${textLabels}, 최대 96 KiB/40,000자; ${binaryLabels}, 최대 2 MiB) 한 개를 첨부합니다.`,
      unsupportedFormat: `지원 첨부 형식: ${imageLabels}·${documentLabels}.`,
      imageTooLarge: "사진은 4 MiB 이하만 첨부할 수 있습니다.",
      textTooLarge: "텍스트 문서는 96 KiB 이하만 첨부할 수 있습니다.",
      textTooLong: "텍스트 문서는 40,000자 이하만 첨부할 수 있습니다.",
      binaryTooLarge: `${binaryLabels} 문서는 2 MiB 이하만 첨부할 수 있습니다.`,
    });
  }

  window.PadiemAttachmentCapabilities = Object.freeze({
    images,
    textDocuments,
    binaryDocuments,
    allDocuments,
    limits,
    accept,
    copy,
  });
})();
