import { useEffect, useState } from "react";
import SourceRow from "./SourceRow";
import type { ChatMessage as ChatMessageType } from "./types";
import { useI18n } from "../providers";

type ActionIconName = "bot" | "copy" | "check" | "word" | "pdf" | "like" | "dislike";

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function ActionIcon({ name, className = "" }: { name: ActionIconName; className?: string }) {
  const classes = `h-[18px] w-[18px] ${className}`.trim();

  switch (name) {
    case "bot":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={classes}>
          <path d="M12 4V2" strokeLinecap="round" />
          <rect x="5" y="7" width="14" height="11" rx="3" />
          <path d="M9 18v2m6-2v2M9 11h.01M15 11h.01" strokeLinecap="round" />
          <path d="M8 14h8" strokeLinecap="round" />
        </svg>
      );
    case "copy":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={classes}>
          <rect x="9" y="9" width="11" height="11" rx="2.5" />
          <path d="M15 9V6.5A2.5 2.5 0 0 0 12.5 4H6.5A2.5 2.5 0 0 0 4 6.5v6A2.5 2.5 0 0 0 6.5 15H9" strokeLinecap="round" />
        </svg>
      );
    case "check":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={classes}>
          <path d="m5 12 4.2 4.2L19 6.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "word":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={classes}>
          <path d="M14 3H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7z" />
          <path d="M14 3v4h4" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M9 11h6M9 15h6M9 7.5h2.5" strokeLinecap="round" />
        </svg>
      );
    case "pdf":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={classes}>
          <path d="M14 3H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7z" />
          <path d="M14 3v4h4" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M8.8 16.7h1.3c.9 0 1.5-.6 1.5-1.4 0-.9-.6-1.4-1.5-1.4H8.8zm4 0v-4.2h1.1a1.8 1.8 0 0 1 0 3.6zm4 0h-2.2v-4.2h2.3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "like":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={classes}>
          <path d="M7 10v10" strokeLinecap="round" />
          <path d="M12 10V6.8c0-1.2.8-2.3 2-2.6l.4-.1c.9-.2 1.8.4 1.9 1.4.1.7.1 1.4-.1 2L15 10h4a2 2 0 0 1 2 2.4l-1 5.2a3 3 0 0 1-2.9 2.4H7a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2z" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "dislike":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={classes}>
          <path d="M17 14V4" strokeLinecap="round" />
          <path d="M12 14v3.2c0 1.2-.8 2.3-2 2.6l-.4.1c-.9.2-1.8-.4-1.9-1.4-.1-.7-.1-1.4.1-2L9 14H5a2 2 0 0 1-2-2.4l1-5.2A3 3 0 0 1 6.9 4H17a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2z" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
  }

  return null;
}

type ChatMessageProps = {
  message: ChatMessageType;
  onFeedback?: (messageId: string, vote: "up" | "down") => void;
  onExport?: (message: ChatMessageType, format: "word" | "pdf") => Promise<void> | void;
};

