export const categoriesSeed = [
  { id: "cat-shnq", code: "SHNQ", name: "Qurilish normalari" },
  { id: "cat-qmq", code: "QMQ", name: "Qurilish me'yorlari" },
  { id: "cat-san", code: "SanQvaN", name: "Sanitar me'yorlar" },
];

export const documentsSeed = [
  {
    id: "doc-1",
    category_code: "SHNQ",
    title: "Yong'in xavfsizligi",
    code: "SHNQ 2.08.02-09",
    lex_url: "https://lex.uz",
    created_at: new Date().toISOString(),
    pipeline: {
      doc_to_html: 100,
      html_chunking: 100,
      row_embedding: 70,
      image_embedding: 40,
      finished: false,
      state: "processing",
    },
  },
  {
    id: "doc-2",
    category_code: "QMQ",
    title: "Suv ta'minoti talablari",
    code: "QMQ 3.01.04",
    lex_url: "",
    created_at: new Date().toISOString(),
    pipeline: {
      doc_to_html: 100,
      html_chunking: 100,
      row_embedding: 100,
      image_embedding: 100,
      finished: true,
      state: "done",
    },
  },
];

export const registrySeed = {
  documents: 2,
  chapters: 18,
  clauses: 436,
  norm_tables: 52,
  norm_table_rows: 308,
  norm_table_cells: 1534,
  norm_images: 67,
  clause_embeddings: 420,
  table_row_embeddings: 267,
  image_embeddings: 41,
  question_answers: 132,
};