import ReactMarkdown, { type Components } from "react-markdown";

// Chat bubbles, not documents — every block element loses its default
// margin except the gap between siblings, so a one-line reply renders as
// one line instead of picking up a paragraph's built-in spacing.
const COMPONENTS: Components = {
  p: ({ children }) => <p className="[&:not(:last-child)]:mb-2">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-5 [&:not(:last-child)]:mb-2">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5 [&:not(:last-child)]:mb-2">{children}</ol>,
  li: ({ children }) => <li className="[&:not(:last-child)]:mb-0.5">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  // Fenced blocks carry a `language-*` className on `code`; inline code
  // doesn't. `pre` below owns the block's background/scroll — styling it
  // again here would double up.
  code: ({ children, className }) =>
    /language-/.test(className ?? "") ? (
      <code className={className}>{children}</code>
    ) : (
      <code className="rounded bg-black/10 px-1 py-0.5 font-mono text-[0.85em] dark:bg-white/10">
        {children}
      </code>
    ),
  // A long unwrapped line (a URL, an unbroken identifier) must scroll
  // inside the bubble, never push the bubble wider than its max-width.
  pre: ({ children }) => (
    <pre className="max-w-full overflow-x-auto rounded bg-black/10 p-2 text-xs [&:not(:last-child)]:mb-2 dark:bg-white/10">
      {children}
    </pre>
  ),
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="underline underline-offset-2">
      {children}
    </a>
  ),
};

function MarkdownMessage({ text }: { text: string }) {
  return <ReactMarkdown components={COMPONENTS}>{text}</ReactMarkdown>;
}

export { MarkdownMessage };
