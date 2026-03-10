"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://shnq-api.dashboard.iqmath.uz";
const AUTH_SESSION_KEY = "shnq_dashboard_static_auth";
const STATIC_LOGIN = {
  username: "tmsiti-1234",
  password: "tmsiti_1234",
};

const STATUS_ORDER = {
  queued: 0,
  processing: 1,
  done: 2,
  failed: 3,
};

const EMPTY_DASHBOARD_STATS = {
  totalDocuments: 0,
  queuedDocuments: 0,
  processingDocuments: 0,
  doneDocuments: 0,
  failedDocuments: 0,
  totalClauses: 0,
  totalTables: 0,
  totalTableRows: 0,
  clauseEmbeddings: 0,
  tableRowEmbeddings: 0,
  imageEmbeddings: 0,
  embeddingCoveragePercent: 0,
};

const EMBEDDING_TYPE_LABELS = {
  all: "Barchasi",
  clause: "Band",
  table_row: "Qator",
  image: "Rasm",
};

function normalizeBackendDocument(item) {
  return {
    id: item.id,
    code: item.code,
    title: item.title,
    categoryId: item.categoryId ?? null,
    category: item.category,
    categoryName: item.categoryName ?? item.category,
    section: item.section ?? null,
    lexUrl: item.lexUrl ?? "",
    status: item.status,
    progress: {
      docHtml: item.progress?.docHtml ?? 0,
      chunking: item.progress?.chunking ?? 0,
      rowEmbedding: item.progress?.rowEmbedding ?? 0,
      imgEmbedding: item.progress?.imgEmbedding ?? 0,
    },
    failedAt: item.failedAt ?? null,
    errorMessage: item.errorMessage ?? null,
    createdAt: item.createdAt ?? null,
  };
}

function normalizeSection(item) {
  return {
    id: item.id,
    code: item.code,
    name: item.name,
  };
}

function normalizeCategory(item) {
  return {
    id: item.id,
    sectionId: item.sectionId,
    sectionCode: item.sectionCode,
    sectionName: item.sectionName,
    code: item.code,
    name: item.name,
  };
}

function normalizeBackendUser(item) {
  return {
    id: item.id,
    firstName: item.first_name ?? "",
    lastName: item.last_name ?? "",
    email: item.email ?? "",
    phone: item.phone ?? "",
    createdAt: item.created_at ?? null,
  };
}

function normalizeQAHistoryItem(item) {
  return {
    id: item.id,
    sessionId: item.session_id,
    roomId: item.room_id ?? null,
    askedBy: item.asked_by ?? "Mehmon",
    email: item.email ?? null,
    phone: item.phone ?? null,
    question: item.question ?? "",
    answer: item.answer ?? null,
    askedAt: item.asked_at ?? null,
    answeredAt: item.answered_at ?? null,
  };
}

function normalizeDashboardStats(item) {
  return {
    totalDocuments: item?.totalDocuments ?? 0,
    queuedDocuments: item?.queuedDocuments ?? 0,
    processingDocuments: item?.processingDocuments ?? 0,
    doneDocuments: item?.doneDocuments ?? 0,
    failedDocuments: item?.failedDocuments ?? 0,
    totalClauses: item?.totalClauses ?? 0,
    totalTables: item?.totalTables ?? 0,
    totalTableRows: item?.totalTableRows ?? 0,
    clauseEmbeddings: item?.clauseEmbeddings ?? 0,
    tableRowEmbeddings: item?.tableRowEmbeddings ?? 0,
    imageEmbeddings: item?.imageEmbeddings ?? 0,
    embeddingCoveragePercent: item?.embeddingCoveragePercent ?? 0,
  };
}

function statusBadge(status) {
  if (status === "done") {
    return "px-3 py-1 rounded-full bg-green-50 dark:bg-green-900/20 text-green-600 text-[10px] font-black uppercase tracking-tighter border border-green-200 dark:border-green-800";
  }
  if (status === "failed") {
    return "px-3 py-1 rounded-full bg-red-50 dark:bg-red-900/20 text-red-600 text-[10px] font-black uppercase tracking-tighter border border-red-200 dark:border-red-800";
  }
  if (status === "queued") {
    return "px-3 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 text-[10px] font-black uppercase tracking-tighter border border-slate-200 dark:border-slate-700";
  }
  return "px-3 py-1 rounded-full bg-primary/10 text-primary text-[10px] font-black uppercase tracking-tighter border border-primary/20";
}

function statusText(status) {
  if (status === "done") return "Bajarildi";
  if (status === "failed") return "Xatolik";
  if (status === "queued") return "Navbatda";
  return "Jarayonda";
}

function StageBar({ pct, done = false, failed = false }) {
  const color = failed ? "bg-red-500" : done ? "bg-green-500" : "bg-primary";
  const textColor = failed ? "text-red-500" : done ? "text-green-500" : "text-slate-400";

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
        <div className={"h-full " + color} style={{ width: `${pct}%` }} />
      </div>
      {done ? (
        <span className="material-symbols-outlined text-green-500 text-[14px]">check_circle</span>
      ) : (
        <span className={"text-[10px] font-bold " + textColor}>{pct}%</span>
      )}
    </div>
  );
}

