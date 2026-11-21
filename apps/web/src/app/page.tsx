import Link from "next/link";

export default function HomePage() {
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
          A local-first foundation for product support answers that will be
          grounded in approved public documentation.
        </p>

        <div className="status-panel" role="status">
          <span className="status-dot" aria-hidden="true" />
          <div>
            <p className="status-title">Foundation in progress</p>
            <p className="status-copy">
              Chat and product data are not enabled in this phase.
            </p>
          </div>
        </div>
      </section>

      <footer className="site-footer">
        <p>
          Demo coverage will be clearly identified when product data is
          available.
        </p>
      </footer>
    </main>
  );
}
