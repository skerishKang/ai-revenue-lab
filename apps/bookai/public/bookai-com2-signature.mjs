// BookAI / COM2 records protocol v1. Keep its public path restrictions unchanged.
import {com2SignedHeaders} from './com2-hmac.mjs';
const validPath = path => typeof path === 'string' && (path === '/api/bookai/records' || path.startsWith('/api/bookai/records?'));
export async function bookaiSignedHeaders(options) {
  if (!validPath(options.path)) throw new Error('invalid_request');
  return com2SignedHeaders(options);
}
