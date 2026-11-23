import Link from "next/link";
import { connection } from "next/server";
import { ChatPanel } from "@/components/ChatPanel";
import {
  type CoverageReport,
  type CoverageStatus,
  getCoverage,
  type ProductCoverage,
} from "@/lib/coverage";

const STATUS_LABELS: Record<CoverageStatus, string> = {
  indexed: "Documentation indexed",
  pending: "Source approved, not indexed yet",
  unavailable: "Source unavailable",
  excluded: "Source excluded",
  no_public_source: "No approved public source",
};

const UNAVAILABLE_COPY = {
  unreachable: "The coverage service could not be reached.",
  unavailable: "The coverage service reported that its data is unavailable.",
  invalid: "The coverage service returned an unexpected response.",
} as const;

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString("en-CA", { timeZone: "UTC" });
}

function CoverageSummary({ report }: { report: CoverageReport }) {
  const { summary } = report;
  return (
    <>
      <div className="status-panel" role="status">
        <span
          className={`status-dot${summary.products_indexed ? " status-dot-ok" : ""}`}
          aria-hidden="true"
        />
        <div>
          <p className="status-title">
            {summary.products_indexed} of {summary.manifest_products} demo
            products have indexed documentation
          </p>
          <p className="status-copy">
            {summary.pages_indexed} documentation pages from{" "}
            {summary.products_with_sources} products with an approved public
            source. The assistant answers only about these products; the rest of
            the sample is listed below as not covered.
          </p>
          {report.retrieval_enabled ? null : (
            <p className="status-copy">
              Search is not enabled, so these pages are stored but not yet
              searchable.
            </p>
          )}
        </div>
      </div>
      {report.state_available ? null : (
        <p className="notice" role="alert">
          Ingestion state could not be read, so indexed products cannot be
          confirmed right now.
        </p>
      )}
      {report.source_map_matches_manifest ? null : (
        <p className="notice" role="alert">
          The source list was prepared for a different product manifest version.
          Coverage may be incomplete.
        </p>
      )}
    </>
  );
}

function ProductRow({ product }: { product: ProductCoverage }) {
  return (
    <tr>
      <th scope="row">{product.product_name}</th>
      <td>
        <span className={`badge badge-${product.status}`}>
          {STATUS_LABELS[product.status]}
        </span>
        {product.reason_category ? (
          <span className="reason"> ({product.reason_category})</span>
        ) : null}
      </td>
      <td className="numeric">
        {product.status === "indexed" ? product.pages_indexed : "—"}
      </td>
      <td>{formatDate(product.last_indexed_at)}</td>
    </tr>
  );
}

function CoverageRows({
  products,
  caption,
}: {
  products: ProductCoverage[];
  caption: string;
}) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Product</th>
            <th scope="col">Coverage</th>
            <th scope="col" className="numeric">
              Pages
            </th>
            <th scope="col">Last indexed (UTC)</th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <ProductRow key={product.product_id} product={product} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CoverageTable({ report }: { report: CoverageReport }) {
  const indexed = report.products.filter(
    (product) => product.status === "indexed",
  );
  const others = report.products.filter(
    (product) => product.status !== "indexed",
  );
  const versions = `Manifest ${report.manifest_version}; source list ${report.source_map_version}.`;
  return (
    <>
      {indexed.length ? (
        <CoverageRows
          products={indexed}
          caption={`Products with indexed documentation. ${versions}`}
        />
      ) : (
        <p className="status-copy">No product has indexed documentation yet.</p>
      )}
      {others.length ? (
        <details className="coverage-others">
          <summary>
            Show the other {others.length} demo products (not searchable)
          </summary>
          <p className="status-copy">
            These products are in the demo sample, but their documentation is
            not indexed. The assistant can tell you they are in the catalog, but
            it will not answer questions about them.
          </p>
          <CoverageRows
            products={others}
            caption={`Demo products without indexed documentation. ${versions}`}
          />
        </details>
      ) : null}
    </>
  );
}

export default async function HomePage() {
  await connection();
  const result = await getCoverage();

  return (
    <main className="page-shell">
      <header className="site-header">
        <Link
          className="brand"
          href="/"
          aria-label="Product Support Agent home"
        >
          <span className="brand-mark" aria-hidden="true">
            PS
          </span>
          <span>Product Support Agent</span>
        </Link>
        <span className="environment-label">Local demo</span>
      </header>

      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">Product knowledge, carefully grounded</p>
        <h1 id="page-title">Support guidance with sources you can verify.</h1>
        <p className="intro">
          A local-first demo of product support answers grounded in approved
          public documentation. It covers a fixed sample of 100 products, and
          only some of them have documentation indexed.
        </p>
        {result.ok ? (
          <CoverageSummary report={result.report} />
        ) : (
          <p className="notice" role="alert">
            Demo coverage could not be loaded. {UNAVAILABLE_COPY[result.reason]}{" "}
            No product should be assumed to be covered.
          </p>
        )}
      </section>

      <ChatPanel
        products={
          result.ok
            ? result.report.products
                .filter((product) => product.status === "indexed")
                .map(({ product_id, product_name }) => ({
                  product_id,
                  product_name,
                }))
            : []
        }
      />

      {result.ok ? (
        <section className="coverage" aria-labelledby="coverage-title">
          <h2 id="coverage-title">Demo catalog coverage</h2>
          <p className="coverage-intro">
            This demo ingested a fixed random sample of{" "}
            {result.report.summary.manifest_products} products to avoid extra
            infrastructure and load on OpenText's sites.
          </p>
          <CoverageTable report={result.report} />
        </section>
      ) : null}

      <footer className="site-footer">
        <p>
          Coverage reflects documentation the demo has stored from approved
          public sources. Having a source does not mean every topic for that
          product is covered.
        </p>
      </footer>
    </main>
  );
}
