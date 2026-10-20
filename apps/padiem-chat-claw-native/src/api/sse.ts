/**
 * Server-Sent Events transport for React Native.
 *
 * React Native's `fetch` has no readable response body, so a streaming answer
 * cannot be consumed through it. The native `XMLHttpRequest` however reports
 * the partial body through `responseText` while the request is still LOADING,
 * which is exactly the transport the existing PADIEM Web client uses for the
 * same `text/event-stream` contract.
 *
 * The frame grammar below is the server's own grammar
 * (`apps/padiem-chat/app/chat_routes.py::_public_sse`):
 *
 *     event: <name>\n
 *     data: <json>\n
 *     \n
 */

export interface SseEvent {
  event: string;
  data: string;
}

export interface SseRequestOptions {
  url: string;
  method?: 'POST' | 'GET';
  headers?: Record<string, string>;
  /** Already-serialized request body. */
  body?: string;
  signal?: AbortSignal;
  onEvent: (event: SseEvent) => void;
  onError: (error: Error) => void;
  onClose?: () => void;
}

export class SseHttpError extends Error {
  readonly status: number;
  readonly body: string;

  constructor(status: number, body: string) {
    super(`SSE 요청 실패 (${status})`);
    this.name = 'SseHttpError';
    this.status = status;
    this.body = body;
  }
}

/** Parse one SSE frame. Returns `null` for a frame that carries no data. */
export function parseSseFrame(frame: string): SseEvent | null {
  let event = 'message';
  const dataLines: string[] = [];

  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) {
      continue;
    }
    const separator = line.indexOf(':');
    const field = separator >= 0 ? line.slice(0, separator) : line;
    let value = separator >= 0 ? line.slice(separator + 1) : '';
    if (value.startsWith(' ')) {
      value = value.slice(1);
    }
    if (field === 'event') {
      event = value;
    } else if (field === 'data') {
      dataLines.push(value);
    }
  }

  if (dataLines.length === 0) {
    return null;
  }
  return {event, data: dataLines.join('\n')};
}

const FRAME_BOUNDARY = /\r?\n\r?\n/;

/**
 * Open one SSE request. The returned function aborts the request.
 *
 * `onEvent` is called for every complete frame. The stream ends when the
 * server closes the connection or the request is aborted.
 */
export function openSseRequest(options: SseRequestOptions): () => void {
  const {
    url,
    method = 'POST',
    headers = {},
    body,
    signal,
    onEvent,
    onError,
    onClose,
  } = options;

  const xhr = new XMLHttpRequest();
  let buffer = '';
  let consumed = 0;
  let settled = false;

  const drain = (): void => {
    const text = xhr.responseText ?? '';
    if (text.length <= consumed) {
      return;
    }
    buffer += text.slice(consumed);
    consumed = text.length;

    for (;;) {
      const boundary = FRAME_BOUNDARY.exec(buffer);
      if (!boundary || boundary.index === undefined) {
        break;
      }
      const frame = buffer.slice(0, boundary.index);
      buffer = buffer.slice(boundary.index + boundary[0].length);
      const parsed = parseSseFrame(frame);
      if (parsed) {
        onEvent(parsed);
      }
    }
  };

  const finish = (): void => {
    if (settled) {
      return;
    }
    settled = true;
    onClose?.();
  };

  const fail = (error: Error): void => {
    if (settled) {
      return;
    }
    settled = true;
    onError(error);
  };

  xhr.onreadystatechange = (): void => {
    if (xhr.readyState !== 3 && xhr.readyState !== 4) {
      return;
    }
    if (xhr.readyState === 3) {
      try {
        drain();
      } catch (error) {
        fail(error instanceof Error ? error : new Error(String(error)));
      }
      return;
    }

    // readyState 4 — the response is complete.
    try {
      drain();
    } catch (error) {
      fail(error instanceof Error ? error : new Error(String(error)));
      return;
    }

    const status = xhr.status;
    if (status >= 200 && status < 300) {
      finish();
      return;
    }
    if (status === 0) {
      // Network-level failure or an aborted request.
      if (signal?.aborted) {
        finish();
        return;
      }
      fail(new SseHttpError(0, ''));
      return;
    }

    let payload = '';
    try {
      payload = xhr.responseText ?? '';
    } catch {
      payload = '';
    }
    fail(new SseHttpError(status, payload));
  };

  xhr.onerror = (): void => {
    fail(new SseHttpError(xhr.status || 0, ''));
  };

  xhr.ontimeout = (): void => {
    fail(new SseHttpError(0, 'timeout'));
  };

  const abort = (): void => {
    try {
      xhr.abort();
    } catch {
      // already finished
    }
    finish();
  };

  if (signal) {
    if (signal.aborted) {
      abort();
      return abort;
    }
    signal.addEventListener('abort', abort);
  }

  try {
    xhr.open(method, url, true);
    for (const [name, value] of Object.entries(headers)) {
      xhr.setRequestHeader(name, value);
    }
    xhr.send(body ?? null);
  } catch (error) {
    fail(error instanceof Error ? error : new Error(String(error)));
  }

  return abort;
}
