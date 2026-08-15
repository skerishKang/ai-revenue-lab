/* Canonical review-surface registry for owner program #396.
 *
 * Web targets were migrated to numbered Cloudflare Pages projects and
 * byte-verified against their exact PR heads. A small set of independently
 * reviewed 2026-08-15 Drive canonicals is routed to dedicated Final Review
 * Pages without rewriting historical PR/SHA lineage.
 */
(function () {
  "use strict";

  var VERIFIED = "CLOUDFLARE_REVIEW_VERIFIED";
  var AVAILABLE = "AVAILABLE_NON_WEB";

  var rows = [
    [6, 180, "fbfd7e47c319d4493bc25f0c18b3961bf5fd3122", "06-world-feed"],
    [7, 397, "9e4f3fa9f7e9b398abf6a4e87b3f2c95eb248802", "07-personal-meaning-map"],
    [8, 398, "72b478a5f51f76522a689dfd80321afb75b866ee", "08-family-newspaper"],
    [9, 399, "26bdf6e5c8d44921cecedafa3a8568ceb81ebf72", "09-personalized-childrens-story"],
    [10, 400, "ea40906005366b6356904ad10a93981d823b0f63", "10-fan-magazine"],
    [11, 401, "282cd9757d820ba3c496a083c1bea72fd18f1045", "11-language-learning-magazine"],
    [12, 402, "ac70446ace1bbba3ab02a49c637dcd205add93dc", "12-creator-mini-media"],
    [15, 403, "8b490afaa3808860c05dc6f0aa4e18d4ae26b1e0", "15-global-ai-newsroom"],
    [16, 404, "8f4db08b6d908fa073716a1e48bceb28fdafa91f", "16-personal-sports"],
    [17, 405, "fecfb4ce306870b6e035a4e425c7e9c2e86b326c", "17-local-shop-magazine"],
    [18, 406, "2014020c65f80d206520f14bcc10190850eafa7b", "18-personal-audio-channel"],
    [19, 407, "33b1f30b54d23a91ed6f0a257977741ddf8cbace", "19-personal-memory-book"],
    [20, 408, "55ba9e9b4d63494428addf13e644b57581228aeb", "20-personal-memory-novel"],
    [21, 409, "5f18d9a727c9fe4e1ea492657dfd72189b3f2a73", "21-founder-strategy-letter"],
    [22, 410, "9e42eb6641fa8f1d662db263a00e27e2597ace4e", "22-personal-media-studio"],
    [32, 354, "73ec4718d0835248ab20d56bc68f3956536112b4", "32-ai-skill-studio"],
    [33, 411, "c034ccae74d038bb3c5517c62e3c290db5bffc2a", "33-research-memory"],
    [34, 412, "4e77ce30ffc266997ba26fa55fd835c6fca32c85", "34-ai-dubbing-studio"],
    [35, 370, "1bc3469baae6ac7d4a1ff362a4a2b4b0af8079d2", "35-ai-media-education-dx"],
    [36, 413, "6d0e904b33b68754b61b45568389c7a67b7124eb", "36-ai-women-safety"],
    [37, 414, "03d43309500aa8be07204fa0e6d6eaf602bbc23d", "37-ai-safe-route"],
    [38, 415, "d24aeb46cc74d5b7c9fa70f270345d92c133b000", "38-ai-exercise-coach"],
    [39, 416, "f62149fee46dc6bb7c9a26a2c20850b925342d43", "39-112-real-time-interpretation"],
    [40, 417, "82e71599ef539443a6a97fb97d038bc962b660cd", "40-emergency-urgency-ai"],
    [41, 418, "e59e82204be94f2f0c49bb9fce01a9c81711ed5e", "41-foreign-emergency-assistant"],
    [42, 419, "04789d43cf99c94a9c4a3a4c39f4c501c74c128d", "42-ai-development-control-tower"],
    [43, 420, "2cb76c6a7e27b2d7c74c75113ec24ecd4164978f", "43-ai-software-factory"],
    [45, 421, "b649a824839003145090fe870ded899d551d2733", "45-ai-content-engine"],
    [46, 422, "2747d64c2387bb6f76dda6e3c619604150d7dd21", "46-ai-personalization-engine"],
    [47, 423, "744a0c9ee66da73e774c4fa24fe12a5bad428b80", "47-real-time-feedback-engine"],
    [48, 424, "3e662d330a8b30383d4bfc1f8b0319a3e9e2382e", "48-ai-verification-engine"],
    [49, 425, "84d24d3665e91413f36822697d6cd7905035781e", "49-public-data-connector-hub"],
    [51, 426, "1accf2929dac862233434aed3b512335b37a55c3", "51-ai-workflow-marketplace"],
    [52, 427, "19e78810554e5680f925af8c807254b5ea7baba1", "52-scheduled-agent-operations"],
    [53, 428, "b4e8f962e51dd298174d0a070dcfb5759f9935c6", "53-embedded-ai-sdk"],
    [55, 429, "3e3eb0aff6eeb198b342be59b312dd265c3ced55", "55-local-ai-fleet"],
    [57, 430, "930a8dc4c2d13c2537c723ee76eec8217983d8e3", "57-classic-literature-translation"],
    [58, 431, "135a0cd0901ca132346ad2d1e1537d1c6fef8444", "58-personal-writing-voice"],
    [59, 392, "f327093a445086d4efb79452b1bc62ba53ff8a9b", "59-living-archive"],
  ];

  var finalReviewed = {
    6: {
      project: "ai-revenue-final-review-b06",
      sha256: "888e91e45c9d02d214cd8a7fef6b710586d09f4b02e07ae3f82e717ed02c634e",
    },
    7: {
      project: "ai-revenue-final-review-b07",
      sha256: "b4c055f23e1b9b488ed2d6dd2b31d8ef5c0451de71bcf4851ff5982766463d89",
    },
    8: {
      project: "ai-revenue-final-review-b08",
      sha256: "fce0b556f32ec27787cad9f1827e4daa7027ad538b7cebb75dcc967df5334919",
    },
    9: {
      project: "ai-revenue-final-review-b09",
      sha256: "81ee4dfe890f04631b2ec3fffae6d4f450ce21d9913917baf2522aac0d4e49db",
    },
    11: {
      project: "ai-revenue-final-review-b11",
      sha256: "416b8c8c85014195912554b5a327c3975d4c2844841bf95248eb5003bc83a358",
    },
  };

  var map = {};
  rows.forEach(function (row) {
    var number = row[0];
    var finalReview = finalReviewed[number] || null;
    var project = finalReview ? finalReview.project : row[3];
    var url = "https://" + project + ".pages.dev/";
    map[number] = {
      number: number,
      kind: "web-review",
      status: VERIFIED,
      pr: row[1],
      exactHead: row[2],
      project: project,
      entry: "index.html",
      plannedUrl: url,
      surfaceUrl: url,
      finalReviewDate: finalReview ? "2026-08-15" : null,
      finalReviewSha256: finalReview ? finalReview.sha256 : null,
    };
  });

  map[54] = {
    number: 54,
    kind: "cli-tui",
    status: AVAILABLE,
    pr: 432,
    exactHead: "815f4de1b5e3ce517692d366ccbf15ffb017c5e2",
    plannedUrl: "https://github.com/skerishKang/ai-revenue-lab/pull/432",
  };

  window.ARL_REVIEW_SURFACES = map;
  (window.ARL_BUSINESSES || []).forEach(function (business) {
    if (!map[business.number]) return;
    business.reviewSurface = map[business.number];
    if (map[business.number].kind === "cli-tui") {
      business.surfaceUrl = map[business.number].plannedUrl;
    } else {
      business.surfaceUrl = map[business.number].surfaceUrl;
    }
  });
})();
