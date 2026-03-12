export type SourceItem = {
  type?: string | null;
  shnq_code?: string | null;
  chapter?: string | null;
  clause_number?: string | null;
  table_number?: string | null;
  title?: string | null;
  markdown?: string | null;
  html?: string | null;
  html_anchor?: string | null;
  lex_url?: string | null;
  snippet?: string | null;
  score?: number | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  question?: string;
  sources?: SourceItem[];
  tableHtml?: string;
  imageUrls?: string[];
  backendMessageId?: string;
  feedback?: "up" | "down" | null;
};

