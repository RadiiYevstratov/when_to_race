import Link from "next/link";

/**
 * The 404 status is the real signal; this is belt and braces for anything that
 * indexes on content rather than status code.
 */
export const metadata = {
  title: "Not found",
  robots: { index: false, follow: true },
};

export default function NotFound() {
  return (
    <div className="border border-dashed border-rule px-4 py-16 text-center">
      <p className="font-mono text-sm text-ink-muted">No such weekend on the board.</p>
      <p className="mt-2 text-xs text-ink-faint">
        The round may have been renamed, or the season may not be published yet.
      </p>
      <Link href="/" className="mt-6 inline-block border-b border-ink text-sm">
        Back to what&rsquo;s on
      </Link>
    </div>
  );
}
