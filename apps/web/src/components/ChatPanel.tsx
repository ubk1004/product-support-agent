"use client";

import { type FormEvent, useId, useState } from "react";

type ChatProduct = {
  product_id: string;
  product_name: string;
  status: string;
};

type ChatCitation = {
  evidence_id: string;
  title: string;
  source_url: string;
};

type ChatResponse = {
  answer: string;
  citations: ChatCitation[];
  grounded: boolean;
  request_id: string;
};

type ChatError =
  | "invalid_request"
  | "uncovered_product"
  | "service_unavailable"
  | "request_failed";

const ERROR_COPY: Record<ChatError, string> = {
  invalid_request: "Enter a question of 1 to 2,000 characters and try again.",
  uncovered_product: "This product is outside the searchable demo catalog.",
  service_unavailable:
    "The chat service is temporarily unavailable. Please try again.",
  request_failed: "The chat request could not be completed.",
};

const STATUS_COPY: Record<string, string> = {
  indexed: "indexed",
  pending: "not indexed yet",
  unavailable: "source unavailable",
  excluded: "excluded",
  no_public_source: "no approved public source",
};

function isChatError(value: unknown): value is ChatError {
  return (
    value === "invalid_request" ||
    value === "uncovered_product" ||
    value === "service_unavailable" ||
    value === "request_failed"
  );
}

function isCitation(value: unknown): value is ChatCitation {
  return (
    typeof value === "object" &&
    value !== null &&
    "evidence_id" in value &&
    typeof value.evidence_id === "string" &&
    "title" in value &&
    typeof value.title === "string" &&
    "source_url" in value &&
    typeof value.source_url === "string"
  );
}

function isChatResponse(value: unknown): value is ChatResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    "answer" in value &&
    typeof value.answer === "string" &&
    "citations" in value &&
    Array.isArray(value.citations) &&
    value.citations.every(isCitation) &&
    "grounded" in value &&
    typeof value.grounded === "boolean" &&
    "request_id" in value &&
    typeof value.request_id === "string"
  );
}

export function ChatPanel({ products }: { products: ChatProduct[] }) {
  const questionId = useId();
  const productId = useId();
  const [question, setQuestion] = useState("");
  const [selectedProduct, setSelectedProduct] = useState("");
  const [answer, setAnswer] = useState<ChatResponse | null>(null);
  const [error, setError] = useState<ChatError | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAnswer(null);
    setError(null);
    setLoading(true);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: question,
          ...(selectedProduct ? { product_id: selectedProduct } : {}),
        }),
      });
      const result: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setError(
          typeof result === "object" &&
            result !== null &&
            "error" in result &&
            isChatError(result.error)
            ? result.error
            : "service_unavailable",
        );
      } else if (isChatResponse(result)) {
        setAnswer(result);
      } else {
        setError("service_unavailable");
      }
    } catch {
      setError("service_unavailable");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="chat-panel" aria-labelledby="chat-title">
      <h2 id="chat-title">Ask the documentation</h2>
      <p className="chat-intro">
        Answers use indexed public documentation from this demo catalog. Sources
        are linked directly from retrieved evidence.
      </p>
      <form className="chat-form" onSubmit={handleSubmit}>
        <label htmlFor={questionId}>Your question</label>
        <textarea
          id={questionId}
          name="question"
          rows={4}
          maxLength={2_000}
          required
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What would you like to know?"
        />
        <label htmlFor={productId}>Product filter (optional)</label>
        <select
          id={productId}
          name="product"
          value={selectedProduct}
          onChange={(event) => setSelectedProduct(event.target.value)}
        >
          <option value="">All searchable products</option>
          {products.map((product) => (
            <option key={product.product_id} value={product.product_id}>
              {product.product_name} (
              {STATUS_COPY[product.status] ?? product.status})
            </option>
          ))}
        </select>
        <button type="submit" disabled={loading}>
          {loading ? "Searching..." : "Ask"}
        </button>
      </form>
      <div className="chat-result" aria-live="polite" aria-busy={loading}>
        {loading ? (
          <p role="status">Searching approved documentation...</p>
        ) : null}
        {error ? (
          <p className="chat-error" role="alert">
            {ERROR_COPY[error]}
          </p>
        ) : null}
        {answer ? (
          <>
            <p className="chat-answer">{answer.answer}</p>
            {answer.citations.length > 0 ? (
              <ol className="citation-list" aria-label="Sources">
                {answer.citations.map((citation) => (
                  <li key={citation.evidence_id}>
                    <a
                      href={citation.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {citation.title}
                    </a>
                  </li>
                ))}
              </ol>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
