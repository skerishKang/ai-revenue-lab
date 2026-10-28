/**
 * B64's ads.txt (#6001, D16).
 *
 * ayeT-Studios publishes the exact lines its checker expects for a placement and
 * re-reads the file within 24 hours, so the body below is reproduced verbatim
 * from the placement's Ads.txt tab — including the comment line and the trailing
 * blank line. The first line really does end in a space.
 *
 * ads.txt is a public, unauthenticated file by design: it names the seller, not
 * a credential. Nothing here may be treated as secret, and the placement id is
 * deliberately visible because the publisher's own check depends on it.
 */
export const B64_ADS_TXT_PATH = '/ads.txt';

export const B64_AYET_ADS_TXT_LINES: readonly string[] = Object.freeze([
  '# AYET-STUDIOS ',
  'ayetstudios.com, AYETSTUDIOS, DIRECT',
  'ayetstudios.com, PL-25819, DIRECT',
  '',
]);

export const B64_AYET_ADS_TXT: string = `${B64_AYET_ADS_TXT_LINES.join('\n')}\n`;
