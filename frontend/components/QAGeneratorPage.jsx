"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

function formatDate(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("uz-UZ");
  } catch {
    return value;
  }
}

function statusTone(status) {
  if (status === "approved" || status === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "rejected" || status === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  if (status === "running") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function draftStatusTone(status) {
  if (status === "approved") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (status === "rejected") {
    return "bg-rose-100 text-rose-700";
  }
  return "bg-slate-100 text-slate-600";
}

async function parseResponse(response, fallback) {
  const text = await response.text();
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text);
    return parsed?.detail || fallback;
  } catch {
    return text;
  }
}

function DraftDetails({ draft, onApprove, onReject, onPreviewTable }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-950/50">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Batafsil javob</div>
          <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700 dark:text-slate-200">
            {draft.answer}
          </div>
          <div className="mt-4 text-xs font-bold uppercase tracking-wide text-slate-400">Source excerpt</div>
          <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
            {draft.source_excerpt}
          </div>
        </div>
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Manba</div>
            <div className="mt-2 text-sm font-semibold text-slate-800 dark:text-slate-100">{draft.chapter_title || "-"}</div>
            <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{draft.clause_number || "Band ko'rsatilmagan"}</div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{draft.source_anchor || "Anchor yo'q"}</div>
            <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">{formatDate(draft.created_at)}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Amallar</div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onApprove(draft.id)}
                className="inline-flex items-center rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white"
              >
                Approve
              </button>
              <button
                type="button"
                onClick={() => onReject(draft.id)}
                className="inline-flex items-center rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-bold text-rose-700"
              >
                Reject
              </button>
              {draft.table_id ? (
                <button
                  type="button"
                  onClick={() => onPreviewTable(draft.table_id)}
                  className="inline-flex items-center rounded-lg border border-primary/20 bg-primary/10 px-3 py-2 text-xs font-bold text-primary"
                >
                  Jadvalni ko'rsatish
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function GeneratorDrawer({
  open,
  query,
  onQueryChange,
  searchItems,
  selectedDocument,
  context,
  form,
  isSearching,
  isLoadingContext,
  isGenerating,
  onClose,
  onSelectDocument,
  onFormChange,
  onGenerate,
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <button
        type="button"
        onClick={onClose}
        className="flex-1 bg-slate-950/35 backdrop-blur-[1px]"
        aria-label="Drawer ni yopish"
      />
      <aside className="relative h-full w-full max-w-[520px] overflow-y-auto border-l border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950">
        <div className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-6 py-5 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-[11px] font-black uppercase tracking-[0.25em] text-primary">Yangi generator</div>
              <h3 className="mt-1 text-2xl font-black text-slate-900 dark:text-slate-50">SHNQ generator paneli</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                SHNQ toping, parametr bering va generator job yarating.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 text-slate-500 transition hover:border-slate-300 hover:text-slate-700 dark:border-slate-700 dark:text-slate-300"
            >
              <span className="material-symbols-outlined text-[20px]">close</span>
            </button>
          </div>
        </div>

        <div className="space-y-6 px-6 py-6">
          <section className="rounded-2xl border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900">
            <div className="text-sm font-bold text-slate-800 dark:text-slate-100">SHNQ qidirish</div>
            <div className="mt-3 relative">
              <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-slate-400">search</span>
              <input
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="Masalan: SHNQ 2.08 yoki hujjat nomi"
                className="h-12 w-full rounded-xl border border-slate-200 bg-white pl-12 pr-4 text-sm text-slate-700 outline-none focus:border-primary dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
            </div>
            <div className="mt-3 text-xs font-medium text-slate-500 dark:text-slate-400">
              {isSearching ? "Qidirilmoqda..." : `${searchItems.length} ta natija`}
            </div>
            <div className="mt-4 max-h-[300px] space-y-3 overflow-auto pr-1">
              {searchItems.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 px-4 py-5 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  Qidiruv natijasi shu yerda chiqadi.
                </div>
              ) : null}
              {searchItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelectDocument(item)}
                  className={`w-full rounded-2xl border px-4 py-4 text-left transition ${
                    selectedDocument?.id === item.id
                      ? "border-primary bg-primary/5"
                      : "border-slate-200 bg-white hover:border-primary/40 dark:border-slate-700 dark:bg-slate-950"
                  }`}
                >
                  <div className="text-sm font-black text-slate-900 dark:text-slate-50">{item.code}</div>
                  <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.title}</div>
                  <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                    <span>{item.clause_count} band</span>
                    <span>{item.table_count} jadval</span>
                    <span>{item.approved_count} approved QA</span>
                  </div>
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-bold text-slate-800 dark:text-slate-100">Tanlangan SHNQ</div>
                <div className="mt-1 text-lg font-black text-slate-900 dark:text-slate-50">{selectedDocument?.code || "-"}</div>
                <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{selectedDocument?.title || "SHNQ hali tanlanmagan"}</div>
              </div>
              {isLoadingContext ? <div className="text-xs font-semibold text-slate-400">Yuklanmoqda...</div> : null}
            </div>
            {context ? (
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-950">
                  <div className="text-slate-500">Bandlar</div>
                  <div className="mt-1 text-xl font-black text-slate-900 dark:text-slate-50">{context.clause_count}</div>
                </div>
                <div className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-950">
                  <div className="text-slate-500">Jadvallar</div>
                  <div className="mt-1 text-xl font-black text-slate-900 dark:text-slate-50">{context.table_count}</div>
                </div>
                <div className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-950">
                  <div className="text-slate-500">Approved QA</div>
                  <div className="mt-1 text-xl font-black text-slate-900 dark:text-slate-50">{context.approved_count}</div>
                </div>
                <div className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-950">
                  <div className="text-slate-500">Lex link</div>
                  <div className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-50">{context.lex_url || "-"}</div>
                </div>
              </div>
            ) : null}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-bold text-slate-800 dark:text-slate-100">Generator parametrlari</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">Model: gpt-5-mini</div>
              </div>
            </div>
            <label className="mt-4 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Nechta savol kerak
              <input
                type="number"
                min="1"
                max="100"
                value={form.requested_count}
                onChange={(event) => onFormChange({ requested_count: event.target.value })}
                className="mt-2 h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm text-slate-700 outline-none focus:border-primary dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
            </label>
            <label className="mt-4 flex items-center gap-3 text-sm font-medium text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={form.include_table_questions}
                onChange={(event) => onFormChange({ include_table_questions: event.target.checked })}
                className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary"
              />
              Jadvalga tayangan savollarni ham yaratish
            </label>
            <button
              type="button"
              onClick={onGenerate}
              disabled={!selectedDocument || isGenerating}
              className="mt-5 inline-flex w-full items-center justify-center rounded-xl bg-primary px-4 py-3 text-sm font-bold text-white transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isGenerating ? "Generator ishga tushmoqda..." : "Generator job yaratish"}
            </button>
          </section>
        </div>
      </aside>
    </div>
  );
}

export default function QAGeneratorPage({ apiBase }) {
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchItems, setSearchItems] = useState([]);
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [context, setContext] = useState(null);
  const [form, setForm] = useState({ requested_count: 12, include_table_questions: true });
  const [jobs, setJobs] = useState([]);
  const [expandedJobId, setExpandedJobId] = useState("");
  const [draftsByJob, setDraftsByJob] = useState({});
  const [loadingDraftJobId, setLoadingDraftJobId] = useState("");
  const [selectedDraftIdsByJob, setSelectedDraftIdsByJob] = useState({});
  const [expandedDraftIdsByJob, setExpandedDraftIdsByJob] = useState({});
  const [tablePreview, setTablePreview] = useState(null);
  const [notice, setNotice] = useState("");
  const [noticeType, setNoticeType] = useState("success");
  const [isSearching, setIsSearching] = useState(false);
  const [isLoadingContext, setIsLoadingContext] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isLoadingJobs, setIsLoadingJobs] = useState(false);
  const [isBulkApproving, setIsBulkApproving] = useState(false);

  const hasRunningJob = useMemo(
    () => jobs.some((job) => job.status === "queued" || job.status === "running"),
    [jobs]
  );

  const stats = useMemo(() => {
    return {
      totalJobs: jobs.length,
      runningJobs: jobs.filter((job) => job.status === "queued" || job.status === "running").length,
      generated: jobs.reduce((sum, job) => sum + Number(job.generated_count || 0), 0),
      approved: jobs.reduce((sum, job) => sum + Number(job.approved_count || 0), 0),
    };
  }, [jobs]);

  const orderedJobs = useMemo(() => {
    const items = [...jobs];
    items.sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
    return items;
  }, [jobs]);

  useEffect(() => {
    loadJobs();
  }, []);

  useEffect(() => {
    if (!hasRunningJob) return undefined;
    const timer = window.setInterval(() => {
      loadJobs().catch(() => {});
      if (expandedJobId) {
        loadDrafts(expandedJobId).catch(() => {});
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [expandedJobId, hasRunningJob]);

  useEffect(() => {
    if (!query.trim() || !isDrawerOpen) {
      setSearchItems([]);
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      try {
        setIsSearching(true);
        const params = new URLSearchParams({ query: query.trim(), limit: "12" });
        const response = await fetch(`${apiBase}/api/admin/qa-generator/documents?${params.toString()}`, {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(await parseResponse(response, "SHNQ qidirishda xatolik"));
        }
        const data = await response.json();
        setSearchItems(Array.isArray(data) ? data : []);
      } catch (error) {
        setNoticeType("error");
        setNotice(error?.message || "SHNQ qidirishda xatolik");
      } finally {
        setIsSearching(false);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [apiBase, isDrawerOpen, query]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(""), 3500);
    return () => window.clearTimeout(timer);
  }, [notice]);

  async function loadJobs() {
    try {
      setIsLoadingJobs(true);
      const params = new URLSearchParams({ limit: "100" });
      const response = await fetch(`${apiBase}/api/admin/qa-generator/jobs?${params.toString()}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Generator joblarini olishda xatolik"));
      }
      const data = await response.json();
      setJobs(Array.isArray(data?.items) ? data.items : []);
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Generator joblarini olishda xatolik");
    } finally {
      setIsLoadingJobs(false);
    }
  }

  async function loadContext(documentId) {
    try {
      setIsLoadingContext(true);
      const response = await fetch(`${apiBase}/api/admin/qa-generator/documents/${documentId}/context`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "SHNQ ma'lumotini olishda xatolik"));
      }
      setContext(await response.json());
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "SHNQ ma'lumotini olishda xatolik");
    } finally {
      setIsLoadingContext(false);
    }
  }

  async function loadDrafts(jobId) {
    try {
      setLoadingDraftJobId(jobId);
      const params = new URLSearchParams({ job_id: jobId, limit: "1000" });
      const response = await fetch(`${apiBase}/api/admin/qa-generator/drafts?${params.toString()}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Draftlarni olishda xatolik"));
      }
      const data = await response.json();
      setDraftsByJob((prev) => ({
        ...prev,
        [jobId]: Array.isArray(data?.items) ? data.items : [],
      }));
    } finally {
      setLoadingDraftJobId("");
    }
  }

  async function handleSelectDocument(item) {
    setSelectedDocument(item);
    await loadContext(item.id);
  }

  async function handleGenerate() {
    if (!selectedDocument?.id) {
      setNoticeType("error");
      setNotice("Avval SHNQ tanlang");
      return;
    }
    try {
      setIsGenerating(true);
      const response = await fetch(`${apiBase}/api/admin/qa-generator/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: selectedDocument.id,
          requested_count: Number(form.requested_count || 0),
          include_table_questions: Boolean(form.include_table_questions),
        }),
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Generator job yaratishda xatolik"));
      }
      await loadJobs();
      setIsDrawerOpen(false);
      setNoticeType("success");
      setNotice("Generator job yaratildi");
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Generator job yaratishda xatolik");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleToggleJob(job) {
    if (expandedJobId === job.id) {
      setExpandedJobId("");
      setTablePreview(null);
      return;
    }
    setExpandedJobId(job.id);
    setTablePreview(null);
    if (!draftsByJob[job.id]) {
      await loadDrafts(job.id);
    }
  }

  function updateSelectedDraftIds(jobId, updater) {
    setSelectedDraftIdsByJob((prev) => ({
      ...prev,
      [jobId]: updater(prev[jobId] || []),
    }));
  }

  function toggleDraftSelection(jobId, draftId, checked) {
    updateSelectedDraftIds(jobId, (items) => {
      if (checked) {
        return items.includes(draftId) ? items : [...items, draftId];
      }
      return items.filter((item) => item !== draftId);
    });
  }

  function toggleDraftExpansion(jobId, draftId) {
    setExpandedDraftIdsByJob((prev) => ({
      ...prev,
      [jobId]: prev[jobId] === draftId ? "" : draftId,
    }));
  }

  async function approveDraft(jobId, draftId) {
    try {
      const response = await fetch(`${apiBase}/api/admin/qa-generator/drafts/${draftId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Draftni approve qilishda xatolik"));
      }
      await Promise.all([loadJobs(), loadDrafts(jobId)]);
      updateSelectedDraftIds(jobId, (items) => items.filter((item) => item !== draftId));
      setNoticeType("success");
      setNotice("Draft approved qilindi");
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Draftni approve qilishda xatolik");
    }
  }

  async function rejectDraft(jobId, draftId) {
    try {
      const response = await fetch(`${apiBase}/api/admin/qa-generator/drafts/${draftId}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Draftni reject qilishda xatolik"));
      }
      await loadDrafts(jobId);
      updateSelectedDraftIds(jobId, (items) => items.filter((item) => item !== draftId));
      setNoticeType("success");
      setNotice("Draft reject qilindi");
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Draftni reject qilishda xatolik");
    }
  }

  async function bulkApprove(jobId) {
    const ids = selectedDraftIdsByJob[jobId] || [];
    if (ids.length === 0) return;
    try {
      setIsBulkApproving(true);
      const response = await fetch(`${apiBase}/api/admin/qa-generator/drafts/bulk-approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft_ids: ids }),
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Tanlangan draftlarni approve qilishda xatolik"));
      }
      await Promise.all([loadJobs(), loadDrafts(jobId)]);
      setSelectedDraftIdsByJob((prev) => ({ ...prev, [jobId]: [] }));
      setNoticeType("success");
      setNotice("Tanlangan draftlar approve qilindi");
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Tanlangan draftlarni approve qilishda xatolik");
    } finally {
      setIsBulkApproving(false);
    }
  }

  async function openTablePreview(tableId) {
    try {
      const response = await fetch(`${apiBase}/api/admin/qa-generator/tables/${tableId}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Jadvalni olishda xatolik"));
      }
      setTablePreview(await response.json());
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Jadvalni olishda xatolik");
    }
  }

  return (
    <div className="flex-1 overflow-y-auto bg-background-light p-8 dark:bg-background-dark">
      <div className="mx-auto max-w-[1400px] space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[11px] font-black uppercase tracking-[0.28em] text-primary">AI generator</div>
            <h2 className="mt-2 text-3xl font-black tracking-tight text-slate-950 dark:text-slate-50">
              SHNQ generator monitoring
            </h2>
            <p className="mt-2 max-w-3xl text-sm text-slate-500 dark:text-slate-400">
              Bu yerda generator joblar jadvali turadi. Row ustiga bossangiz, shu SHNQ bo'yicha generated savollar,
              qisqa javoblar va jadvalga bog'langan natijalar pastda ochiladi.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden rounded-2xl border border-slate-200 bg-white px-4 py-3 text-right shadow-sm lg:block dark:border-slate-800 dark:bg-slate-900">
              <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Model</div>
              <div className="mt-1 text-lg font-black text-slate-900 dark:text-slate-50">gpt-5-mini</div>
            </div>
            <button
              type="button"
              onClick={() => setIsDrawerOpen(true)}
              className="inline-flex items-center gap-2 rounded-2xl bg-primary px-5 py-3 text-sm font-bold text-white shadow-lg shadow-primary/20 transition hover:bg-primary/90"
            >
              <span className="material-symbols-outlined text-[18px]">auto_awesome</span>
              SHNQ generator qilish
            </button>
          </div>
        </div>

        {notice ? (
          <div
            className={`rounded-2xl border px-4 py-3 text-sm font-semibold ${
              noticeType === "error"
                ? "border-rose-200 bg-rose-50 text-rose-700"
                : "border-emerald-200 bg-emerald-50 text-emerald-700"
            }`}
          >
            {notice}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Jami job</div>
            <div className="mt-2 text-3xl font-black text-slate-900 dark:text-slate-50">{stats.totalJobs}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Jarayonda</div>
            <div className="mt-2 text-3xl font-black text-amber-600">{stats.runningJobs}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Generated</div>
            <div className="mt-2 text-3xl font-black text-slate-900 dark:text-slate-50">{stats.generated}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Approved</div>
            <div className="mt-2 text-3xl font-black text-emerald-600">{stats.approved}</div>
          </div>
        </div>

        <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-5 dark:border-slate-800">
            <div>
              <div className="text-lg font-black text-slate-900 dark:text-slate-50">Generator joblar jadvali</div>
              <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                SHNQ kodi, nomi, nechta savol generatsiya qilingani va statuslar shu yerda ko'rinadi.
              </div>
            </div>
            {isLoadingJobs ? (
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Yangilanmoqda...</div>
            ) : null}
          </div>

          {orderedJobs.length === 0 ? (
            <div className="px-6 py-14 text-center">
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 text-primary">
                <span className="material-symbols-outlined text-[28px]">auto_awesome</span>
              </div>
              <div className="mt-4 text-lg font-black text-slate-900 dark:text-slate-50">Generator job hali yaratilmagan</div>
              <div className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                Burchakdagi tugma orqali yangi SHNQ generator job oching.
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse">
                <thead className="bg-slate-50 dark:bg-slate-950/70">
                  <tr className="text-left text-[11px] font-black uppercase tracking-[0.18em] text-slate-400">
                    <th className="w-14 px-5 py-4"></th>
                    <th className="px-5 py-4">SHNQ raqami</th>
                    <th className="px-5 py-4">SHNQ nomi</th>
                    <th className="px-5 py-4">Requested</th>
                    <th className="px-5 py-4">Generated</th>
                    <th className="px-5 py-4">Approved</th>
                    <th className="px-5 py-4">Status</th>
                    <th className="px-5 py-4">Yaratilgan</th>
                  </tr>
                </thead>
                <tbody>
                  {orderedJobs.map((job) => {
                    const isExpanded = expandedJobId === job.id;
                    const drafts = draftsByJob[job.id] || [];
                    const selectedDraftIds = selectedDraftIdsByJob[job.id] || [];
                    const expandedDraftId = expandedDraftIdsByJob[job.id] || "";
                    const isDraftLoading = loadingDraftJobId === job.id;

                    return (
                      <Fragment key={job.id}>
                        <tr
                          className="cursor-pointer border-t border-slate-200 transition hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-950/60"
                          onClick={() => handleToggleJob(job)}
                        >
                          <td className="px-5 py-4">
                            <span className="material-symbols-outlined text-slate-500">
                              {isExpanded ? "keyboard_arrow_down" : "chevron_right"}
                            </span>
                          </td>
                          <td className="px-5 py-4 text-sm font-black text-slate-900 dark:text-slate-50">{job.document_code}</td>
                          <td className="px-5 py-4 text-sm text-slate-600 dark:text-slate-300">{job.document_title}</td>
                          <td className="px-5 py-4 text-sm font-semibold text-slate-700 dark:text-slate-200">{job.requested_count}</td>
                          <td className="px-5 py-4 text-sm font-semibold text-slate-700 dark:text-slate-200">{job.generated_count}</td>
                          <td className="px-5 py-4 text-sm font-semibold text-emerald-600">{job.approved_count}</td>
                          <td className="px-5 py-4">
                            <span className={`inline-flex rounded-full border px-3 py-1 text-[11px] font-black uppercase ${statusTone(job.status)}`}>
                              {job.status}
                            </span>
                          </td>
                          <td className="px-5 py-4 text-xs font-medium text-slate-500 dark:text-slate-400">{formatDate(job.created_at)}</td>
                        </tr>
                        {isExpanded ? (
                          <tr className="border-t border-slate-200 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-950/40">
                            <td colSpan={8} className="px-5 py-5">
                              <div className="space-y-4">
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                  <div>
                                    <div className="text-sm font-black text-slate-900 dark:text-slate-50">Generated savollar</div>
                                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                      Savol-javoblar, qisqa javoblar va table bog'lanishi shu yerda ko'rinadi.
                                    </div>
                                  </div>
                                  {selectedDraftIds.length > 0 ? (
                                    <button
                                      type="button"
                                      onClick={() => bulkApprove(job.id)}
                                      disabled={isBulkApproving}
                                      className="inline-flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-bold text-emerald-700"
                                    >
                                      <span className="material-symbols-outlined text-[16px]">done_all</span>
                                      {isBulkApproving ? "Approve..." : `Tanlanganlarni approve (${selectedDraftIds.length})`}
                                    </button>
                                  ) : null}
                                </div>

                                {job.error_message ? (
                                  <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">
                                    {job.error_message}
                                  </div>
                                ) : null}

                                {isDraftLoading ? (
                                  <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                                    Draftlar yuklanmoqda...
                                  </div>
                                ) : drafts.length === 0 ? (
                                  <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                                    Bu job bo'yicha draft topilmadi.
                                  </div>
                                ) : (
                                  <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
                                    <div className="overflow-x-auto">
                                      <table className="min-w-full border-collapse">
                                        <thead className="bg-slate-50 dark:bg-slate-950/70">
                                          <tr className="text-left text-[11px] font-black uppercase tracking-[0.18em] text-slate-400">
                                            <th className="w-14 px-4 py-3"></th>
                                            <th className="w-12 px-4 py-3"></th>
                                            <th className="px-4 py-3">Savol</th>
                                            <th className="px-4 py-3">Qisqa javob</th>
                                            <th className="px-4 py-3">Manba</th>
                                            <th className="px-4 py-3">Jadval</th>
                                            <th className="px-4 py-3">Status</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {drafts.map((draft) => {
                                            const isDraftExpanded = expandedDraftId === draft.id;
                                            return (
                                              <Fragment key={draft.id}>
                                                <tr
                                                  className="border-t border-slate-200 align-top transition hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-950/50"
                                                >
                                                  <td className="px-4 py-4">
                                                    <button
                                                      type="button"
                                                      onClick={() => toggleDraftExpansion(job.id, draft.id)}
                                                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 text-slate-500 dark:border-slate-700"
                                                    >
                                                      <span className="material-symbols-outlined text-[18px]">
                                                        {isDraftExpanded ? "keyboard_arrow_down" : "chevron_right"}
                                                      </span>
                                                    </button>
                                                  </td>
                                                  <td className="px-4 py-4">
                                                    <input
                                                      type="checkbox"
                                                      checked={selectedDraftIds.includes(draft.id)}
                                                      onChange={(event) => toggleDraftSelection(job.id, draft.id, event.target.checked)}
                                                      className="mt-1 h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary"
                                                    />
                                                  </td>
                                                  <td className="px-4 py-4 text-sm font-semibold text-slate-800 dark:text-slate-100">{draft.question}</td>
                                                  <td className="px-4 py-4 text-sm text-slate-600 dark:text-slate-300">{draft.short_answer}</td>
                                                  <td className="px-4 py-4 text-xs font-medium text-slate-500 dark:text-slate-400">
                                                    <div>{draft.chapter_title || "-"}</div>
                                                    <div className="mt-1">{draft.clause_number || "band yo'q"}</div>
                                                  </td>
                                                  <td className="px-4 py-4 text-xs font-semibold text-slate-600 dark:text-slate-300">
                                                    {draft.table_number ? `Jadval ${draft.table_number}` : "-"}
                                                  </td>
                                                  <td className="px-4 py-4">
                                                    <span className={`inline-flex rounded-full px-3 py-1 text-[11px] font-black uppercase ${draftStatusTone(draft.status)}`}>
                                                      {draft.status}
                                                    </span>
                                                  </td>
                                                </tr>
                                                {isDraftExpanded ? (
                                                  <tr className="border-t border-slate-200 dark:border-slate-800">
                                                    <td colSpan={7} className="px-4 py-4">
                                                      <DraftDetails
                                                        draft={draft}
                                                        onApprove={(draftId) => approveDraft(job.id, draftId)}
                                                        onReject={(draftId) => rejectDraft(job.id, draftId)}
                                                        onPreviewTable={openTablePreview}
                                                      />
                                                    </td>
                                                  </tr>
                                                ) : null}
                                              </Fragment>
                                            );
                                          })}
                                        </tbody>
                                      </table>
                                    </div>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={() => setIsDrawerOpen(true)}
        className="fixed bottom-8 right-8 z-30 inline-flex items-center gap-3 rounded-full bg-slate-950 px-5 py-3 text-sm font-bold text-white shadow-2xl transition hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100"
      >
        <span className="material-symbols-outlined text-[18px]">auto_awesome</span>
        SHNQ generator qilish
      </button>

      {tablePreview ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-5">
          <div className="max-h-[88vh] w-full max-w-[1180px] overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5 dark:border-slate-800">
              <div>
                <div className="text-[11px] font-black uppercase tracking-[0.22em] text-primary">Jadval preview</div>
                <div className="mt-2 text-xl font-black text-slate-900 dark:text-slate-50">
                  {tablePreview.document_code} / Jadval {tablePreview.table_number}
                </div>
                <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{tablePreview.title || "-"}</div>
              </div>
              <button
                type="button"
                onClick={() => setTablePreview(null)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 text-slate-500 dark:border-slate-700"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>
            <div className="max-h-[calc(88vh-96px)] overflow-auto bg-slate-50 p-6 dark:bg-slate-950">
              {tablePreview.html ? (
                <div className="min-w-[760px] rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                  <div dangerouslySetInnerHTML={{ __html: tablePreview.html }} />
                </div>
              ) : (
                <pre className="whitespace-pre-wrap rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
                  {tablePreview.markdown || "Jadval matni topilmadi."}
                </pre>
              )}
            </div>
          </div>
        </div>
      ) : null}

      <GeneratorDrawer
        open={isDrawerOpen}
        query={query}
        onQueryChange={setQuery}
        searchItems={searchItems}
        selectedDocument={selectedDocument}
        context={context}
        form={form}
        isSearching={isSearching}
        isLoadingContext={isLoadingContext}
        isGenerating={isGenerating}
        onClose={() => setIsDrawerOpen(false)}
        onSelectDocument={handleSelectDocument}
        onFormChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))}
        onGenerate={handleGenerate}
      />
    </div>
  );
}
