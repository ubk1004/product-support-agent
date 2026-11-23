import {
  type Attributes,
  type Context,
  SamplingDecision,
  type SamplingResult,
  trace,
} from "@opentelemetry/api";
import { registerOTel } from "@vercel/otel";

const HEALTH_PATH = "/api/healthz";

// The container health probe calls /api/healthz every few seconds. Its traces would bury real
// requests, so a root span for that path is dropped; everything else is sampled as usual.
const dropHealthChecks = {
  shouldSample(
    context: Context,
    _traceId: string,
    spanName: string,
    _spanKind: unknown,
    attributes: Attributes,
  ): SamplingResult {
    const isRoot = !trace.getSpanContext(context);
    const target = String(
      attributes["http.target"] ?? attributes["url.path"] ?? "",
    );
    if (
      isRoot &&
      (spanName.includes(HEALTH_PATH) || target.startsWith(HEALTH_PATH))
    ) {
      return { decision: SamplingDecision.NOT_RECORD };
    }
    return { decision: SamplingDecision.RECORD_AND_SAMPLED };
  },
  toString: () => "DropHealthChecks",
};

// Next.js calls register() once per server process. Spans are exported only when
// OTEL_EXPORTER_OTLP_ENDPOINT is set (the Aspire dashboard locally). Trace context is
// propagated only to the FastAPI service, so a chat request shows as one trace across
// Next.js and the API. Request bodies, questions, and answers are never recorded.
export function register() {
  if (!process.env.OTEL_EXPORTER_OTLP_ENDPOINT?.trim()) return;
  const apiBase = process.env.PRODUCT_SUPPORT_API_BASE_URL?.trim();
  registerOTel({
    serviceName: process.env.OTEL_SERVICE_NAME || "product-support-web",
    attributes: {
      "deployment.environment.name":
        process.env.PRODUCT_SUPPORT_ENVIRONMENT || "local",
    },
    traceSampler: dropHealthChecks,
    instrumentationConfig: {
      fetch: {
        propagateContextUrls: apiBase ? [apiBase] : [],
      },
    },
  });
}
