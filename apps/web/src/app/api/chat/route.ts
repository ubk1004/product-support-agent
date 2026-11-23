import { apiBaseUrl } from "@/lib/coverage";

const MAX_BODY_CHARS = 12_000;
const MAX_MESSAGE_CHARS = 2_000;

type ChatRequest = {
  message: string;
  product_id?: string;
};

type ChatError =
  | "invalid_request"
  | "uncovered_product"
  | "service_unavailable"
  | "request_failed";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isChatRequest(value: unknown): value is ChatRequest {
  if (
    !isRecord(value) ||
    Object.keys(value).some((key) => !["message", "product_id"].includes(key))
  ) {
    return false;
  }
  if (
    typeof value.message !== "string" ||
    value.message.trim().length === 0 ||
    value.message.length > MAX_MESSAGE_CHARS
  ) {
    return false;
  }
  return (
    value.product_id === undefined ||
    (typeof value.product_id === "string" &&
      value.product_id.trim().length > 0 &&
      value.product_id.length <= 100)
  );
}

function isCitation(
  value: unknown,
): value is { evidence_id: string; title: string; source_url: string } {
  if (
    !isRecord(value) ||
    typeof value.evidence_id !== "string" ||
    !/^E\d+$/.test(value.evidence_id) ||
    typeof value.title !== "string" ||
    typeof value.source_url !== "string"
  ) {
    return false;
  }
  try {
    const url = new URL(value.source_url);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch {
    return false;
  }
}

function isChatResponse(value: unknown): value is {
  answer: string;
  citations: { evidence_id: string; title: string; source_url: string }[];
  grounded: boolean;
  request_id: string;
} {
  return (
    isRecord(value) &&
    typeof value.answer === "string" &&
    Array.isArray(value.citations) &&
    value.citations.length <= 20 &&
    value.citations.every(isCitation) &&
    typeof value.grounded === "boolean" &&
    value.grounded === value.citations.length > 0 &&
    typeof value.request_id === "string" &&
    value.request_id.length > 0
  );
}

function apiError(error: ChatError, status: number): Response {
  return Response.json({ error }, { status });
}

export async function POST(request: Request): Promise<Response> {
  const contentType = request.headers
    .get("content-type")
    ?.split(";")[0]
    .trim()
    .toLowerCase();
  if (contentType !== "application/json") {
    return apiError("invalid_request", 415);
  }

  const bodyText = await request.text();
  if (bodyText.length > MAX_BODY_CHARS) {
    return apiError("invalid_request", 413);
  }

  let body: unknown;
  try {
    body = JSON.parse(bodyText);
  } catch {
    return apiError("invalid_request", 400);
  }
  if (!isChatRequest(body)) {
    return apiError("invalid_request", 400);
  }

  const payload = {
    message: body.message.trim(),
    ...(body.product_id ? { product_ids: [body.product_id.trim()] } : {}),
  };

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(35_000),
    });
  } catch {
    return apiError("service_unavailable", 503);
  }

  const result: unknown = await upstream.json().catch(() => null);
  if (!upstream.ok) {
    if (
      upstream.status === 422 &&
      isRecord(result) &&
      isRecord(result.detail) &&
      result.detail.code === "uncovered_product"
    ) {
      return apiError("uncovered_product", 422);
    }
    if (upstream.status >= 500) {
      return apiError("service_unavailable", 503);
    }
    return apiError("request_failed", 400);
  }
  if (!isChatResponse(result)) {
    return apiError("service_unavailable", 502);
  }
  return Response.json(result);
}