export default function ChatMessage({ message, onFeedback, onExport }: ChatMessageProps) {
  const { t } = useI18n();
  const [isDarkTheme, setIsDarkTheme] = useState(false);
  const [copied, setCopied] = useState(false);
  const [busyAction, setBusyAction] = useState<"word" | "pdf" | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    const syncTheme = () => setIsDarkTheme(root.classList.contains("dark"));
    syncTheme();

    const observer = new MutationObserver(syncTheme);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!copied) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timeoutId);
  }, [copied]);

  if (message.role === "user") {
    return (
      <div className="flex justify-end items-start">
        <div className="w-fit max-w-[70%] break-words rounded-2xl rounded-br-md bg-blue-600 px-4 py-3 text-sm text-white shadow-sm">
          {message.content}
        </div>
      </div>
    );
  }

  if (message.role === "error") {
    return (
      <div className="flex justify-start items-start">
        <div className="w-fit max-w-[70%] break-words rounded-2xl rounded-bl-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {message.content}
        </div>
      </div>
    );
  }

  const firstSource = message.sources?.[0];
  const tableSource = message.sources?.find((item) => item.type === "table");
  const tableHtml = message.tableHtml || tableSource?.html || firstSource?.html;
  const imageUrls = (message.imageUrls || [])
    .map((url) => url.trim())
    .filter((url) => url.length > 0);
  const hasRichContent = Boolean(tableHtml) || imageUrls.length > 0;
  const tableTitle =
    tableSource?.table_number && tableSource?.shnq_code
      ? `${tableSource.shnq_code} - ${tableSource.table_number}-jadval`
      : undefined;
  const summaryMatch = message.content.match(/(Qisqa qilib aytganda:)([\s\S]*)/i);
  const detailText = summaryMatch
    ? message.content.slice(0, summaryMatch.index).trim()
    : message.content;
  const summaryLabel = summaryMatch?.[1] || "";
  const summaryText = summaryMatch?.[2]?.trim() || "";
  const summaryParts = summaryText.split(/(\d+(?:[.,]\d+)?%?)/g);
  const renderedTableHtml = tableHtml
    ? `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      html, body {
        margin: 0;
        padding: 0;
        background: ${isDarkTheme ? "#020617" : "#ffffff"};
        color: ${isDarkTheme ? "#e2e8f0" : "#111827"};
      }
      body {
        padding: 10px;
        font-family: "Times New Roman", serif;
      }
      * {
        box-sizing: border-box;
      }
      body, table, thead, tbody, tr, th, td, div, span, p, b, strong, em, i, font {
        color: ${isDarkTheme ? "#e2e8f0" : "#111827"} !important;
      }
      table {
        width: 100% !important;
        max-width: 100% !important;
        border-collapse: collapse;
        table-layout: auto;
        background: ${isDarkTheme ? "#0f172a" : "#ffffff"} !important;
      }
      th, td {
        max-width: none !important;
        white-space: normal;
        word-break: break-word;
        color: inherit !important;
        border-color: ${isDarkTheme ? "#334155" : "#1f2937"} !important;
        background: transparent !important;
      }
      img {
        max-width: 100% !important;
        height: auto !important;
      }
      a {
        color: ${isDarkTheme ? "#93c5fd" : "#1d4ed8"} !important;
      }
    </style>
  </head>
  <body>${tableHtml}</body>
</html>`
    : undefined;

  const handleCopy = async () => {
    try {
      await copyText(message.content || "");
      setCopied(true);
    } catch (error) {
      console.error("Copy failed", error);
    }
  };

  const handleExport = async (format: "word" | "pdf") => {
    if (!onExport) {
      return;
    }
    setBusyAction(format);
    try {
      await onExport(message, format);
    } catch (error) {
      console.error("Export failed", error);
    } finally {
      setBusyAction(null);
    }
  };

  const baseActionButton =
    "group inline-flex h-12 w-12 items-center justify-center rounded-[18px] border bg-white transition-all duration-200 hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-950";

  return (
    <div className="flex w-full items-start gap-4">
      <div className="mt-1 flex size-8 items-center justify-center rounded-xl border border-blue-100 bg-blue-50 text-blue-600 shadow-sm dark:border-blue-900/60 dark:bg-blue-950/60 dark:text-blue-300">
        <ActionIcon name="bot" />
      </div>
      <div
        className={`w-full break-words rounded-[24px] border border-slate-200/90 bg-white px-5 py-4 text-sm text-slate-800 shadow-[0_10px_28px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100 ${
          hasRichContent ? "max-w-[920px]" : "max-w-[860px]"
        }`}
      >
        <div className="leading-relaxed whitespace-pre-wrap">
          {summaryMatch ? (
            <>
              {detailText ? <div>{detailText}</div> : null}
              <div className="mt-3 rounded-md bg-slate-100 px-2 py-1 text-slate-800 dark:bg-slate-800 dark:text-slate-100">
                <span className="font-bold text-slate-900 dark:text-slate-50">{summaryLabel}</span>
                {summaryText ? " " : ""}
                {summaryParts.map((part, index) =>
                  /^\d+(?:[.,]\d+)?%?$/.test(part) ? (
                    <span key={`${part}-${index}`} className="font-semibold text-slate-900 dark:text-slate-50">
                      {part}
                    </span>
                  ) : (
                    <span key={`${part}-${index}`}>{part}</span>
                  )
                )}
              </div>
            </>
          ) : (
            message.content
          )}
        </div>
        {firstSource ? <SourceRow source={firstSource} /> : null}
        {tableHtml ? (
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-950/60">
            <div className="mb-2 text-xs font-medium text-slate-600 dark:text-slate-300">
              {tableTitle || t("chat.table.default_title", "Jadval")}
            </div>
            <iframe
              title={tableTitle || t("chat.table.iframe_title", "SHNQ jadval")}
              sandbox=""
              srcDoc={renderedTableHtml}
              className="h-[75vh] min-h-[520px] w-full rounded-md border border-slate-200 bg-white dark:border-slate-700"
            />
          </div>
        ) : null}
        {imageUrls.length > 0 ? (
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-950/60">
            <div className="mb-2 text-xs font-medium text-slate-600 dark:text-slate-300">
              {t("chat.image.default_title", "Rasm")}
            </div>
            <div className="grid grid-cols-1 gap-2">
              {imageUrls.map((url, index) => (
                <a
                  key={`${url}-${index}`}
                  href={url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="overflow-hidden rounded-md border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={url}
                    alt={t("chat.image.alt", "Rasm")}
                    loading="lazy"
                    className="h-auto max-h-[70vh] w-full object-contain"
                  />
                </a>
              ))}
            </div>
          </div>
        ) : null}
        <div className="mt-5 border-t border-slate-100 pt-4 dark:border-slate-800">
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
          <button
            type="button"
            title={copied ? t("chat.action.copied", "Nusxa olindi") : t("chat.action.copy", "Nusxa olish")}
            className={`${baseActionButton} ${
              copied
                ? "border-blue-200 bg-blue-50 text-blue-600 shadow-[0_8px_20px_rgba(37,99,235,0.12)] dark:border-blue-700/50 dark:bg-blue-900/30 dark:text-blue-300"
                : "border-slate-200 text-slate-500 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:bg-slate-900"
            }`}
            aria-label={copied ? t("chat.action.copied", "Nusxa olindi") : t("chat.action.copy", "Nusxa olish")}
            onClick={() => {
              void handleCopy();
            }}
          >
            <ActionIcon name={copied ? "check" : "copy"} className="h-5 w-5" />
          </button>
          <button
            type="button"
            title={t("chat.action.download_word", "Word yuklab olish")}
            className={`${baseActionButton} ${
              busyAction === "word"
                ? "border-blue-200 bg-blue-50 text-blue-600 shadow-[0_8px_20px_rgba(37,99,235,0.12)] dark:border-blue-700/50 dark:bg-blue-900/30 dark:text-blue-300"
                : "border-slate-200 text-blue-500 hover:border-blue-200 hover:bg-blue-50 hover:text-blue-600 dark:border-slate-700 dark:text-blue-300 dark:hover:border-blue-800 dark:hover:bg-blue-950/40"
            }`}
            aria-label={t("chat.action.download_word", "Word yuklab olish")}
            onClick={() => {
              void handleExport("word");
            }}
            disabled={busyAction !== null}
          >
            <ActionIcon name="word" className={`h-5 w-5 ${busyAction === "word" ? "animate-pulse" : ""}`} />
          </button>
          <button
            type="button"
            title={t("chat.action.download_pdf", "PDF yuklab olish")}
            className={`${baseActionButton} ${
              busyAction === "pdf"
                ? "border-rose-200 bg-rose-50 text-rose-600 shadow-[0_8px_20px_rgba(225,29,72,0.12)] dark:border-rose-700/50 dark:bg-rose-900/30 dark:text-rose-300"
                : "border-slate-200 text-rose-500 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 dark:border-slate-700 dark:text-rose-300 dark:hover:border-rose-800 dark:hover:bg-rose-950/40"
            }`}
            aria-label={t("chat.action.download_pdf", "PDF yuklab olish")}
            onClick={() => {
              void handleExport("pdf");
            }}
            disabled={busyAction !== null}
          >
            <ActionIcon name="pdf" className={`h-5 w-5 ${busyAction === "pdf" ? "animate-pulse" : ""}`} />
          </button>
          <div className="mx-1 h-8 w-px bg-slate-200 dark:bg-slate-700" />
          <button
            type="button"
            className={`${baseActionButton} ${
              message.feedback === "up"
                ? "border-emerald-200 bg-emerald-50 text-emerald-600 shadow-[0_8px_20px_rgba(5,150,105,0.12)] dark:border-emerald-700/50 dark:bg-emerald-900/30 dark:text-emerald-400"
                : "border-slate-200 text-slate-500 hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-600 dark:border-slate-700 dark:text-slate-400 dark:hover:border-emerald-800 dark:hover:bg-emerald-950/30"
            }`}
            aria-label={t("chat.feedback.like", "Foydali")}
            onClick={() => {
              onFeedback?.(message.id, "up");
            }}
          >
            <ActionIcon name="like" className="h-5 w-5" />
          </button>
          <button
            type="button"
            className={`${baseActionButton} ${
              message.feedback === "down"
                ? "border-rose-200 bg-rose-50 text-rose-600 shadow-[0_8px_20px_rgba(225,29,72,0.12)] dark:border-rose-700/50 dark:bg-rose-900/30 dark:text-rose-400"
                : "border-slate-200 text-slate-500 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 dark:border-slate-700 dark:text-slate-400 dark:hover:border-rose-800 dark:hover:bg-rose-950/30"
            }`}
            aria-label={t("chat.feedback.dislike", "Foydasiz")}
            onClick={() => {
              onFeedback?.(message.id, "down");
            }}
          >
            <ActionIcon name="dislike" className="h-5 w-5" />
          </button>
          </div>
        </div>
      </div>
    </div>
  );
}