function HujjatModal({ open, onClose, onSubmit, categories, sections, mode = "create", initialData = null }) {
  const isEditMode = mode === "edit";
  const [form, setForm] = useState({
    id: "",
    category_id: "",
    title: "",
    code: "",
    lex_url: "",
    original_file: "",
    html_file: "",
    original_upload: null,
    html_upload: null,
  });
  const [originalUploadProgress, setOriginalUploadProgress] = useState(0);
  const [htmlUploadProgress, setHtmlUploadProgress] = useState(0);
  const [isOriginalUploading, setIsOriginalUploading] = useState(false);
  const [isHtmlUploading, setIsHtmlUploading] = useState(false);

  useEffect(() => {
    if (!open) {
      setForm({
        id: "",
        category_id: "",
        title: "",
        code: "",
        lex_url: "",
        original_file: "",
        html_file: "",
        original_upload: null,
        html_upload: null,
      });
      setOriginalUploadProgress(0);
      setHtmlUploadProgress(0);
      setIsOriginalUploading(false);
      setIsHtmlUploading(false);
      return;
    }

    if (isEditMode && initialData) {
      setForm({
        id: initialData.id || "",
        category_id: initialData.categoryId || "",
        title: initialData.title || "",
        code: initialData.code || "",
        lex_url: initialData.lexUrl || "",
        original_file: "",
        html_file: "",
        original_upload: null,
        html_upload: null,
      });
      setOriginalUploadProgress(0);
      setHtmlUploadProgress(0);
      setIsOriginalUploading(false);
      setIsHtmlUploading(false);
      return;
    }

    setForm({
      id: "",
      category_id: "",
      title: "",
      code: "",
      lex_url: "",
      original_file: "",
      html_file: "",
      original_upload: null,
      html_upload: null,
    });
    setOriginalUploadProgress(0);
    setHtmlUploadProgress(0);
    setIsOriginalUploading(false);
    setIsHtmlUploading(false);
  }, [open, isEditMode, initialData]);

  const categoriesBySection = useMemo(() => {
    const bucket = new Map();
    sections.forEach((section) => {
      bucket.set(section.id, {
        id: section.id,
        code: section.code,
        name: section.name,
        categories: [],
      });
    });
    categories.forEach((category) => {
      const group = bucket.get(category.sectionId);
      if (group) {
        group.categories.push(category);
      }
    });
    return Array.from(bucket.values()).filter((group) => group.categories.length > 0);
  }, [categories, sections]);

  const hasCategories = categories.length > 0;

  if (!open) return null;

  function handleChange(event) {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const ok = await onSubmit(form);
    if (ok) onClose();
  }

  function runFakeUpload(setProgress, setUploading) {
    setUploading(true);
    setProgress(0);

    const timer = setInterval(() => {
      setProgress((prev) => {
        const next = prev + Math.floor(Math.random() * 18 + 8);
        if (next >= 100) {
          clearInterval(timer);
          setUploading(false);
          return 100;
        }
        return next;
      });
    }, 180);
  }

  function handleFileChange(event, kind) {
    const file = event.target.files?.[0];
    if (!file) return;

    if (kind === "original") {
      setForm((prev) => ({ ...prev, original_file: `docs/original/${file.name}`, original_upload: file }));
      runFakeUpload(setOriginalUploadProgress, setIsOriginalUploading);
      return;
    }

    setForm((prev) => ({ ...prev, html_file: `docs/html/${file.name}`, html_upload: file }));
    runFakeUpload(setHtmlUploadProgress, setIsHtmlUploading);
  }

  const hasAnyUpload = Boolean(form.original_file || form.html_file);
  const uploadCount = Number(Boolean(form.original_file)) + Number(Boolean(form.html_file));
  const combinedProgress = uploadCount
    ? Math.round((originalUploadProgress + htmlUploadProgress) / uploadCount)
    : 0;
  const isUploading = isOriginalUploading || isHtmlUploading;

  const isLexValid =
    !form.lex_url ||
    form.lex_url.startsWith("http://") ||
    form.lex_url.startsWith("https://");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
      <div className="w-full max-w-[860px] rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <form onSubmit={handleSubmit} className="p-9 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Kategoriya
              <select
                required
                name="category_id"
                value={form.category_id}
                onChange={handleChange}
                className="mt-2 h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-slate-600 focus:border-primary focus:ring-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                <option value="">{hasCategories ? "Kategoriyani tanlang" : "Avval kategoriya yarating"}</option>
                {categoriesBySection.map((group) => (
                  <optgroup key={group.id} label={`${group.name} (${group.code})`}>
                    {group.categories.map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.name} ({category.code})
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              {!hasCategories ? (
                <p className="mt-2 text-xs font-medium text-amber-600 dark:text-amber-400">
                  Hujjat yaratishdan oldin kategoriya qo'shing.
                </p>
              ) : null}
            </label>

            <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Hujjat kodi
              <input
                required
                name="code"
                value={form.code}
                onChange={handleChange}
                placeholder="masalan, SHNQ-2024-00"
                className="mt-2 h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-slate-700 placeholder:text-slate-400 focus:border-primary focus:ring-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
          </div>

          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-200">
            Hujjat sarlavhasi
            <input
              required
              name="title"
              value={form.title}
              onChange={handleChange}
              placeholder="Qurilish standarti nomi"
              className="mt-2 h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-slate-700 placeholder:text-slate-400 focus:border-primary focus:ring-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>

          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-200">
              Lex URL
            </label>
            <div className="mt-2 relative">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-[17px]">
                link
              </span>
              <input
                name="lex_url"
                value={form.lex_url}
                onChange={handleChange}
                placeholder="https://lex.uz/..."
                className={`h-12 w-full rounded-xl border pl-10 pr-4 ${
                  isLexValid ? "border-slate-200" : "border-red-400"
                } bg-slate-50 text-slate-700 placeholder:text-slate-400 focus:border-primary focus:ring-primary dark:bg-slate-800 dark:text-slate-100`}
              />
            </div>
            {!isLexValid ? (
              <p className="mt-2 inline-flex items-center gap-1 text-xs text-red-500 font-medium">
                <span className="material-symbols-outlined text-[14px]">error</span>
                Iltimos, Lex URL to'g'ri kiriting.
              </p>
            ) : null}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Asl fayl manzili
              <div className="mt-2 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-9 text-center dark:border-slate-700 dark:bg-slate-800">
                <span className="material-symbols-outlined text-slate-400 text-[34px]">upload_file</span>
                <p className="mt-2 text-sm font-semibold text-slate-600 dark:text-slate-300">PDF, DOCX up to 50MB</p>
                <p className="text-xs text-slate-400 mt-1">Drag and drop or click to upload</p>
                <input
                  id="original-file"
                  type="file"
                  accept=".pdf,.doc,.docx"
                  className="hidden"
                  onChange={(event) => handleFileChange(event, "original")}
                />
                <label
                  htmlFor="original-file"
                  className="mt-3 inline-flex cursor-pointer items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  Fayl tanlash
                </label>
                <input
                  readOnly
                  value={form.original_file}
                  placeholder="docs/original/file.docx"
                  className="mt-3 h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                />
              </div>
            </label>

            <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              HTML fayl manzili
              <div className="mt-2 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-9 text-center dark:border-slate-700 dark:bg-slate-800">
                <span className="material-symbols-outlined text-slate-400 text-[34px]">html</span>
                <p className="mt-2 text-sm font-semibold text-slate-600 dark:text-slate-300">Processed HTML file</p>
                <p className="text-xs text-slate-400 mt-1">Drag and drop or click to upload</p>
                <input
                  id="html-file"
                  type="file"
                  accept=".html,.htm"
                  className="hidden"
                  onChange={(event) => handleFileChange(event, "html")}
                />
                <label
                  htmlFor="html-file"
                  className="mt-3 inline-flex cursor-pointer items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  Fayl tanlash
                </label>
                <input
                  readOnly
                  value={form.html_file}
                  placeholder="docs/html/file.html"
                  className="mt-3 h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                />
              </div>
            </label>
          </div>

          {hasAnyUpload ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-bold text-slate-500">
                <span>{isUploading ? "UPLOADING..." : "UPLOAD COMPLETED"}</span>
                <span>{combinedProgress}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden">
                <div className="h-full bg-primary" style={{ width: `${combinedProgress}%` }} />
              </div>
            </div>
          ) : null}

          <div className="pt-5 border-t border-slate-200 dark:border-slate-700 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-lg font-semibold text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Bekor qilish
            </button>
            <button
              type="submit"
              disabled={!hasCategories}
              className="px-7 py-2.5 rounded-xl bg-primary text-white font-bold inline-flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-[18px]">check_circle</span>
              {isEditMode ? "Saqlash" : "Hujjat yaratish"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function BolimModal({ open, onClose, onSubmit, mode = "create", initialData = null }) {
  const isEditMode = mode === "edit";
  const [form, setForm] = useState({ id: "", code: "", name: "" });

  useEffect(() => {
    if (!open) {
      setForm({ id: "", code: "", name: "" });
      return;
    }
    if (isEditMode && initialData) {
      setForm({
        id: initialData.id || "",
        code: initialData.code || "",
        name: initialData.name || "",
      });
      return;
    }
    setForm({ id: "", code: "", name: "" });
  }, [open, isEditMode, initialData]);

  if (!open) return null;

  async function handleSubmit(event) {
    event.preventDefault();
    const ok = await onSubmit(form);
    if (ok) onClose();
  }

  function handleChange(event) {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
      <div className="w-full max-w-[540px] rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {isEditMode ? "Bo'limni tahrirlash" : "Yangi bo'lim"}
            </p>
            <h3 className="text-xl font-black text-slate-900 dark:text-slate-100 mt-1">
              {isEditMode ? "Katta bo'lim tahrirlash" : "Katta bo'lim yaratish"}
            </h3>
          </div>

          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-200">
            Bo'lim kodi
            <input
              required
              name="code"
              value={form.code}
              onChange={handleChange}
              placeholder="masalan, TEXNIK"
              className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-slate-700 placeholder:text-slate-400 focus:border-primary focus:ring-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>

          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-200">
            Bo'lim nomi
            <input
              name="name"
              value={form.name}
              onChange={handleChange}
              placeholder="masalan, Texnik me'yorlar"
              className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-slate-700 placeholder:text-slate-400 focus:border-primary focus:ring-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>

          <div className="pt-3 border-t border-slate-200 dark:border-slate-700 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 rounded-lg font-semibold text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Bekor qilish
            </button>
            <button type="submit" className="px-5 py-2.5 rounded-xl bg-primary text-white font-bold">
              {isEditMode ? "Saqlash" : "Bo'lim yaratish"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function KategoriyaModal({ open, onClose, onSubmit, sections, mode = "create", initialData = null }) {
  const isEditMode = mode === "edit";
  const [form, setForm] = useState({ id: "", sectionId: "", code: "", name: "" });

  useEffect(() => {
    if (!open) {
      setForm({ id: "", sectionId: "", code: "", name: "" });
      return;
    }

    if (isEditMode && initialData) {
      setForm({
        id: initialData.id || "",
        sectionId: initialData.sectionId || "",
        code: initialData.code || "",
        name: initialData.name || "",
      });
      return;
    }

    if (sections.length > 0) {
      setForm({ id: "", sectionId: sections[0].id, code: "", name: "" });
    }
  }, [open, sections, isEditMode, initialData]);

  if (!open) return null;

  async function handleSubmit(event) {
    event.preventDefault();
    const ok = await onSubmit(form);
    if (ok) onClose();
  }

  function handleChange(event) {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  const hasSections = sections.length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
      <div className="w-full max-w-[580px] rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {isEditMode ? "Kategoriyani tahrirlash" : "Yangi kategoriya"}
            </p>
            <h3 className="text-xl font-black text-slate-900 dark:text-slate-100 mt-1">
              {isEditMode ? "Kategoriya tahrirlash" : "Kategoriya yaratish"}
            </h3>
          </div>

          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-200">
            Katta bo'lim
            <select
              required
              name="sectionId"
              value={form.sectionId}
              onChange={handleChange}
              className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-slate-700 focus:border-primary focus:ring-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              {sections.map((section) => (
                <option key={section.id} value={section.id}>
                  {section.name} ({section.code})
                </option>
              ))}
            </select>
            {!hasSections ? (
              <p className="mt-2 text-xs font-medium text-amber-600 dark:text-amber-400">
                Avval bo'lim yarating.
              </p>
            ) : null}
          </label>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-200">
              Kategoriya kodi
              <input
                required
                name="code"
                value={form.code}
                onChange={handleChange}
                placeholder="masalan, SHNQ"
                className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-slate-700 placeholder:text-slate-400 focus:border-primary focus:ring-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-200">
              Kategoriya nomi
              <input
                name="name"
                value={form.name}
                onChange={handleChange}
                placeholder="masalan, Qurilish normalari"
                className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-slate-700 placeholder:text-slate-400 focus:border-primary focus:ring-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
          </div>

          <div className="pt-3 border-t border-slate-200 dark:border-slate-700 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 rounded-lg font-semibold text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Bekor qilish
            </button>
            <button
              type="submit"
              disabled={!hasSections}
              className="px-5 py-2.5 rounded-xl bg-primary text-white font-bold disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isEditMode ? "Saqlash" : "Kategoriya yaratish"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function BolimlarSahifasi({ sections, categories, onOpenModal, onRefresh, onEdit, onDelete }) {
  const categoryCountBySection = useMemo(() => {
    const map = new Map();
    categories.forEach((category) => {
      map.set(category.sectionId, (map.get(category.sectionId) || 0) + 1);
    });
    return map;
  }, [categories]);

  return (
    <div className="flex-1 overflow-hidden flex flex-col p-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-slate-900 dark:text-slate-50 tracking-tight">Katta bo'limlar</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Avval bo'limlar yaratiladi, keyin kategoriyalar shu bo'limga biriktiriladi.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onRefresh}
            className="flex items-center justify-center h-10 w-10 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700"
          >
            <span className="material-symbols-outlined text-[18px]">refresh</span>
          </button>
          <button onClick={onOpenModal} className="px-4 py-2.5 rounded-lg bg-primary text-white text-sm font-bold">
            Bo'lim yaratish
          </button>
        </div>
      </div>

      <div className="flex-1 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col overflow-hidden shadow-sm">
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse min-w-[760px]">
            <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800/80 z-20">
              <tr className="text-left text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700">
                <th className="px-6 py-4 w-[220px]">Bo'lim kodi</th>
                <th className="px-6 py-4">Bo'lim nomi</th>
                <th className="px-6 py-4 w-[160px]">Kategoriyalar</th>
                <th className="px-6 py-4 w-[170px] text-right">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {sections.map((section) => (
                <tr key={section.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/50">
                  <td className="px-6 py-4">
                    <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[11px] font-bold text-slate-700 dark:text-slate-200">
                      {section.code}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm font-medium text-slate-700 dark:text-slate-200">{section.name}</td>
                  <td className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400">{categoryCountBySection.get(section.id) || 0}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => onEdit(section)}
                        className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700"
                      >
                        Tahrirlash
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(section)}
                        className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-900/20 dark:text-red-400"
                      >
                        O'chirish
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {sections.length === 0 ? (
            <div className="px-6 py-8 text-sm text-slate-500 dark:text-slate-400">
              Hozircha bo'limlar yo'q. Bo'lim yaratish tugmasi orqali yangi bo'lim qo'shing.
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function KategoriyalarSahifasi({ categories, documents, onOpenModal, onRefresh, onEdit, onDelete }) {
  const documentCountByCategory = useMemo(() => {
    const map = new Map();
    documents.forEach((doc) => {
      if (!doc.categoryId) return;
      map.set(doc.categoryId, (map.get(doc.categoryId) || 0) + 1);
    });
    return map;
  }, [documents]);

  return (
    <div className="flex-1 overflow-hidden flex flex-col p-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-slate-900 dark:text-slate-50 tracking-tight">Kategoriyalar</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Har bir kategoriya bitta katta bo'limga bog'lanadi.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onRefresh}
            className="flex items-center justify-center h-10 w-10 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700"
          >
            <span className="material-symbols-outlined text-[18px]">refresh</span>
          </button>
          <button onClick={onOpenModal} className="px-4 py-2.5 rounded-lg bg-primary text-white text-sm font-bold">
            Kategoriya yaratish
          </button>
        </div>
      </div>

      <div className="flex-1 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col overflow-hidden shadow-sm">
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse min-w-[900px]">
            <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800/80 z-20">
              <tr className="text-left text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700">
                <th className="px-6 py-4 w-[240px]">Katta bo'lim</th>
                <th className="px-6 py-4 w-[180px]">Kategoriya kodi</th>
                <th className="px-6 py-4">Kategoriya nomi</th>
                <th className="px-6 py-4 w-[140px]">Hujjatlar</th>
                <th className="px-6 py-4 w-[170px] text-right">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {categories.map((category) => (
                <tr key={category.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/50">
                  <td className="px-6 py-4 text-sm font-medium text-slate-700 dark:text-slate-200">
                    {category.sectionName} ({category.sectionCode})
                  </td>
                  <td className="px-6 py-4">
                    <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[11px] font-bold text-slate-700 dark:text-slate-200">
                      {category.code}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-700 dark:text-slate-200">{category.name}</td>
                  <td className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400">{documentCountByCategory.get(category.id) || 0}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => onEdit(category)}
                        className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700"
                      >
                        Tahrirlash
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(category)}
                        className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-900/20 dark:text-red-400"
                      >
                        O'chirish
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {categories.length === 0 ? (
            <div className="px-6 py-8 text-sm text-slate-500 dark:text-slate-400">
              Hozircha kategoriyalar yo'q. Avval bo'lim yaratib, keyin kategoriya qo'shing.
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function FoydalanuvchilarSahifasi({ users, onRefresh, onDelete }) {
  return (
    <div className="flex-1 overflow-hidden flex flex-col p-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-slate-900 dark:text-slate-50 tracking-tight">Foydalanuvchilar</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Tizimga ro'yxatdan o'tgan foydalanuvchilar ro'yxati.</p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center justify-center h-10 w-10 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700"
          title="Yangilash"
        >
          <span className="material-symbols-outlined text-[18px]">refresh</span>
        </button>
      </div>

      <div className="flex-1 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col overflow-hidden shadow-sm">
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse min-w-[980px]">
            <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800/80 z-20">
              <tr className="text-left text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700">
                <th className="px-6 py-4 w-[180px]">Ism</th>
                <th className="px-6 py-4 w-[200px]">Familya</th>
                <th className="px-6 py-4">Gmail</th>
                <th className="px-6 py-4 w-[190px]">Telefon raqami</th>
                <th className="px-6 py-4 w-[220px]">Ro'yxatdan o'tgan</th>
                <th className="px-6 py-4 w-[120px] text-right">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/50">
                  <td className="px-6 py-4 text-sm font-medium text-slate-700 dark:text-slate-200">{user.firstName || "-"}</td>
                  <td className="px-6 py-4 text-sm text-slate-700 dark:text-slate-200">{user.lastName || "-"}</td>
                  <td className="px-6 py-4 text-sm text-slate-600 dark:text-slate-300">{user.email || "-"}</td>
                  <td className="px-6 py-4 text-sm text-slate-600 dark:text-slate-300">{user.phone || "-"}</td>
                  <td className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400">
                    {user.createdAt ? new Date(user.createdAt).toLocaleString("uz-UZ") : "-"}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end">
                      <button
                        type="button"
                        onClick={() => onDelete(user)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-900/20 dark:text-red-400"
                        title="Foydalanuvchini o'chirish"
                        aria-label="Foydalanuvchini o'chirish"
                      >
                        <span className="material-symbols-outlined text-[18px]">delete</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {users.length === 0 ? (
            <div className="px-6 py-8 text-sm text-slate-500 dark:text-slate-400">
              Hozircha foydalanuvchilar topilmadi.
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SavolJavobSahifasi({ qaItems, onRefresh }) {
  return (
    <div className="flex-1 overflow-hidden flex flex-col p-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-slate-900 dark:text-slate-50 tracking-tight">Savol-javob</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Foydalanuvchilarning bergan savollari va tizim javoblari.</p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center justify-center h-10 w-10 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700"
          title="Yangilash"
        >
          <span className="material-symbols-outlined text-[18px]">refresh</span>
        </button>
      </div>

      <div className="flex-1 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col overflow-hidden shadow-sm">
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse min-w-[1300px]">
            <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800/80 z-20">
              <tr className="text-left text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700">
                <th className="px-6 py-4 w-[220px]">Kim bergan</th>
                <th className="px-6 py-4 w-[340px]">Savol</th>
                <th className="px-6 py-4">Javob</th>
                <th className="px-6 py-4 w-[220px]">Savol vaqti</th>
                <th className="px-6 py-4 w-[220px]">Javob vaqti</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {qaItems.map((item) => (
                <tr key={item.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/50 align-top">
                  <td className="px-6 py-4">
                    <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">{item.askedBy || "-"}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">{item.email || "-"}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">{item.phone || "-"}</div>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap break-words">
                    {item.question || "-"}
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-600 dark:text-slate-300 whitespace-pre-wrap break-words">
                    {item.answer || "Javob hali yo'q"}
                  </td>
                  <td className="px-6 py-4 text-xs text-slate-500 dark:text-slate-400">
                    {item.askedAt ? new Date(item.askedAt).toLocaleString("uz-UZ") : "-"}
                  </td>
                  <td className="px-6 py-4 text-xs text-slate-500 dark:text-slate-400">
                    {item.answeredAt ? new Date(item.answeredAt).toLocaleString("uz-UZ") : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {qaItems.length === 0 ? (
            <div className="px-6 py-8 text-sm text-slate-500 dark:text-slate-400">
              Hozircha savol-javoblar topilmadi.
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function EmbeddingTekshiruvModal({
  open,
  onClose,
  documentItem,
  data,
  isLoading,
  errorMessage,
  activeType,
  onTypeChange,
  onRefresh,
}) {
  if (!open) return null;

  const summary = data?.summary || { total: 0, clause: 0, tableRow: 0, image: 0 };
  const rows = data?.items || [];
  const previewOrDash = (value) => (value && value.trim() ? value : "-");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
      <div className="w-full max-w-[1200px] rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <div className="px-6 py-5 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between gap-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Embedding tekshiruvi</p>
            <h3 className="text-lg font-black text-slate-900 dark:text-slate-100 mt-1">
              {documentItem?.code || "-"} - {documentItem?.title || ""}
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onRefresh}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <span className="material-symbols-outlined text-[16px]">refresh</span>
              Yangilash
            </button>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            >
              <span className="material-symbols-outlined text-[16px]">close</span>
              Yopish
            </button>
          </div>
        </div>

        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex flex-wrap items-center gap-2">
          {Object.entries(EMBEDDING_TYPE_LABELS).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => onTypeChange(key)}
              className={`px-3 py-1 rounded-full text-[11px] font-bold border uppercase tracking-tight ${
                activeType === key
                  ? "bg-primary/10 text-primary border-primary/20"
                  : "bg-slate-50 dark:bg-slate-800 text-slate-500 border-slate-200 dark:border-slate-700"
              }`}
            >
              {label}
            </button>
          ))}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">Jami: {summary.total}</span>
            <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">Band: {summary.clause}</span>
            <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">Qator: {summary.tableRow}</span>
            <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">Rasm: {summary.image}</span>
          </div>
        </div>

        <div className="max-h-[70vh] overflow-auto">
          {isLoading ? (
            <div className="px-6 py-8 text-sm font-medium text-slate-500 dark:text-slate-400">Embeddinglar yuklanmoqda...</div>
          ) : null}
          {!isLoading && errorMessage ? (
            <div className="px-6 py-8 text-sm font-medium text-red-500">{errorMessage}</div>
          ) : null}
          {!isLoading && !errorMessage && rows.length === 0 ? (
            <div className="px-6 py-8 text-sm font-medium text-slate-500 dark:text-slate-400">Bu hujjat uchun embedding topilmadi.</div>
          ) : null}
          {!isLoading && !errorMessage && rows.length > 0 ? (
            <table className="w-full border-collapse min-w-[980px]">
              <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800/90 z-10">
                <tr className="text-left text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700">
                  <th className="px-4 py-3 w-[90px]">Raqam</th>
                  <th className="px-4 py-3 w-[120px]">Turi</th>
                  <th className="px-4 py-3 w-[280px]">Nomi</th>
                  <th className="px-4 py-3 w-[140px]">Ref</th>
                  <th className="px-4 py-3 w-[110px]">Token</th>
                  <th className="px-4 py-3 w-[180px]">Model</th>
                  <th className="px-4 py-3">Preview</th>
                  <th className="px-4 py-3 w-[360px]">NormTable</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map((item) => (
                  <tr key={item.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/50">
                    <td className="px-4 py-3 text-xs font-bold text-slate-700 dark:text-slate-200">{item.sequenceNumber}</td>
                    <td className="px-4 py-3 text-xs font-semibold text-slate-600 dark:text-slate-300">{EMBEDDING_TYPE_LABELS[item.type] || item.type}</td>
                    <td className="px-4 py-3 text-xs font-semibold text-slate-700 dark:text-slate-200">{item.name}</td>
                    <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{item.referenceNumber}</td>
                    <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{item.tokenCount}</td>
                    <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{item.embeddingModel}</td>
                    <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">{item.preview || "-"}</td>
                    <td className="px-4 py-3 align-top">
                      {item.type === "table_row" && item.normTable ? (
                        <details className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 p-2">
                          <summary className="cursor-pointer text-[11px] font-bold text-primary">NormTable maydonlarini ko'rish</summary>
                          <div className="mt-2 space-y-2 text-[11px]">
                            <div>
                              <p className="font-bold text-slate-600 dark:text-slate-300">raw_html</p>
                              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white dark:bg-slate-900 p-2 text-slate-600 dark:text-slate-300">{previewOrDash(item.normTable.rawHtml)}</pre>
                            </div>
                            <div>
                              <p className="font-bold text-slate-600 dark:text-slate-300">raw_html_ru</p>
                              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white dark:bg-slate-900 p-2 text-slate-600 dark:text-slate-300">{previewOrDash(item.normTable.rawHtmlRu)}</pre>
                            </div>
                            <div>
                              <p className="font-bold text-slate-600 dark:text-slate-300">raw_html_en</p>
                              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white dark:bg-slate-900 p-2 text-slate-600 dark:text-slate-300">{previewOrDash(item.normTable.rawHtmlEn)}</pre>
                            </div>
                            <div>
                              <p className="font-bold text-slate-600 dark:text-slate-300">raw_html_ko</p>
                              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white dark:bg-slate-900 p-2 text-slate-600 dark:text-slate-300">{previewOrDash(item.normTable.rawHtmlKo)}</pre>
                            </div>
                            <div>
                              <p className="font-bold text-slate-600 dark:text-slate-300">markdown</p>
                              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white dark:bg-slate-900 p-2 text-slate-600 dark:text-slate-300">{previewOrDash(item.normTable.markdown)}</pre>
                            </div>
                            <div>
                              <p className="font-bold text-slate-600 dark:text-slate-300">markdown_ru</p>
                              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white dark:bg-slate-900 p-2 text-slate-600 dark:text-slate-300">{previewOrDash(item.normTable.markdownRu)}</pre>
                            </div>
                            <div>
                              <p className="font-bold text-slate-600 dark:text-slate-300">markdown_en</p>
                              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white dark:bg-slate-900 p-2 text-slate-600 dark:text-slate-300">{previewOrDash(item.normTable.markdownEn)}</pre>
                            </div>
                            <div>
                              <p className="font-bold text-slate-600 dark:text-slate-300">markdown_ko</p>
                              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white dark:bg-slate-900 p-2 text-slate-600 dark:text-slate-300">{previewOrDash(item.normTable.markdownKo)}</pre>
                            </div>
                          </div>
                        </details>
                      ) : (
                        <span className="text-[11px] text-slate-400">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function HujjatlarSahifasi({ documents, onOpenModal, onRefresh, onOpenEmbeddings, onEdit, onDelete }) {
  const processingCount = documents.filter((d) => d.status === "processing").length;
  const stuckCount = documents.filter((d) => d.status === "processing" || d.status === "queued").length;

  return (
    <div className="flex-1 overflow-hidden flex flex-col p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-black text-slate-900 dark:text-slate-50 tracking-tight">Real vaqt pipeline nazorati</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Hujjatlarning DOC dan embeddinggacha bo'lgan jarayoni.</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onRefresh(true)}
            className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-700 transition hover:bg-amber-100 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-300"
            title="Qotib qolgan pipeline'larni qayta navbatga qo'yish"
          >
            <span className="material-symbols-outlined text-[18px]">restart_alt</span>
            Qayta ishga tushirish ({stuckCount})
          </button>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-100 dark:border-green-800">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
            </span>
            <span className="text-xs font-bold text-green-700 dark:text-green-400 uppercase tracking-widest">Tizim holati: me'yorida</span>
          </div>
          <button onClick={() => onRefresh()} className="flex items-center justify-center h-10 w-10 bg-primary text-white rounded-lg shadow-lg shadow-primary/20 hover:bg-primary/90 transition-all" title="Yangilash">
            <span className="material-symbols-outlined text-[20px]">refresh</span>
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between bg-white dark:bg-slate-900 p-3 rounded-xl border border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-xs font-bold border border-transparent hover:border-slate-300 transition-all">
            <span className="material-symbols-outlined text-[18px]">filter_alt</span>
            Filtrlar
          </button>
          <div className="h-6 w-px bg-slate-200 dark:bg-slate-700 mx-2" />
          <div className="flex gap-2">
            <button className="px-3 py-1 rounded-full bg-primary/10 text-primary text-[11px] font-bold border border-primary/20 uppercase tracking-tight">Barchasi</button>
            <button className="px-3 py-1 rounded-full bg-slate-50 dark:bg-slate-800 text-slate-500 text-[11px] font-bold border border-slate-200 dark:border-slate-700 uppercase tracking-tight hover:bg-slate-100 transition-all">Qurilish</button>
            <button className="px-3 py-1 rounded-full bg-slate-50 dark:bg-slate-800 text-slate-500 text-[11px] font-bold border border-slate-200 dark:border-slate-700 uppercase tracking-tight hover:bg-slate-100 transition-all">Elektr</button>
            <button className="px-3 py-1 rounded-full bg-slate-50 dark:bg-slate-800 text-slate-500 text-[11px] font-bold border border-slate-200 dark:border-slate-700 uppercase tracking-tight hover:bg-slate-100 transition-all">Mexanika</button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 font-medium mr-2">Ko'rsatilmoqda: {documents.length} ta</span>
          <button onClick={onOpenModal} className="px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-bold">Hujjat yaratish</button>
        </div>
      </div>

      <div className="flex-1 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col overflow-hidden shadow-sm">
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse min-w-[1200px]">
            <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800/80 backdrop-blur-sm z-20">
              <tr className="text-left text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest border-b border-slate-200 dark:border-slate-700">
                <th className="px-6 py-4 w-[140px] sticky-col bg-slate-50 dark:bg-slate-800">Kod</th>
                <th className="px-6 py-4 w-[300px] sticky-col-2 bg-slate-50 dark:bg-slate-800">Sarlavha</th>
                <th className="px-6 py-4 w-[150px]">Kategoriya</th>
                <th className="px-6 py-4">Doc -&gt; HTML</th>
                <th className="px-6 py-4">Chunking</th>
                <th className="px-6 py-4">Qator embedding</th>
                <th className="px-6 py-4">Rasm embedding</th>
                <th className="px-6 py-4 text-center">Holat</th>
                <th className="px-6 py-4 w-[170px] text-right">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {documents.map((doc) => {
                const doneAll = doc.status === "done";
                return (
                  <tr key={doc.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/50 transition-colors group">
                    <td className="px-6 py-4 whitespace-nowrap sticky-col bg-white dark:bg-slate-900 group-hover:bg-slate-50/80 dark:group-hover:bg-slate-800/50">
                      <div className="flex items-center gap-3">
                        {doc.status === "processing" ? <div className="pulsing-dot" /> : null}
                        {doc.status === "queued" ? <span className="w-2 h-2 rounded-full bg-slate-300 dark:bg-slate-700" /> : null}
                        {doc.status === "failed" ? <span className="material-symbols-outlined text-red-500 text-[18px]">error</span> : null}
                        {doc.status === "done" ? <span className="w-2 h-2 rounded-full bg-emerald-500" /> : null}
                        <button
                          type="button"
                          onClick={() => onOpenEmbeddings(doc)}
                          className="font-bold text-xs text-primary hover:underline"
                        >
                          {doc.code}
                        </button>
                      </div>
                    </td>
                    <td className="px-6 py-4 sticky-col-2 bg-white dark:bg-slate-900 group-hover:bg-slate-50/80 dark:group-hover:bg-slate-800/50">
                      <span className={`font-medium text-xs truncate max-w-[250px] inline-block ${doc.status === "processing" ? "text-primary" : "text-slate-700 dark:text-slate-300"}`}>
                        {doc.title}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap items-center gap-1">
                        {doc.section ? (
                          <span className="px-2 py-0.5 rounded bg-primary/10 text-[10px] font-bold text-primary">
                            {doc.section}
                          </span>
                        ) : null}
                        <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[10px] font-bold text-slate-600 dark:text-slate-400">
                          {doc.categoryName || doc.category}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4"><StageBar pct={doc.progress.docHtml} done={doneAll || doc.progress.docHtml === 100} /></td>
                    <td className="px-6 py-4"><StageBar pct={doc.progress.chunking} failed={doc.status === "failed" && doc.failedAt === "chunking"} done={doneAll} /></td>
                    <td className="px-6 py-4"><StageBar pct={doc.progress.rowEmbedding} done={doneAll} /></td>
                    <td className="px-6 py-4"><StageBar pct={doc.progress.imgEmbedding} done={doneAll} /></td>
                    <td className="px-6 py-4 text-center"><span className={statusBadge(doc.status)}>{statusText(doc.status)}</span></td>
                    <td className="px-6 py-4">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => onEdit(doc)}
                          className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700"
                        >
                          Tahrirlash
                        </button>
                        <button
                          type="button"
                          onClick={() => onDelete(doc)}
                          className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-900/20 dark:text-red-400"
                        >
                          O'chirish
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="px-6 py-3 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 font-medium">Sahifadagi qatorlar:</span>
            <span className="text-xs font-bold text-slate-700 dark:text-slate-300">50</span>
          </div>
          <div className="flex items-center gap-6">
            <span className="text-xs text-slate-500 font-medium">1 - {documents.length} / {Math.max(1240, documents.length)}</span>
            <span className="text-xs text-slate-500 font-medium">Jarayonda: {processingCount}</span>
          </div>
        </div>
      </div>

      <button onClick={onOpenModal} className="fixed bottom-10 right-10 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-white shadow-2xl shadow-primary/40 hover:scale-105 transition-transform z-30" title="Hujjat yaratish">
        <span className="material-symbols-outlined text-[32px]">add</span>
      </button>
    </div>
  );
}

export default function HomePage() {
  const [theme, setTheme] = useState("light");
  const [documents, setDocuments] = useState([]);
  const [sections, setSections] = useState([]);
  const [categories, setCategories] = useState([]);
  const [users, setUsers] = useState([]);
  const [qaHistory, setQaHistory] = useState([]);
  const [dashboardStats, setDashboardStats] = useState(EMPTY_DASHBOARD_STATS);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSectionModalOpen, setIsSectionModalOpen] = useState(false);
  const [isCategoryModalOpen, setIsCategoryModalOpen] = useState(false);
  const [editingDocument, setEditingDocument] = useState(null);
  const [editingSection, setEditingSection] = useState(null);
  const [editingCategory, setEditingCategory] = useState(null);
  const [isEmbeddingModalOpen, setIsEmbeddingModalOpen] = useState(false);
  const [selectedEmbeddingDoc, setSelectedEmbeddingDoc] = useState(null);
  const [embeddingPayload, setEmbeddingPayload] = useState(null);
  const [embeddingKind, setEmbeddingKind] = useState("all");
  const [isLoadingEmbeddings, setIsLoadingEmbeddings] = useState(false);
  const [embeddingError, setEmbeddingError] = useState("");
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);
  const [cornerMessage, setCornerMessage] = useState("");
  const [cornerType, setCornerType] = useState("success");
  const [isAuthReady, setIsAuthReady] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [loginError, setLoginError] = useState("");
  const pathname = usePathname();
  const isDashboardPage = pathname === "/";
  const isSectionsPage = pathname === "/sections";
  const isCategoriesPage = pathname === "/categories";
  const isDocumentsPage = pathname === "/documents";
  const isUsersPage = pathname === "/users";
  const isQAPage = pathname === "/qa";

  useEffect(() => {
    const session = window.localStorage.getItem(AUTH_SESSION_KEY);
    setIsAuthenticated(session === "ok");
    setIsAuthReady(true);
  }, []);

  useEffect(() => {
    const saved = window.localStorage.getItem("theme");
    const initialTheme = saved === "dark" ? "dark" : "light";
    setTheme(initialTheme);
    document.documentElement.classList.remove("light", "dark");
    document.documentElement.classList.add(initialTheme);
  }, []);

  function toggleTheme() {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    document.documentElement.classList.remove("light", "dark");
    document.documentElement.classList.add(nextTheme);
    window.localStorage.setItem("theme", nextTheme);
  }

  function handleLoginFieldChange(event) {
    const { name, value } = event.target;
    setLoginForm((prev) => ({ ...prev, [name]: value }));
    if (loginError) {
      setLoginError("");
    }
  }

  function handleLoginSubmit(event) {
    event.preventDefault();
    const enteredUsername = loginForm.username.trim();
    const enteredPassword = loginForm.password;

    if (
      enteredUsername === STATIC_LOGIN.username &&
      enteredPassword === STATIC_LOGIN.password
    ) {
      window.localStorage.setItem(AUTH_SESSION_KEY, "ok");
      setIsAuthenticated(true);
      setLoginError("");
      setLoginForm({ username: "", password: "" });
      return;
    }

    window.localStorage.removeItem(AUTH_SESSION_KEY);
    setIsAuthenticated(false);
    setLoginError("Login yoki parol noto'g'ri.");
  }

  function handleLogout() {
    window.localStorage.removeItem(AUTH_SESSION_KEY);
    setIsAuthenticated(false);
  }

  async function parseErrorMessage(response, fallback) {
    const detail = await response.text();
    if (!detail) return fallback;
    try {
      const parsed = JSON.parse(detail);
      return parsed?.detail || fallback;
    } catch {
      return detail;
    }
  }

  async function loadDocuments() {
    try {
      setIsLoadingDocs(true);
      const [docsResponse, statsResponse] = await Promise.all([
        fetch(`${API_BASE}/api/upload/documents`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/upload/dashboard-stats`, { cache: "no-store" }),
      ]);

      if (docsResponse.ok) {
        const docsData = await docsResponse.json();
        if (Array.isArray(docsData)) {
          setDocuments(docsData.map(normalizeBackendDocument));
        }
      }
      if (statsResponse.ok) {
        const statsData = await statsResponse.json();
        setDashboardStats(normalizeDashboardStats(statsData));
      }
    } catch (error) {
      console.error("Hujjatlarni olishda xatolik:", error);
    } finally {
      setIsLoadingDocs(false);
    }
  }

  async function requeueStuckDocuments() {
    try {
      const response = await fetch(`${API_BASE}/api/upload/documents/requeue-stuck`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await parseErrorMessage(response, "Hujjatlarni qayta ishga tushirishda xatolik"));
      }
      const result = await response.json();
      setCornerType("success");
      setCornerMessage(result?.detail || "Hujjatlar qayta navbatga qo'yildi");
      await loadDocuments();
    } catch (error) {
      console.error("Stuck hujjatlarni qayta ishga tushirishda xatolik:", error);
      setCornerType("error");
      setCornerMessage(error?.message || "Qayta ishga tushirishda xatolik");
    }
  }

  async function refreshDocuments(forceRequeue = false) {
    if (forceRequeue) {
      await requeueStuckDocuments();
      return;
    }
    await loadDocuments();
  }

  async function loadTaxonomy() {
    try {
      const [sectionsResponse, categoriesResponse] = await Promise.all([
        fetch(`${API_BASE}/api/upload/sections`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/upload/categories`, { cache: "no-store" }),
      ]);

      if (sectionsResponse.ok) {
        const sectionsData = await sectionsResponse.json();
        if (Array.isArray(sectionsData)) {
          setSections(sectionsData.map(normalizeSection));
        }
      }

      if (categoriesResponse.ok) {
        const categoriesData = await categoriesResponse.json();
        if (Array.isArray(categoriesData)) {
          setCategories(categoriesData.map(normalizeCategory));
        }
      }
    } catch (error) {
      console.error("Bo'lim/kategoriya ma'lumotini olishda xatolik:", error);
    }
  }

  async function loadUsers() {
    try {
      const response = await fetch(`${API_BASE}/api/auth/users`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await parseErrorMessage(response, "Foydalanuvchilarni olishda xatolik"));
      }
      const usersData = await response.json();
      if (Array.isArray(usersData)) {
        setUsers(usersData.map(normalizeBackendUser));
      } else {
        setUsers([]);
      }
    } catch (error) {
      console.error("Foydalanuvchilarni olishda xatolik:", error);
    }
  }

  async function loadQAHistory() {
    try {
      const response = await fetch(`${API_BASE}/api/chat/qa-history?limit=500`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await parseErrorMessage(response, "Savol-javoblarni olishda xatolik"));
      }
      const qaData = await response.json();
      if (Array.isArray(qaData)) {
        setQaHistory(qaData.map(normalizeQAHistoryItem));
      } else {
        setQaHistory([]);
      }
    } catch (error) {
      console.error("Savol-javoblarni olishda xatolik:", error);
    }
  }

  async function upsertDocument(form) {
    const isEdit = Boolean(form.id);
    if (!form.category_id) {
      setCornerType("error");
      setCornerMessage("Kategoriya tanlang");
      return false;
    }
    if (!isEdit && !form.html_upload) {
      setCornerType("error");
      setCornerMessage("Yangi hujjat uchun HTML fayl majburiy");
      return false;
    }

    const payload = new FormData();
    payload.append("category_id", form.category_id);
    payload.append("title", form.title || "");
    payload.append("code", form.code || "");
    payload.append("lex_url", form.lex_url || "");

    if (form.original_upload) {
      payload.append("original_file", form.original_upload);
    }
    if (form.html_upload) {
      payload.append("html_file", form.html_upload);
    }

    try {
      const endpoint = isEdit
        ? `${API_BASE}/api/upload/documents/${form.id}`
        : `${API_BASE}/api/upload/documents`;
      const response = await fetch(endpoint, {
        method: isEdit ? "PUT" : "POST",
        body: payload,
      });
      if (!response.ok) {
        const message = await parseErrorMessage(response, "Yuklashda xatolik");
        console.error("Hujjat saqlashda xatolik:", message);
        setCornerType("error");
        setCornerMessage(message);
        return false;
      }
      const result = await response.json();
      await loadDocuments();
      setCornerType("success");
      if (isEdit) {
        setCornerMessage(result?.status === "queued" ? "Hujjat yangilandi va qayta ishlashga yuborildi" : "Hujjat yangilandi");
      } else {
        setCornerMessage("Hujjat yuklandi");
      }
      return true;
    } catch (error) {
      console.error("Hujjat saqlashda xatolik:", error);
      setCornerType("error");
      setCornerMessage("Yuklashda xatolik");
      return false;
    }
  }

  async function deleteDocument(item) {
    if (!item?.id) return;
    if (!window.confirm(`"${item.code}" hujjatini o'chirmoqchimisiz?`)) return;
    try {
      const response = await fetch(`${API_BASE}/api/upload/documents/${item.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const message = await parseErrorMessage(response, "Hujjatni o'chirishda xatolik");
        setCornerType("error");
        setCornerMessage(message);
        return;
      }
      await loadDocuments();
      setCornerType("success");
      setCornerMessage("Hujjat o'chirildi");
    } catch (error) {
      console.error("Hujjatni o'chirishda xatolik:", error);
      setCornerType("error");
      setCornerMessage("Hujjatni o'chirishda xatolik");
    }
  }

  async function upsertSection(form) {
    const isEdit = Boolean(form.id);
    const payload = {
      code: form.code || "",
      name: form.name || "",
    };

    try {
      const endpoint = isEdit
        ? `${API_BASE}/api/upload/sections/${form.id}`
        : `${API_BASE}/api/upload/sections`;
      const response = await fetch(endpoint, {
        method: isEdit ? "PUT" : "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const message = await parseErrorMessage(response, "Bo'limni saqlashda xatolik");
        setCornerType("error");
        setCornerMessage(message);
        return false;
      }
      await refreshAll();
      setCornerType("success");
      setCornerMessage(isEdit ? "Bo'lim yangilandi" : "Bo'lim yaratildi");
      return true;
    } catch (error) {
      console.error("Bo'limni saqlashda xatolik:", error);
      setCornerType("error");
      setCornerMessage("Bo'limni saqlashda xatolik");
      return false;
    }
  }

  async function deleteSection(item) {
    if (!item?.id) return;
    if (!window.confirm(`"${item.name}" bo'limini o'chirmoqchimisiz?`)) return;
    try {
      const response = await fetch(`${API_BASE}/api/upload/sections/${item.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const message = await parseErrorMessage(response, "Bo'limni o'chirishda xatolik");
        setCornerType("error");
        setCornerMessage(message);
        return;
      }
      await refreshAll();
      setCornerType("success");
      setCornerMessage("Bo'lim o'chirildi");
    } catch (error) {
      console.error("Bo'limni o'chirishda xatolik:", error);
      setCornerType("error");
      setCornerMessage("Bo'limni o'chirishda xatolik");
    }
  }

  async function upsertCategory(form) {
    const isEdit = Boolean(form.id);
    const payload = {
      sectionId: form.sectionId || "",
      code: form.code || "",
      name: form.name || "",
    };

    try {
      const endpoint = isEdit
        ? `${API_BASE}/api/upload/categories/${form.id}`
        : `${API_BASE}/api/upload/categories`;
      const response = await fetch(endpoint, {
        method: isEdit ? "PUT" : "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const message = await parseErrorMessage(response, "Kategoriyani saqlashda xatolik");
        setCornerType("error");
        setCornerMessage(message);
        return false;
      }
      await refreshAll();
      setCornerType("success");
      setCornerMessage(isEdit ? "Kategoriya yangilandi" : "Kategoriya yaratildi");
      return true;
    } catch (error) {
      console.error("Kategoriyani saqlashda xatolik:", error);
      setCornerType("error");
      setCornerMessage("Kategoriyani saqlashda xatolik");
      return false;
    }
  }

  async function deleteCategory(item) {
    if (!item?.id) return;
    if (!window.confirm(`"${item.name}" kategoriyasini o'chirmoqchimisiz?`)) return;
    try {
      const response = await fetch(`${API_BASE}/api/upload/categories/${item.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const message = await parseErrorMessage(response, "Kategoriyani o'chirishda xatolik");
        setCornerType("error");
        setCornerMessage(message);
        return;
      }
      await refreshAll();
      setCornerType("success");
      setCornerMessage("Kategoriya o'chirildi");
    } catch (error) {
      console.error("Kategoriyani o'chirishda xatolik:", error);
      setCornerType("error");
      setCornerMessage("Kategoriyani o'chirishda xatolik");
    }
  }

  async function deleteUser(item) {
    if (!item?.id) return;
    const fullName = `${item.firstName || ""} ${item.lastName || ""}`.trim();
    const displayName = fullName || item.email || item.phone || "Foydalanuvchi";
    if (!window.confirm(`"${displayName}" foydalanuvchisini o'chirmoqchimisiz?`)) return;
    try {
      const response = await fetch(`${API_BASE}/api/auth/users/${item.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const message = await parseErrorMessage(response, "Foydalanuvchini o'chirishda xatolik");
        setCornerType("error");
        setCornerMessage(message);
        return;
      }
      await loadUsers();
      setCornerType("success");
      setCornerMessage("Foydalanuvchi o'chirildi");
    } catch (error) {
      console.error("Foydalanuvchini o'chirishda xatolik:", error);
      setCornerType("error");
      setCornerMessage("Foydalanuvchini o'chirishda xatolik");
    }
  }

  async function loadDocumentEmbeddings(documentItem, type = "all") {
    if (!documentItem?.id) return;
    try {
      setIsLoadingEmbeddings(true);
      setEmbeddingError("");
      const query = new URLSearchParams({
        kind: type,
        limit: "5000",
      });
      const response = await fetch(`${API_BASE}/api/upload/documents/${documentItem.id}/embeddings?${query.toString()}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        const detail = await response.text();
        let message = detail || "Embeddinglarni olishda xatolik.";
        try {
          const parsed = JSON.parse(detail);
          if (parsed?.detail) {
            message = parsed.detail;
          }
        } catch {
          // plain text error
        }
        setEmbeddingError(message);
        return;
      }
      const payload = await response.json();
      setEmbeddingPayload(payload);
    } catch (error) {
      console.error("Embeddinglarni olishda xatolik:", error);
      setEmbeddingError("Embeddinglarni olishda xatolik.");
    } finally {
      setIsLoadingEmbeddings(false);
    }
  }

  function openEmbeddingsModal(documentItem) {
    setSelectedEmbeddingDoc(documentItem);
    setEmbeddingKind("all");
    setEmbeddingPayload(null);
    setEmbeddingError("");
    setIsEmbeddingModalOpen(true);
    loadDocumentEmbeddings(documentItem, "all");
  }

  function closeEmbeddingsModal() {
    setIsEmbeddingModalOpen(false);
    setEmbeddingError("");
  }

  function handleEmbeddingTypeChange(nextType) {
    setEmbeddingKind(nextType);
    if (selectedEmbeddingDoc?.id) {
      loadDocumentEmbeddings(selectedEmbeddingDoc, nextType);
    }
  }

  useEffect(() => {
    if (!isAuthReady || !isAuthenticated) {
      return;
    }
    loadDocuments();
    loadTaxonomy();
    loadUsers();
    loadQAHistory();
    const timer = window.setInterval(() => {
      loadDocuments();
      loadTaxonomy();
      loadUsers();
      loadQAHistory();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [isAuthReady, isAuthenticated]);

  useEffect(() => {
    if (!cornerMessage) return;
    const timer = window.setTimeout(() => setCornerMessage(""), 2500);
    return () => window.clearTimeout(timer);
  }, [cornerMessage]);

  const sortedDocuments = useMemo(() => {
    const data = [...documents];
    data.sort((a, b) => {
      const statusA = STATUS_ORDER[a.status] ?? 99;
      const statusB = STATUS_ORDER[b.status] ?? 99;
      if (statusA !== statusB) return statusA - statusB;
      return (a.code || "").localeCompare(b.code || "");
    });
    return data;
  }, [documents]);

  const dashboardCards = useMemo(() => {
    const total = dashboardStats.totalDocuments;
    const queued = dashboardStats.queuedDocuments;
    const processing = dashboardStats.processingDocuments;
    const done = dashboardStats.doneDocuments;
    const failed = dashboardStats.failedDocuments;
    const successRate = total ? Math.round((done / total) * 100) : 0;

    return [
      { title: "Jami hujjatlar", value: total, icon: "article", tone: "text-primary bg-primary/10", extra: `Navbatda: ${queued}` },
      { title: "Jarayonda", value: processing, icon: "sync", tone: "text-amber-500 bg-amber-500/10", extra: "Faol pipeline" },
      { title: "Yakunlangan", value: done, icon: "task_alt", tone: "text-emerald-500 bg-emerald-500/10", extra: `Muvaffaqiyat: ${successRate}%` },
      { title: "Xatolik", value: failed, icon: "error", tone: "text-rose-500 bg-rose-500/10", extra: "Qayta tekshirish kerak" },
    ];
  }, [dashboardStats]);

  const deepStatsCards = useMemo(() => {
    return [
      { title: "Bandlar soni", value: dashboardStats.totalClauses, icon: "segment", tone: "text-sky-500 bg-sky-500/10", extra: "Chunk qilingan matnlar" },
      { title: "Jadvallar soni", value: dashboardStats.totalTables, icon: "table_chart", tone: "text-indigo-500 bg-indigo-500/10", extra: "Normativ jadvallar" },
      { title: "Jadval qatorlari", value: dashboardStats.totalTableRows, icon: "view_list", tone: "text-violet-500 bg-violet-500/10", extra: "Qatorlar jami" },
      { title: "Band embedding", value: dashboardStats.clauseEmbeddings, icon: "data_object", tone: "text-cyan-500 bg-cyan-500/10", extra: "Clause vectorlari" },
      { title: "Qator embedding", value: dashboardStats.tableRowEmbeddings, icon: "dataset", tone: "text-emerald-500 bg-emerald-500/10", extra: "Table-row vectorlari" },
      { title: "Rasm embedding", value: dashboardStats.imageEmbeddings, icon: "image", tone: "text-orange-500 bg-orange-500/10", extra: "Image vectorlari" },
      { title: "Embedding qamrovi", value: `${dashboardStats.embeddingCoveragePercent}%`, icon: "radar", tone: "text-teal-500 bg-teal-500/10", extra: "Jadval qatoriga nisbatan" },
    ];
  }, [dashboardStats]);

  function openCreateDocumentModal() {
    setEditingDocument(null);
    setIsModalOpen(true);
  }

  function openCreateSectionModal() {
    setEditingSection(null);
    setIsSectionModalOpen(true);
  }

  function openCreateCategoryModal() {
    setEditingCategory(null);
    setIsCategoryModalOpen(true);
  }

  function closeDocumentModal() {
    setIsModalOpen(false);
    setEditingDocument(null);
  }

  function closeSectionModal() {
    setIsSectionModalOpen(false);
    setEditingSection(null);
  }

  function closeCategoryModal() {
    setIsCategoryModalOpen(false);
    setEditingCategory(null);
  }

  function openEditDocumentModal(item) {
    setEditingDocument(item);
    setIsModalOpen(true);
  }

  function openEditSectionModal(item) {
    setEditingSection(item);
    setIsSectionModalOpen(true);
  }

  function openEditCategoryModal(item) {
    setEditingCategory(item);
    setIsCategoryModalOpen(true);
  }

  const quickActionConfig = useMemo(() => {
    if (isSectionsPage) {
      return {
        icon: "account_tree",
        label: "Bo'lim yaratish",
        action: openCreateSectionModal,
      };
    }
    if (isCategoriesPage) {
      return {
        icon: "category",
        label: "Kategoriya yaratish",
        action: openCreateCategoryModal,
      };
    }
    if (isUsersPage) {
      return {
        icon: "refresh",
        label: "Foydalanuvchilarni yangilash",
        action: loadUsers,
      };
    }
    if (isQAPage) {
      return {
        icon: "forum",
        label: "Savol-javobni yangilash",
        action: loadQAHistory,
      };
    }
    return {
      icon: "upload_file",
      label: "Hujjat yaratish",
      action: openCreateDocumentModal,
    };
  }, [isCategoriesPage, isSectionsPage, isUsersPage, isQAPage]);

  async function refreshAll() {
    await Promise.all([loadDocuments(), loadTaxonomy()]);
  }

  if (!isAuthReady) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-950">
        <div className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow-sm dark:bg-slate-900 dark:text-slate-200">
          <span className="material-symbols-outlined text-base">hourglass_top</span>
          Tekshirilmoqda...
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-slate-100 dark:bg-slate-950 px-4 py-10">
        <div className="mx-auto w-full max-w-md overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
          <div className="h-24 bg-gradient-to-r from-primary/20 via-slate-100 to-primary/5 dark:from-primary/10 dark:via-slate-800 dark:to-primary/5" />
          <div className="px-7 py-8">
            <h1 className="text-3xl font-black text-slate-900 dark:text-slate-100">Tizimga kirish</h1>
            <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              Dashboard sahifalariga kirish uchun login va parol kiriting.
            </p>

            <form onSubmit={handleLoginSubmit} className="mt-6 space-y-4">
              <label className="block">
                <span className="mb-1 block text-sm font-semibold text-slate-700 dark:text-slate-300">
                  Login
                </span>
                <input
                  type="text"
                  name="username"
                  value={loginForm.username}
                  onChange={handleLoginFieldChange}
                  autoComplete="username"
                  placeholder="Loginni kiriting"
                  className="h-11 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm text-slate-700 outline-none transition focus:border-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </label>

              <label className="block">
                <span className="mb-1 block text-sm font-semibold text-slate-700 dark:text-slate-300">
                  Parol
                </span>
                <input
                  type="password"
                  name="password"
                  value={loginForm.password}
                  onChange={handleLoginFieldChange}
                  autoComplete="current-password"
                  placeholder="Parolni kiriting"
                  className="h-11 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm text-slate-700 outline-none transition focus:border-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </label>

              {loginError ? (
                <p className="text-sm font-semibold text-red-600 dark:text-red-400">{loginError}</p>
              ) : null}

              <button
                type="submit"
                className="mt-2 inline-flex h-11 w-full items-center justify-center rounded-xl bg-primary px-4 text-sm font-bold text-white transition hover:bg-primary/90"
              >
                Kirish
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-64 flex-shrink-0 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 flex flex-col">
        <div className="p-6 flex items-center gap-3">
          <div className="h-10 w-10 bg-primary rounded-lg flex items-center justify-center text-white">
            <span className="material-symbols-outlined text-2xl">construction</span>
          </div>
          <div className="flex flex-col">
            <h1 className="text-slate-900 dark:text-white font-bold text-lg leading-tight">SHNQ Admin</h1>
            <p className="text-slate-500 dark:text-slate-400 text-xs font-medium">Normativ portal</p>
          </div>
        </div>

        <nav className="flex-1 px-4 space-y-1 overflow-y-auto">
          <Link href="/" className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isDashboardPage ? "bg-primary/10 text-primary font-semibold" : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"}`}>
            <span className="material-symbols-outlined">dashboard</span>
            <span className="text-sm">Boshqaruv paneli</span>
          </Link>
          <Link href="/sections" className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isSectionsPage ? "bg-primary/10 text-primary font-semibold" : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"}`}>
            <span className="material-symbols-outlined">account_tree</span>
            <span className="text-sm">Bo'lim</span>
          </Link>
          <Link href="/categories" className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isCategoriesPage ? "bg-primary/10 text-primary font-semibold" : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"}`}>
            <span className="material-symbols-outlined">category</span>
            <span className="text-sm">Kategoriya</span>
          </Link>
          <Link href="/documents" className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isDocumentsPage ? "bg-primary/10 text-primary font-semibold" : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"}`}>
            <span className="material-symbols-outlined">description</span>
            <span className="text-sm">Hujjatlar</span>
          </Link>
          <Link href="/users" className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isUsersPage ? "bg-primary/10 text-primary font-semibold" : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"}`}>
            <span className="material-symbols-outlined">group</span>
            <span className="text-sm">Foydalanuvchilar</span>
          </Link>
          <Link href="/qa" className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isQAPage ? "bg-primary/10 text-primary font-semibold" : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"}`}>
            <span className="material-symbols-outlined">forum</span>
            <span className="text-sm">Savol-javob</span>
          </Link>
          <a className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors" href="#">
            <span className="material-symbols-outlined">monitoring</span>
            <span className="text-sm">Monitoring</span>
          </a>
          <a className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors" href="#">
            <span className="material-symbols-outlined">database</span>
            <span className="text-sm">Reyestr</span>
          </a>
          <a className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors" href="#">
            <span className="material-symbols-outlined">settings</span>
            <span className="text-sm">Sozlamalar</span>
          </a>
        </nav>

        <div className="p-4 border-t border-slate-200 dark:border-slate-800">
          <button onClick={quickActionConfig.action} className="w-full bg-primary hover:bg-primary/90 text-white font-bold py-2.5 rounded-lg flex items-center justify-center gap-2 transition-all shadow-sm">
            <span className="material-symbols-outlined text-lg">{quickActionConfig.icon}</span>
            <span className="text-sm">{quickActionConfig.label}</span>
          </button>
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="h-16 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between px-8 z-10">
          <div className="flex items-center gap-4 flex-1">
            <div className="relative w-96">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-xl">search</span>
              <input className="w-full pl-10 pr-4 py-2 bg-slate-100 dark:bg-slate-800 border-none rounded-lg focus:ring-2 focus:ring-primary text-sm placeholder:text-slate-500" placeholder="Hujjat yoki kod bo'yicha qidirish..." type="text" />
            </div>
          </div>

          <div className="flex items-center gap-4">
            <button onClick={toggleTheme} className="p-2 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors" title="Mavzu almashtirish">
              <span className="material-symbols-outlined">{theme === "dark" ? "light_mode" : "dark_mode"}</span>
            </button>
            <button
              onClick={handleLogout}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              title="Chiqish"
            >
              <span className="material-symbols-outlined text-[16px]">logout</span>
              Chiqish
            </button>
            <button className="p-2 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg relative transition-colors">
              <span className="material-symbols-outlined">notifications</span>
              <span className="absolute top-2 right-2.5 w-2 h-2 bg-red-500 rounded-full border-2 border-white dark:border-slate-900" />
            </button>
            <div className="h-8 w-px bg-slate-200 dark:bg-slate-700 mx-1" />
            <div className="flex items-center gap-3 pl-2">
              <div className="text-right hidden sm:block">
                <p className="text-sm font-bold leading-tight">Tizim foydalanuvchisi</p>
                <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Administrator</p>
              </div>
              <img alt="Foydalanuvchi" className="h-9 w-9 rounded-full object-cover border border-slate-200 dark:border-slate-700" src="https://lh3.googleusercontent.com/aida-public/AB6AXuAbnv0siY5M_dBogQYyBJQQFIU6k4EHPwAc9-pz9HWIv6npXwrMiZeR37HfcK2N_9VZIScnuymF6CY2DCdDcoKvGDcMdQ3iOzQvp6KYnmIEZ82CtgKDgrBzdLgBhVoKji-UHBaBezPxoNAnDkIoYz6rlzKyKoyIqZlmKEV3KAy2vv0w0Lbi12hVvbhP1pmxzrTf-5VzE4LgyTLfUKMp3a39lUfH078Y2mR1xLbIVgknZ5faaYqlhaVvtxhkYD6T4_t513ouZk_CGy3W" />
            </div>
          </div>
        </header>

        {isDocumentsPage ? (
          <HujjatlarSahifasi
            documents={sortedDocuments}
            onOpenModal={openCreateDocumentModal}
            onRefresh={refreshDocuments}
            onOpenEmbeddings={openEmbeddingsModal}
            onEdit={openEditDocumentModal}
            onDelete={deleteDocument}
          />
        ) : isSectionsPage ? (
          <BolimlarSahifasi
            sections={sections}
            categories={categories}
            onOpenModal={openCreateSectionModal}
            onRefresh={loadTaxonomy}
            onEdit={openEditSectionModal}
            onDelete={deleteSection}
          />
        ) : isCategoriesPage ? (
          <KategoriyalarSahifasi
            categories={categories}
            documents={sortedDocuments}
            onOpenModal={openCreateCategoryModal}
            onRefresh={refreshAll}
            onEdit={openEditCategoryModal}
            onDelete={deleteCategory}
          />
        ) : isUsersPage ? (
          <FoydalanuvchilarSahifasi
            users={users}
            onRefresh={loadUsers}
            onDelete={deleteUser}
          />
        ) : isQAPage ? (
          <SavolJavobSahifasi
            qaItems={qaHistory}
            onRefresh={loadQAHistory}
          />
        ) : (
          <div className="flex-1 overflow-y-auto p-8 space-y-8 bg-background-light dark:bg-background-dark">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-extrabold tracking-tight">Boshqaruv paneli</h2>
                <nav className="flex text-sm text-slate-500 mt-1 font-medium">
                  <a className="hover:text-primary" href="#">Admin</a>
                  <span className="mx-2 text-slate-400">/</span>
                  <span className="text-slate-900 dark:text-slate-100">Boshqaruv paneli</span>
                </nav>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {dashboardCards.map((card) => (
                <div key={card.title} className="bg-white dark:bg-slate-900 p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
                  <div className="flex items-center justify-between mb-4">
                    <div className={`p-2 rounded-lg ${card.tone}`}><span className="material-symbols-outlined">{card.icon}</span></div>
                  </div>
                  <p className="text-slate-500 dark:text-slate-400 text-sm font-medium">{card.title}</p>
                  <h3 className="text-3xl font-extrabold mt-1">{card.value}</h3>
                  <p className="text-[11px] mt-4 font-semibold text-slate-500 dark:text-slate-400">{card.extra}</p>
                </div>
              ))}
            </div>

            <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-6">
              <div className="flex items-center justify-between mb-4">
                <h4 className="font-bold text-lg">Texnik statistika</h4>
                <Link href="/documents" className="text-sm font-semibold text-primary hover:underline">Hujjatlar sahifasi</Link>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                {deepStatsCards.map((card) => (
                  <div key={card.title} className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 p-4">
                    <div className="flex items-center gap-3">
                      <div className={`p-2 rounded-lg ${card.tone}`}>
                        <span className="material-symbols-outlined text-[18px]">{card.icon}</span>
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{card.title}</p>
                        <p className="text-xl font-extrabold text-slate-900 dark:text-slate-100">{card.value}</p>
                      </div>
                    </div>
                    <p className="text-[11px] mt-3 font-medium text-slate-500 dark:text-slate-400">{card.extra}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>

      <HujjatModal
        open={isModalOpen}
        onClose={closeDocumentModal}
        onSubmit={upsertDocument}
        categories={categories}
        sections={sections}
        mode={editingDocument ? "edit" : "create"}
        initialData={editingDocument}
      />
      <BolimModal
        open={isSectionModalOpen}
        onClose={closeSectionModal}
        onSubmit={upsertSection}
        mode={editingSection ? "edit" : "create"}
        initialData={editingSection}
      />
      <KategoriyaModal
        open={isCategoryModalOpen}
        onClose={closeCategoryModal}
        onSubmit={upsertCategory}
        sections={sections}
        mode={editingCategory ? "edit" : "create"}
        initialData={editingCategory}
      />
      <EmbeddingTekshiruvModal
        open={isEmbeddingModalOpen}
        onClose={closeEmbeddingsModal}
        documentItem={selectedEmbeddingDoc}
        data={embeddingPayload}
        isLoading={isLoadingEmbeddings}
        errorMessage={embeddingError}
        activeType={embeddingKind}
        onTypeChange={handleEmbeddingTypeChange}
        onRefresh={() => {
          if (selectedEmbeddingDoc?.id) {
            loadDocumentEmbeddings(selectedEmbeddingDoc, embeddingKind);
          }
        }}
      />
      {isLoadingDocs ? (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 rounded-lg bg-slate-900 text-white px-3 py-1.5 text-xs">
          Ma'lumotlar yangilanmoqda...
        </div>
      ) : null}
      {cornerMessage ? (
        <div className={`fixed top-4 right-4 z-40 rounded-lg text-white px-4 py-2 text-sm shadow-lg ${cornerType === "success" ? "bg-emerald-600" : "bg-red-600"}`}>
          {cornerMessage}
        </div>
      ) : null}
    </div>
  );
}

