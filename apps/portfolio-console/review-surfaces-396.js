/* Review-surface registry for owner program #396.
 *
 * Only surfaces whose deployed Cloudflare Pages bytes were verified to match
 * the exact manifest head (`sha256(public) === sha256(source)`) are promoted to
 * `surfaceUrl` with status `CLOUDFLARE_REVIEW_VERIFIED`. Pending targets remain
 * attached as review metadata only and are NOT promoted to `surfaceUrl`.
 */
(function () {
  "use strict";

  var PENDING = "CLOUDFLARE_REVIEW_DEPLOY_PENDING";
  var VERIFIED = "CLOUDFLARE_REVIEW_VERIFIED";
  var AVAILABLE = "AVAILABLE_NON_WEB";

  var rows = [
    [6, 180, "fbfd7e47c319d4493bc25f0c18b3961bf5fd3122", "arl-review-b06-world-feed", "index.html"],
    [7, 397, "9e4f3fa9f7e9b398abf6a4e87b3f2c95eb248802", "arl-review-b07-personal-meaning-map", "ux.html"],
    [8, 398, "72b478a5f51f76522a689dfd80321afb75b866ee", "arl-review-b08-family-newspaper", "ux.html"],
    [9, 399, "26bdf6e5c8d44921cecedafa3a8568ceb81ebf72", "arl-review-b09-personalized-childrens-story", "ux.html"],
    [10, 400, "ea40906005366b6356904ad10a93981d823b0f63", "arl-review-b10-fan-magazine", "ux.html"],
    [11, 401, "282cd9757d820ba3c496a083c1bea72fd18f1045", "arl-review-b11-language-learning-magazine", "ux.html"],
    [12, 402, "ac70446ace1bbba3ab02a49c637dcd205add93dc", "arl-review-b12-creator-mini-media", "ux.html"],
    [15, 403, "8b490afaa3808860c05dc6f0aa4e18d4ae26b1e0", "arl-review-b15-global-ai-newsroom", "ux.html"],
    [16, 404, "8f4db08b6d908fa073716a1e48bceb28fdafa91f", "arl-review-b16-personal-sports", "ux.html"],
    [17, 405, "fecfb4ce306870b6e035a4e425c7e9c2e86b326c", "arl-review-b17-local-shop-magazine", "ux.html"],
    [18, 406, "2014020c65f80d206520f14bcc10190850eafa7b", "arl-review-b18-personal-audio-channel", "ux.html"],
    [19, 407, "33b1f30b54d23a91ed6f0a257977741ddf8cbace", "arl-review-b19-personal-memory-book", "ux.html"],
    [20, 408, "55ba9e9b4d63494428addf13e644b57581228aeb", "arl-review-b20-personal-memory-novel", "ux.html"],
    [21, 409, "5f18d9a727c9fe4e1ea492657dfd72189b3f2a73", "arl-review-b21-founder-strategy-letter", "ux.html"],
    [22, 410, "9e42eb6641fa8f1d662db263a00e27e2597ace4e", "arl-review-b22-personal-media-studio", "ux.html"],
    [32, 354, "73ec4718d0835248ab20d56bc68f3956536112b4", "arl-review-b32-ai-skill-studio", "index.html"],
    [33, 411, "c034ccae74d038bb3c5517c62e3c290db5bffc2a", "arl-review-b33-research-memory", "ux.html"],
    [34, 412, "4e77ce30ffc266997ba26fa55fd835c6fca32c85", "arl-review-b34-ai-dubbing-studio", "ux.html"],
    [35, 370, "1bc3469baae6ac7d4a1ff362a4a2b4b0af8079d2", "arl-review-b35-ai-media-education-dx", "index.html"],
    [36, 413, "6d0e904b33b68754b61b45568389c7a67b7124eb", "arl-review-b36-ai-women-safety", "ux.html"],
    [37, 414, "03d43309500aa8be07204fa0e6d6eaf602bbc23d", "arl-review-b37-ai-safe-route", "ux.html"],
    [38, 415, "d24aeb46cc74d5b7c9fa70f270345d92c133b000", "arl-review-b38-ai-exercise-coach", "ux.html"],
    [39, 416, "f62149fee46dc6bb7c9a26a2c20850b925342d43", "arl-review-b39-112-real-time-interpretation", "ux.html"],
    [40, 417, "82e71599ef539443a6a97fb97d038bc962b660cd", "arl-review-b40-emergency-urgency-ai", "ux.html"],
    [41, 418, "e59e82204be94f2f0c49bb9fce01a9c81711ed5e", "arl-review-b41-foreign-emergency-assistant", "ux.html"],
    [42, 419, "04789d43cf99c94a9c4a3a4c39f4c501c74c128d", "arl-review-b42-ai-development-control-tower", "ux.html"],
    [43, 420, "2cb76c6a7e27b2d7c74c75113ec24ecd4164978f", "arl-review-b43-ai-software-factory", "ux.html"],
    [45, 421, "b649a824839003145090fe870ded899d551d2733", "arl-review-b45-ai-content-engine", "ux.html"],
    [46, 422, "2747d64c2387bb6f76dda6e3c619604150d7dd21", "arl-review-b46-ai-personalization-engine", "ux.html"],
    [47, 423, "744a0c9ee66da73e774c4fa24fe12a5bad428b80", "arl-review-b47-real-time-feedback-engine", "ux.html"],
    [48, 424, "3e662d330a8b30383d4bfc1f8b0319a3e9e2382e", "arl-review-b48-ai-verification-engine", "ux.html"],
    [49, 425, "84d24d3665e91413f36822697d6cd7905035781e", "arl-review-b49-public-data-connector-hub", "ux.html"],
    [51, 426, "1accf2929dac862233434aed3b512335b37a55c3", "arl-review-b51-ai-workflow-marketplace", "ux.html"],
    [52, 427, "19e78810554e5680f925af8c807254b5ea7baba1", "arl-review-b52-scheduled-agent-operations", "ux.html"],
    [53, 428, "b4e8f962e51dd298174d0a070dcfb5759f9935c6", "arl-review-b53-embedded-ai-sdk", "ux.html"],
    [55, 429, "3e3eb0aff6eeb198b342be59b312dd265c3ced55", "arl-review-b55-local-ai-fleet", "ux.html"],
    [57, 430, "930a8dc4c2d13c2537c723ee76eec8217983d8e3", "arl-review-b57-classic-literature-translation", "ux.html"],
    [58, 431, "135a0cd0901ca132346ad2d1e1537d1c6fef8444", "arl-review-b58-personal-writing-voice", "ux.html"],
    [59, 392, "f327093a445086d4efb79452b1bc62ba53ff8a9b", "arl-review-b59-living-archive", "index.html"],
  ];

  var verifiedUrls = {
    6: "https://arl-review-b06-world-feed.pages.dev/index.html",
    7: "https://arl-review-b07-personal-meaning-map.pages.dev/ux.html",
    8: "https://arl-review-b08-family-newspaper.pages.dev/ux.html",
    9: "https://arl-review-b09-personalized-childrens-story.pages.dev/ux.html",
    10: "https://arl-review-b10-fan-magazine.pages.dev/ux.html",
    11: "https://arl-review-b11-language-learning-magazine.pages.dev/ux.html",
    12: "https://arl-review-b12-creator-mini-media.pages.dev/ux.html",
    15: "https://arl-review-b15-global-ai-newsroom.pages.dev/ux.html",
    16: "https://arl-review-b16-personal-sports.pages.dev/ux.html",
    17: "https://arl-review-b17-local-shop-magazine.pages.dev/ux.html",
    18: "https://arl-review-b18-personal-audio-channel.pages.dev/ux.html",
    19: "https://arl-review-b19-personal-memory-book.pages.dev/ux.html",
    20: "https://arl-review-b20-personal-memory-novel.pages.dev/ux.html",
    21: "https://arl-review-b21-founder-strategy-letter.pages.dev/ux.html",
    22: "https://arl-review-b22-personal-media-studio.pages.dev/ux.html",
    33: "https://arl-review-b33-research-memory.pages.dev/ux.html",
    34: "https://arl-review-b34-ai-dubbing-studio.pages.dev/ux.html",
    36: "https://arl-review-b36-ai-women-safety.pages.dev/ux.html",
    37: "https://arl-review-b37-ai-safe-route.pages.dev/ux.html",
    38: "https://arl-review-b38-ai-exercise-coach.pages.dev/ux.html",
    39: "https://arl-review-b39-112-real-time-interpretation.pages.dev/ux.html",
    40: "https://arl-review-b40-emergency-urgency-ai.pages.dev/ux.html",
    41: "https://arl-review-b41-foreign-emergency-assistant.pages.dev/ux.html",
    42: "https://arl-review-b42-ai-development-control-tower.pages.dev/ux.html",
    43: "https://arl-review-b43-ai-software-factory.pages.dev/ux.html",
    45: "https://arl-review-b45-ai-content-engine.pages.dev/ux.html",
    46: "https://arl-review-b46-ai-personalization-engine.pages.dev/ux.html",
    47: "https://arl-review-b47-real-time-feedback-engine.pages.dev/ux.html",
    48: "https://arl-review-b48-ai-verification-engine.pages.dev/ux.html",
    49: "https://arl-review-b49-public-data-connector-hub.pages.dev/ux.html",
    51: "https://arl-review-b51-ai-workflow-marketplace.pages.dev/ux.html",
    52: "https://arl-review-b52-scheduled-agent-operations.pages.dev/ux.html",
    53: "https://arl-review-b53-embedded-ai-sdk.pages.dev/ux.html",
    55: "https://arl-review-b55-local-ai-fleet.pages.dev/ux.html",
    57: "https://arl-review-b57-classic-literature-translation.pages.dev/ux.html",
    58: "https://arl-review-b58-personal-writing-voice.pages.dev/ux.html",
  };

  var map = {};
  rows.forEach(function (row) {
    var number = row[0];
    var project = row[3];
    var entry = row[4];
    var verified = false;
    if (Object.prototype.hasOwnProperty.call(verifiedUrls, number)) {
      verified = true;
    }
    map[number] = {
      kind: "web-review",
      status: verified ? VERIFIED : PENDING,
      pr: row[1],
      exactHead: row[2],
      project: project,
      entry: entry,
      plannedUrl: "https://" + project + ".pages.dev/" + entry,
      surfaceUrl: verified ? verifiedUrls[number] : null,
    };
  });

  map[54] = {
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
    } else if (map[business.number].status === VERIFIED) {
      business.surfaceUrl = map[business.number].surfaceUrl;
    }
  });
})();
