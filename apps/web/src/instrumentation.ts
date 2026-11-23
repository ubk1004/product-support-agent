import { registerOTel } from "@vercel/otel";

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
    instrumentationConfig: {
      fetch: {
        propagateContextUrls: apiBase ? [apiBase] : [],
      },
    },
  });
}
