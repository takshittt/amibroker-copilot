/** Small helpers shared by the BFF route files. */

import { serverConfig } from "./config";
import { jsonError } from "./forward";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Only ids that look like ids reach the API's paths. */
export function safeId(id: string): string | null {
  return UUID.test(id) ? id.toLowerCase() : null;
}

export function notFound(): Response {
  return jsonError(404, "not_found", "Not found.");
}

export function config() {
  return serverConfig();
}
