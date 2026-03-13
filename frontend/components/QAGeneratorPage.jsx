"use client";

import { useEffect, useMemo, useState } from "react";

function formatDate(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("uz-UZ");
  } catch {
    return value;
  }
}

function statusTone(status) {
  if (status === "approved" || status === "completed") return "text-emerald-600 bg-emerald-50 border-emerald-200";
  if (status === "rejected" || status === "failed") return "text-rose-600 bg-rose-50 border-rose-200";
  if (status === "running") return "text-amber-600 bg-amber-50 border-amber-200";
  return "text-slate-600 bg-slate-50 border-slate-200";
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

export default function QAGeneratorPage({ apiBase }) {
  const [query, setQuery] = useState("");
  const [searchItems, setSearchItems] = useState([]);
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [context, setContext] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [selectedDraftIds, setSelectedDraftIds] = useState([]);
  const [form, setForm] = useState({ requested_count: 12, include_table_questions: true });
  const [tablePreview, setTablePreview] = useState(null);
  const [notice, setNotice] = useState("");
  const [noticeType, setNoticeType] = useState("success");
  const [isSearching, setIsSearching] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isLoadingContext, setIsLoadingContext] = useState(false);
  const [isLoadingDrafts, setIsLoadingDrafts] = useState(false);
  const [isBulkApproving, setIsBulkApproving] = useState(false);

  const activeJob = jobs[0] || null;
  const isJobRunning = activeJob && (activeJob.status === "queued" || activeJob.status === "running");

  useEffect(() => {
    if (!query.trim()) {
      setSearchItems([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        setIsSearching(true);
        const params = new URLSearchParams({ query: query.trim(), limit: "12" });
        const response = await fetch(`${apiBase}/api/admin/qa-generator/documents?${params.toString()}`, { cache: "no-store" });
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
  }, [apiBase, query]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 3200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  async function loadContext(documentId) {
    try {
      setIsLoadingContext(true);
      const response = await fetch(`${apiBase}/api/admin/qa-generator/documents/${documentId}/context`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Generator kontekstini olishda xatolik"));
      }
      const data = await response.json();
      setContext(data);
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Generator kontekstini olishda xatolik");
    } finally {
      setIsLoadingContext(false);
    }
  }

  async function loadJobs(documentId) {
    const params = new URLSearchParams({ document_id: documentId, limit: "20" });
    const response = await fetch(`${apiBase}/api/admin/qa-generator/jobs?${params.toString()}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(await parseResponse(response, "Joblarni olishda xatolik"));
    }
    const data = await response.json();
    setJobs(Array.isArray(data?.items) ? data.items : []);
  }

  async function loadDrafts(documentId) {
    try {
      setIsLoadingDrafts(true);
      const params = new URLSearchParams({ document_id: documentId, limit: "1000" });
      const response = await fetch(`${apiBase}/api/admin/qa-generator/drafts?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Draftlarni olishda xatolik"));
      }
      const data = await response.json();
      setDrafts(Array.isArray(data?.items) ? data.items : []);
    } finally {
      setIsLoadingDrafts(false);
    }
  }

  async function selectDocument(item) {
    setSelectedDocument(item);
    setTablePreview(null);
    setSelectedDraftIds([]);
    try {
      await Promise.all([loadContext(item.id), loadJobs(item.id), loadDrafts(item.id)]);
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "SHNQ ma'lumotini yuklashda xatolik");
    }
  }

  useEffect(() => {
    if (!selectedDocument?.id || !isJobRunning) return undefined;
    const timer = window.setInterval(() => {
      loadJobs(selectedDocument.id).catch(() => {});
      loadDrafts(selectedDocument.id).catch(() => {});
      loadContext(selectedDocument.id).catch(() => {});
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedDocument?.id, isJobRunning]);

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
      await Promise.all([loadJobs(selectedDocument.id), loadDrafts(selectedDocument.id), loadContext(selectedDocument.id)]);
      setNoticeType("success");
      setNotice("AI generator ishga tushdi");
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Generator job yaratishda xatolik");
    } finally {
      setIsGenerating(false);
    }
  }

  async function approveDraft(draftId) {
    try {
      const response = await fetch(`${apiBase}/api/admin/qa-generator/drafts/${draftId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Draftni approve qilishda xatolik"));
      }
      await Promise.all([loadDrafts(selectedDocument.id), loadContext(selectedDocument.id), loadJobs(selectedDocument.id)]);
      setNoticeType("success");
      setNotice("Draft approved qilindi");
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Draftni approve qilishda xatolik");
    }
  }

  async function rejectDraft(draftId) {
    try {
      const response = await fetch(`${apiBase}/api/admin/qa-generator/drafts/${draftId}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Draftni reject qilishda xatolik"));
      }
      await loadDrafts(selectedDocument.id);
      setNoticeType("success");
      setNotice("Draft reject qilindi");
    } catch (error) {
      setNoticeType("error");
      setNotice(error?.message || "Draftni reject qilishda xatolik");
    }
  }

  async function bulkApprove() {
    if (selectedDraftIds.length === 0) return;
    try {
      setIsBulkApproving(true);
      const response = await fetch(`${apiBase}/api/admin/qa-generator/drafts/bulk-approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft_ids: selectedDraftIds }),
      });
      if (!response.ok) {
        throw new Error(await parseResponse(response, "Tanlangan draftlarni approve qilishda xatolik"));
      }
      await Promise.all([loadDrafts(selectedDocument.id), loadContext(selectedDocument.id), loadJobs(selectedDocument.id)]);
      setSelectedDraftIds([]);
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
    if (!tableId) return;
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

  const groupedDrafts = useMemo(() => {
    const sorted = [...drafts];
    sorted.sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
    return sorted;
  }, [drafts]);

  function toggleDraft(id, checked) {
    setSelectedDraftIds((prev) => {
      if (checked) {
        return prev.includes(id) ? prev : [...prev, id];
      }
      return prev.filter((item) => item !== id);
    });
  }

  return (
    <div className="flex-1 overflow-y-auto p-8 space-y-6 bg-background-light dark:bg-background-dark">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-extrabold tracking-tight">AI Savol Generator</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">SHNQ tanlang, draft savollar yarating, ko'rib chiqing va approve qiling.</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="font-semibold text-slate-600 dark:text-slate-300">Model</div>
          <div className="mt-1 text-lg font-black text-slate-900 dark:text-slate-50">gpt-5-mini</div>
        </div>
      </div>

      {notice ? (
        <div className={`rounded-xl border px-4 py-3 text-sm font-semibold ${noticeType === "error" ? "border-rose-200 bg-rose-50 text-rose-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>
          {notice}
        </div>
      ) : null}

      <div className="grid grid-cols-1 xl:grid-cols-[420px_minmax(0,1fr)] gap-6">
        <section className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <label className="block text-sm font-bold text-slate-700 dark:text-slate-200">SHNQ qidirish</label>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Masalan: SHNQ 2.08 yoki hujjat nomi"
              className="mt-3 h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm text-slate-700 outline-none focus:border-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
            <div className="mt-3 text-xs font-medium text-slate-500 dark:text-slate-400">
              {isSearching ? "Qidirilmoqda..." : `${searchItems.length} ta natija`}
            </div>
            <div className="mt-4 max-h-[420px] space-y-3 overflow-auto">
              {searchItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => selectDocument(item)}
                  className={`w-full rounded-2xl border px-4 py-4 text-left transition ${selectedDocument?.id === item.id ? "border-primary bg-primary/5" : "border-slate-200 bg-white hover:border-primary/40 dark:border-slate-700 dark:bg-slate-900"}`}
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
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="text-sm font-bold text-slate-700 dark:text-slate-200">Generator parametrlari</div>
            <label className="mt-4 block text-sm font-medium text-slate-600 dark:text-slate-300">
              Nechta savol kerak
              <input
                type="number"
                min="1"
                max="100"
                value={form.requested_count}
                onChange={(event) => setForm((prev) => ({ ...prev, requested_count: event.target.value }))}
                className="mt-2 h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm dark:border-slate-700 dark:bg-slate-800"
              />
            </label>
            <label className="mt-4 flex items-center gap-3 text-sm font-medium text-slate-700 dark:text-slate-200">
              <input
                type="checkbox"
                checked={form.include_table_questions}
                onChange={(event) => setForm((prev) => ({ ...prev, include_table_questions: event.target.checked }))}
                className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary"
              />
              Jadvalga tayangan savollarni ham yaratish
            </label>
            <button
              type="button"
              onClick={handleGenerate}
              disabled={!selectedDocument || isGenerating}
              className="mt-5 inline-flex w-full items-center justify-center rounded-xl bg-primary px-4 py-3 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isGenerating ? "Generatsiya boshlanmoqda..." : "AI Generate Savol"}
            </button>
          </div>
        </section>
        <section className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-sm font-bold text-slate-700 dark:text-slate-200">Tanlangan SHNQ</div>
                <div className="mt-1 text-xl font-black text-slate-900 dark:text-slate-50">{selectedDocument?.code || "-"}</div>
                <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{selectedDocument?.title || "SHNQ tanlanmagan"}</div>
              </div>
              {isLoadingContext ? <div className="text-xs font-semibold text-slate-400">Yuklanmoqda...</div> : null}
            </div>
            {context ? (
              <div className="mt-4 grid grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
                <div className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-800">
                  <div className="text-slate-500">Bandlar</div>
                  <div className="mt-1 text-xl font-black">{context.clause_count}</div>
                </div>
                <div className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-800">
                  <div className="text-slate-500">Jadvallar</div>
                  <div className="mt-1 text-xl font-black">{context.table_count}</div>
                </div>
                <div className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-800">
                  <div className="text-slate-500">Approved QA</div>
                  <div className="mt-1 text-xl font-black">{context.approved_count}</div>
                </div>
                <div className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-800">
                  <div className="text-slate-500">Lex link</div>
                  <div className="mt-1 truncate text-sm font-semibold">{context.lex_url || "-"}</div>
                </div>
              </div>
            ) : null}
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-sm font-bold text-slate-700 dark:text-slate-200">Generator joblari</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">So'nggi ishga tushirilgan joblar</div>
              </div>
              {selectedDraftIds.length > 0 ? (
                <button
                  type="button"
                  onClick={bulkApprove}
                  disabled={isBulkApproving}
                  className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-700"
                >
                  {isBulkApproving ? "Approve..." : `Tanlanganlarni approve (${selectedDraftIds.length})`}
                </button>
              ) : null}
            </div>
            <div className="mt-4 space-y-3">
              {jobs.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  Hali generator job yo'q.
                </div>
              ) : null}
              {jobs.map((job) => (
                <div key={job.id} className="rounded-xl border border-slate-200 px-4 py-4 dark:border-slate-700">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-black text-slate-900 dark:text-slate-50">{job.document_code}</div>
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {job.generated_count} / {job.requested_count} generated, {job.approved_count} approved
                      </div>
                    </div>
                    <span className={`rounded-full border px-3 py-1 text-[11px] font-black uppercase ${statusTone(job.status)}`}>
                      {job.status}
                    </span>
                  </div>
                  <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                    Model: {job.generator_model} • {formatDate(job.created_at)}
                  </div>
                  {job.error_message ? <div className="mt-2 text-xs font-medium text-rose-600">{job.error_message}</div> : null}
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-sm font-bold text-slate-700 dark:text-slate-200">Generated draftlar</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {isLoadingDrafts ? "Yuklanmoqda..." : `${groupedDrafts.length} ta draft`}
                </div>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {groupedDrafts.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  Draftlar hali yaratilmagan.
                </div>
              ) : null}
              {groupedDrafts.map((draft) => (
                <details key={draft.id} className="rounded-2xl border border-slate-200 bg-slate-50/50 dark:border-slate-700 dark:bg-slate-900/40">
                  <summary className="cursor-pointer list-none px-4 py-4">
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={selectedDraftIds.includes(draft.id)}
                        onChange={(event) => toggleDraft(draft.id, event.target.checked)}
                        onClick={(event) => event.stopPropagation()}
                        className="mt-1 h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-3">
                          <div className="truncate text-sm font-black text-slate-900 dark:text-slate-50">{draft.question}</div>
                          <span className={`rounded-full border px-3 py-1 text-[11px] font-black uppercase ${statusTone(draft.status)}`}>{draft.status}</span>
                        </div>
                        <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">{draft.short_answer}</div>
                        <div className="mt-2 flex flex-wrap gap-2 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                          <span>{draft.chapter_title || "-"}</span>
                          <span>{draft.clause_number || "band ko'rsatilmagan"}</span>
                          {draft.table_number ? <span>Jadval {draft.table_number}</span> : null}
                          <span>{formatDate(draft.created_at)}</span>
                        </div>
                      </div>
                    </div>
                  </summary>
                  <div className="border-t border-slate-200 px-4 py-4 dark:border-slate-700">
                    <div className="text-sm leading-6 text-slate-700 dark:text-slate-200 whitespace-pre-wrap">{draft.answer}</div>
                    <div className="mt-4 rounded-xl bg-white p-4 text-sm shadow-sm dark:bg-slate-950">
                      <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Source excerpt</div>
                      <div className="mt-2 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{draft.source_excerpt}</div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-3">
                      <button type="button" onClick={() => approveDraft(draft.id)} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white">
                        Approve
                      </button>
                      <button type="button" onClick={() => rejectDraft(draft.id)} className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-bold text-rose-700">
                        Reject
                      </button>
                      {draft.table_id ? (
                        <button type="button" onClick={() => openTablePreview(draft.table_id)} className="rounded-lg border border-primary/20 bg-primary/10 px-4 py-2 text-sm font-bold text-primary">
                          Jadvalni ko'rsatish
                        </button>
                      ) : null}
                    </div>
                  </div>
                </details>
              ))}
            </div>
          </div>

          {tablePreview ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-bold text-slate-700 dark:text-slate-200">Jadval preview</div>
                  <div className="mt-1 text-lg font-black text-slate-900 dark:text-slate-50">
                    {tablePreview.document_code} • Jadval {tablePreview.table_number}
                  </div>
                  <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{tablePreview.title || "-"}</div>
                </div>
                <button type="button" onClick={() => setTablePreview(null)} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-bold text-slate-600">
                  Yopish
                </button>
              </div>
              <div className="mt-4 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-950">
                {tablePreview.html ? (
                  <div className="min-w-[680px]" dangerouslySetInnerHTML={{ __html: tablePreview.html }} />
                ) : (
                  <pre className="whitespace-pre-wrap text-sm text-slate-700 dark:text-slate-300">{tablePreview.markdown || "Jadval matni topilmadi."}</pre>
                )}
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
