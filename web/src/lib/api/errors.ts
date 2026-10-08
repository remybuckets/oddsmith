import { API_ERROR_CODES, type ApiErrorCode } from "./types";

export const INTERNAL_MESSAGE = "Something went wrong on our side. Please try again in a moment.";
export const CONNECTION_MESSAGE = "We couldn't reach Oddsmith. Check your connection and try again.";

/** Status used when the request never got a response. */
const NO_RESPONSE_STATUS = 0;

interface ApiRequestErrorInit {
  code: ApiErrorCode;
  message: string;
  status: number;
  retryAt?: string | null;
  cause?: unknown;
}

/** A failed API call. `message` is user-friendly and shown as-is (contracts/openapi.yaml). */
export class ApiRequestError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly retryAt: string | null;

  constructor({ code, message, status, retryAt = null, cause }: ApiRequestErrorInit) {
    super(message, { cause });
    this.name = "ApiRequestError";
    this.code = code;
    this.status = status;
    this.retryAt = retryAt;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isApiErrorCode(value: unknown): value is ApiErrorCode {
  return API_ERROR_CODES.some((code) => code === value);
}

/** Reads an error envelope; anything malformed becomes an internal error. */
export function fromErrorResponse(status: number, body: unknown): ApiRequestError {
  const error = isRecord(body) ? body.error : undefined;
  if (!isRecord(error) || !isApiErrorCode(error.code) || typeof error.message !== "string") {
    return new ApiRequestError({ code: "internal", message: INTERNAL_MESSAGE, status });
  }
  return new ApiRequestError({
    code: error.code,
    message: error.message,
    status,
    retryAt: typeof error.retry_at === "string" ? error.retry_at : null,
  });
}

/** Any thrown value as an ApiRequestError; anything else counts as a failed connection. */
export function asApiError(cause: unknown): ApiRequestError {
  return cause instanceof ApiRequestError ? cause : fromNetworkFailure(cause);
}

export function fromNetworkFailure(cause: unknown): ApiRequestError {
  return new ApiRequestError({
    code: "internal",
    message: CONNECTION_MESSAGE,
    status: NO_RESPONSE_STATUS,
    cause,
  });
}
