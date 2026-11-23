"use client";

import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

type ChatProduct = {
  product_id: string;
  product_name: string;
};

type ChatCitation = {
  evidence_id: string;
  title: string;
  source_url: string;
  product_name?: string | null;
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

type Exchange = {
  id: number;
  question: string;
  productName: string | null;
  response: ChatResponse | null;
  error: ChatError | null;
};

const MAX_HISTORY_TURNS = 8;
const MAX_HISTORY_TURN_CHARS = 4_000;

const ERROR_COPY: Record<ChatError, string> = {
  invalid_request: "Enter a question of 1 to 2,000 characters and try again.",
  uncovered_product:
    "That product's documentation is not searchable in this demo. Choose a product from the filter list.",
  service_unavailable:
    "The assistant is temporarily unavailable. Please try again in a moment.",
  request_failed: "The question could not be answered. Please try again.",
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

/** Earlier grounded turns, in the shape the API accepts. Failed and refused turns are skipped. */
function historyFrom(exchanges: Exchange[]) {
  return exchanges
    .filter((exchange) => exchange.response?.grounded)
    .flatMap((exchange) => [
      { role: "user" as const, content: exchange.question },
      {
        role: "assistant" as const,
        content: (exchange.response?.answer ?? "").slice(
          0,
          MAX_HISTORY_TURN_CHARS,
        ),
      },
    ])
    .slice(-MAX_HISTORY_TURNS);
}

function starterQuestions(products: ChatProduct[]): string[] {
  const questions = ["Which products can you answer questions about?"];
  const [first, second, third] = products;
  if (first) questions.push(`How do I install ${first.product_name}?`);
  if (second)
    questions.push(
      `What are the system requirements for ${second.product_name}?`,
    );
  if (third)
    questions.push(`What resources are available for ${third.product_name}?`);
  return questions;
}

/** Render an answer's [E1] markers as links to the matching numbered source. */
function withCitationLinks(
  text: string,
  citations: ChatCitation[],
  sourceAnchor: (evidenceId: string) => string,
): ReactNode[] {
  const known = new Set(citations.map((citation) => citation.evidence_id));
  return text.split(/(\[E\d+\])/).map((part, index) => {
    const match = /^\[(E(\d+))\]$/.exec(part);
    if (!match || !known.has(match[1])) return part;
    return (
      <a
        // biome-ignore lint/suspicious/noArrayIndexKey: split parts are positional
        key={index}
        className="citation-marker"
        href={`#${sourceAnchor(match[1])}`}
        aria-label={`Source ${match[2]}`}
      >
        [{match[2]}]
      </a>
    );
  });
}

/** Paragraphs and "- " list lines from the plain-text answer. */
function AnswerText({
  answer,
  citations,
  sourceAnchor,
}: {
  answer: string;
  citations: ChatCitation[];
  sourceAnchor: (evidenceId: string) => string;
}) {
  const blocks: ReactNode[] = [];
  let listItems: string[] = [];
  const flushList = () => {
    if (listItems.length) {
      const items = listItems;
      blocks.push(
        <ul key={`list-${blocks.length}`}>
          {items.map((item, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: answer lines are positional
            <li key={index}>
              {withCitationLinks(item, citations, sourceAnchor)}
            </li>
          ))}
        </ul>,
      );
      listItems = [];
    }
  };
  for (const rawLine of answer.split("\n")) {
    const line = rawLine.trim();
    const item = /^(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line);
    if (item) {
      listItems.push(item[1]);
    } else {
      flushList();
      if (line) {
        blocks.push(
          <p key={`p-${blocks.length}`}>
            {withCitationLinks(line, citations, sourceAnchor)}
          </p>,
        );
      }
    }
  }
  flushList();
  return <div className="chat-answer">{blocks}</div>;
}

function ExchangeView({ exchange }: { exchange: Exchange }) {
  const { response, error } = exchange;
  const sourceAnchor = (evidenceId: string) =>
    `answer-${exchange.id}-source-${evidenceId}`;
  return (
    <li className="exchange">
      <div className="message message-user">
        <p className="message-label">
          You
          {exchange.productName ? (
            <span className="message-scope"> · {exchange.productName}</span>
          ) : null}
        </p>
        <p className="message-text">{exchange.question}</p>
      </div>
      <div className="message message-assistant">
        <p className="message-label">Assistant</p>
        {error ? (
          <p className="chat-error" role="alert">
            {ERROR_COPY[error]}
          </p>
        ) : null}
        {response?.grounded ? (
          <>
            <AnswerText
              answer={response.answer}
              citations={response.citations}
              sourceAnchor={sourceAnchor}
            />
            <h3 className="sources-title">Sources</h3>
            <ol className="citation-list">
              {response.citations.map((citation) => (
                <li
                  key={citation.evidence_id}
                  id={sourceAnchor(citation.evidence_id)}
                >
                  <a
                    href={citation.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {citation.title}
                    <span className="visually-hidden">
                      {" "}
                      (opens in a new tab)
                    </span>
                  </a>
                  {citation.product_name ? (
                    <span className="citation-product">
                      {" "}
                      · {citation.product_name}
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          </>
        ) : null}
        {response && !response.grounded ? (
          <div className="no-answer">
            <p>
              I couldn’t find this in the indexed documentation, so I won’t
              guess.
            </p>
            <ul>
              <li>Name the product, or choose it in the product filter.</li>
              <li>
                Try a more specific question, such as an install step or error.
              </li>
              <li>
                Ask “Which products can you answer questions about?” to see what
                is covered.
              </li>
            </ul>
          </div>
        ) : null}
      </div>
    </li>
  );
}

export function ChatPanel({ products }: { products: ChatProduct[] }) {
  const questionId = useId();
  const productId = useId();
  const hintId = useId();
  const startersId = useId();
  const [question, setQuestion] = useState("");
  const [selectedProduct, setSelectedProduct] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const nextId = useRef(1);
  const threadEnd = useRef<HTMLDivElement>(null);
  const questionInput = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!loading) return;
    setElapsed(0);
    const timer = setInterval(() => setElapsed((value) => value + 1), 1_000);
    return () => clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    if (exchanges.length || loading) {
      threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [exchanges, loading]);

  async function ask(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    const product = products.find(
      (item) => item.product_id === selectedProduct,
    );
    const id = nextId.current++;
    const history = historyFrom(exchanges);
    setQuestion("");
    setLoading(true);
    let response: ChatResponse | null = null;
    let error: ChatError | null = null;
    try {
      const result = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          ...(product ? { product_id: product.product_id } : {}),
          ...(history.length ? { history } : {}),
        }),
      });
      const body: unknown = await result.json().catch(() => null);
      if (!result.ok) {
        error =
          typeof body === "object" &&
          body !== null &&
          "error" in body &&
          isChatError(body.error)
            ? body.error
            : "service_unavailable";
      } else if (isChatResponse(body)) {
        response = body;
      } else {
        error = "service_unavailable";
      }
    } catch {
      error = "service_unavailable";
    } finally {
      setExchanges((current) => [
        ...current,
        {
          id,
          question: trimmed,
          productName: product?.product_name ?? null,
          response,
          error,
        },
      ]);
      setLoading(false);
      questionInput.current?.focus();
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function resetConversation() {
    setExchanges([]);
    setQuestion("");
    questionInput.current?.focus();
  }

  return (
    <section className="chat-panel" aria-labelledby="chat-title">
      <div className="chat-heading">
        <h2 id="chat-title">Ask about supported products</h2>
        {exchanges.length ? (
          <button
            type="button"
            className="secondary-button"
            onClick={resetConversation}
            disabled={loading}
          >
            New conversation
          </button>
        ) : null}
      </div>
      <p className="chat-intro">
        Answers come only from indexed public documentation for{" "}
        {products.length} demo products, with a numbered source for every claim.
        The conversation is kept in this browser tab only.
      </p>

      {exchanges.length === 0 && !loading ? (
        <div className="starters">
          <p className="starters-title" id={startersId}>
            Try asking
          </p>
          <ul aria-labelledby={startersId}>
            {starterQuestions(products).map((starter) => (
              <li key={starter}>
                <button
                  type="button"
                  className="starter-button"
                  onClick={() => void ask(starter)}
                >
                  {starter}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="chat-thread" aria-live="polite" aria-busy={loading}>
        {exchanges.length ? (
          <ol className="exchange-list" aria-label="Conversation">
            {exchanges.map((exchange) => (
              <ExchangeView key={exchange.id} exchange={exchange} />
            ))}
          </ol>
        ) : null}
        {loading ? (
          <p className="chat-loading" role="status">
            <span className="loading-dot" aria-hidden="true" />
            Searching the documentation
            {elapsed >= 3 ? ` (${elapsed}s, answers usually take 5–20s)` : "…"}
          </p>
        ) : null}
        <div ref={threadEnd} />
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        <label htmlFor={questionId}>
          {exchanges.length ? "Follow-up question" : "Your question"}
        </label>
        <textarea
          id={questionId}
          ref={questionInput}
          name="question"
          rows={3}
          maxLength={2_000}
          required
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={handleKeyDown}
          aria-describedby={hintId}
          placeholder="For example: How do I install iPrint on Linux?"
        />
        <p className="field-hint" id={hintId}>
          Press Enter to send, Shift+Enter for a new line.
        </p>
        <div className="chat-controls">
          <div className="product-filter">
            <label htmlFor={productId}>Limit to product (optional)</label>
            <select
              id={productId}
              name="product"
              value={selectedProduct}
              onChange={(event) => setSelectedProduct(event.target.value)}
            >
              <option value="">
                All {products.length} searchable products
              </option>
              {products.map((product) => (
                <option key={product.product_id} value={product.product_id}>
                  {product.product_name}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={loading || !question.trim()}>
            {loading ? "Answering…" : "Ask"}
          </button>
        </div>
      </form>
    </section>
  );
}
