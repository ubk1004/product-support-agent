// Server-side only: imported by Server Components, never by Client Components.
export type CoverageStatus =
  | "indexed"
  | "pending"
  | "unavailable"
  | "excluded"
  | "no_public_source";

export interface ProductCoverage {
  product_id: string;
  product_name: string;
  status: CoverageStatus;
  reason_category: string | null;
  source_host: string | null;
  pages_indexed: number;
  last_indexed_at: string | null;
}

export interface CoverageReport {
  manifest_version: string;
  source_map_version: string;
  source_map_matches_manifest: boolean;
  state_available: boolean;
  retrieval_enabled: boolean;
  summary: {
    manifest_products: number;
    products_with_sources: number;
    products_indexed: number;
    pages_indexed: number;
  };
  products: ProductCoverage[];
}

export type CoverageResult =
  | { ok: true; report: CoverageReport }
  | { ok: false; reason: "unreachable" | "unavailable" | "invalid" };

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 5_000;
const STATUSES = new Set<CoverageStatus>([
  "indexed",
  "pending",
  "unavailable",
  "excluded",
  "no_public_source",
]);

export function apiBaseUrl(): string {
  const configured = process.env.PRODUCT_SUPPORT_API_BASE_URL?.trim();
  const base = configured || DEFAULT_API_BASE_URL;
  const url = new URL(base);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("PRODUCT_SUPPORT_API_BASE_URL must be an http(s) URL");
  }
  return url.toString().replace(/\/$/, "");
}

function isCoverageReport(value: unknown): value is CoverageReport {
  if (typeof value !== "object" || value === null) return false;
  const report = value as Partial<CoverageReport>;
  return (
    typeof report.manifest_version === "string" &&
    typeof report.summary === "object" &&
    report.summary !== null &&
    Array.isArray(report.products) &&
    report.products.every(
      (product) =>
        typeof product?.product_id === "string" &&
        typeof product.product_name === "string" &&
        STATUSES.has(product.status),
    )
  );
}

/** Fetch product coverage from the API on the server. The browser never calls the API. */
export async function getCoverage(): Promise<CoverageResult> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}/catalog/coverage`, {
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    return { ok: false, reason: "unreachable" };
  }
  if (!response.ok) {
    return { ok: false, reason: "unavailable" };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!isCoverageReport(payload)) {
    return { ok: false, reason: "invalid" };
  }
  return { ok: true, report: payload };
}
