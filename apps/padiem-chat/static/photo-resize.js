// #5728 — big photos are resized in the browser, never on the Worker.
//
// 근거(플랫폼 한도): Cloudflare Workers 무료 플랜은 요청당 CPU 10ms·메모리 128MB다.
// 수 MB짜리 사진을 Worker가 디코드·리사이즈하면 그 CPU 한도를 넘겨 요청이 죽고,
// 사용자에게는 이유 없는 실패로 보인다. 그래서 원본 바이트를 그대로 올리지 않고,
// 업로드 전에 브라우저에서 긴 변을 화면·SNS에 필요한 크기로 줄인다.
//
// 이것은 업로드 상한이 아니다. 어떤 크기의 사진도 올릴 수 있고, 거부되지 않는다.
// 바뀌는 것은 저장되는 바이트의 해상도뿐이다 — 블로그·페이스북·인스타그램
// 미리보기와 게시물 미디어가 실제로 쓰는 크기가 1920px이므로, 그보다 큰 원본은
// 화면에 보이는 것과 같은 그림을 더 작은 바이트로 담는다.
(function (root) {
  "use strict";

  // 화면·SNS 게시물 미디어가 쓰는 긴 변. 더 큰 원본은 이 크기로 줄인다.
  var MAX_EDGE = 1920;
  // 눈에 띄는 손실 없이 바이트를 크게 줄이는 품질.
  var QUALITY = 0.85;
  // 원본이 이보다 작으면 다시 인코딩하지 않는다(재인코딩은 화질만 떨어뜨린다).
  var SKIP_EDGE = 256;

  function targetSize(width, height, maxEdge) {
    var w = Math.max(0, Math.floor(Number(width) || 0));
    var h = Math.max(0, Math.floor(Number(height) || 0));
    var edge = Math.max(SKIP_EDGE, Math.floor(Number(maxEdge) || MAX_EDGE));
    if (!w || !h) return { width: 0, height: 0 };
    var longest = Math.max(w, h);
    if (longest <= edge) return { width: w, height: h };
    var scale = edge / longest;
    return {
      width: Math.max(1, Math.round(w * scale)),
      height: Math.max(1, Math.round(h * scale)),
    };
  }

  function shouldResize(width, height, maxEdge) {
    var w = Math.max(0, Math.floor(Number(width) || 0));
    var h = Math.max(0, Math.floor(Number(height) || 0));
    var edge = Math.max(SKIP_EDGE, Math.floor(Number(maxEdge) || MAX_EDGE));
    return Math.max(w, h) > edge;
  }

  // Browser only: data URL in → { dataUrl, width, height, resized } out.
  // A browser that cannot decode or encode the image resolves with the original
  // bytes unchanged — the upload still happens, so a resize failure never costs
  // the user their photo.
  function resizeDataUrl(source, maxEdge, mimeType) {
    var edge = Math.max(SKIP_EDGE, Math.floor(Number(maxEdge) || MAX_EDGE));
    return new Promise(function (resolve) {
      var unchanged = function () {
        resolve({ dataUrl: source, width: 0, height: 0, resized: false });
      };
      if (typeof source !== "string" || source.indexOf("data:image/") !== 0) {
        unchanged();
        return;
      }
      if (typeof root.Image !== "function" || typeof root.document !== "object") {
        unchanged();
        return;
      }
      var img = new root.Image();
      img.onerror = unchanged;
      img.onload = function () {
        var width = img.naturalWidth || img.width || 0;
        var height = img.naturalHeight || img.height || 0;
        if (!shouldResize(width, height, edge)) {
          resolve({ dataUrl: source, width: width, height: height, resized: false });
          return;
        }
        var target = targetSize(width, height, edge);
        try {
          var canvas = root.document.createElement("canvas");
          canvas.width = target.width;
          canvas.height = target.height;
          var ctx = canvas.getContext("2d");
          if (!ctx) {
            unchanged();
            return;
          }
          ctx.drawImage(img, 0, 0, target.width, target.height);
          var type = typeof mimeType === "string" && mimeType.indexOf("image/") === 0
            ? mimeType : "image/jpeg";
          // PNG keeps transparency; JPEG/WebP re-encode with QUALITY.
          var encoded = type === "image/png"
            ? canvas.toDataURL("image/png")
            : canvas.toDataURL(type, QUALITY);
          if (typeof encoded !== "string" || encoded.indexOf("data:image/") !== 0) {
            unchanged();
            return;
          }
          resolve({
            dataUrl: encoded,
            width: target.width,
            height: target.height,
            resized: true,
          });
        } catch (_error) {
          unchanged();
        }
      };
      img.src = source;
    });
  }

  root.PadiemPhotoResize = Object.freeze({
    MAX_EDGE: MAX_EDGE,
    QUALITY: QUALITY,
    targetSize: targetSize,
    shouldResize: shouldResize,
    resizeDataUrl: resizeDataUrl,
  });
})(typeof window === "object" ? window : globalThis);
