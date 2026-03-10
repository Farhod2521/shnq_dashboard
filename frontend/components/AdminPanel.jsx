"use client";

import { useEffect, useMemo, useState } from "react";
import { categoriesSeed, documentsSeed, registrySeed } from "../lib/mockData";
import {
  createDocument,
  fetchDocuments,
  fetchPipelineStatus,
  fetchRegistry,
} from "../lib/api";

const POLL_MS = 3000;

function asPercent(value) {
  const num = Number(value || 0);
  return Math.max(0, Math.min(100, num));
}

function getStateFromPipeline(pipeline) {
  if (!pipeline) return "queued";
  if (pipeline.finished) return "done";
  if (pipeline.state) return pipeline.state;
  return "processing";
}

function StatusPill({ state }) {
  return <span className={`pill pill-${state}`}>{state}</span>;
}

function StageCell({ label, value }) {
  const pct = asPercent(value);

  return (
    <div className="stage-cell">
      <div className="stage-line">
        <span>{label}</span>
        <strong>{pct}%</strong>
      </div>
      <div className="bar">
        <div className="bar-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function simulateProgress(items) {
  return items.map((doc) => {
    if (doc.pipeline?.finished) {
      return doc;
    }

    const next = { ...doc, pipeline: { ...doc.pipeline } };
    const delta = Math.floor(Math.random() * 8) + 2;

    if (next.pipeline.doc_to_html < 100) {
      next.pipeline.doc_to_html = Math.min(100, next.pipeline.doc_to_html + delta);
    } else if (next.pipeline.html_chunking < 100) {
      next.pipeline.html_chunking = Math.min(100, next.pipeline.html_chunking + delta);
    } else if (next.pipeline.row_embedding < 100) {
      next.pipeline.row_embedding = Math.min(100, next.pipeline.row_embedding + delta);
    } else if (next.pipeline.image_embedding < 100) {
      next.pipeline.image_embedding = Math.min(100, next.pipeline.image_embedding + delta);
    }

    const finished =
      next.pipeline.doc_to_html === 100 &&
      next.pipeline.html_chunking === 100 &&
      next.pipeline.row_embedding === 100 &&
      next.pipeline.image_embedding === 100;

    next.pipeline.finished = finished;
    next.pipeline.state = finished ? "done" : "processing";

    return next;
  });
}

function useTheme() {
  const [theme, setTheme] = useState("dark");

  useEffect(() => {
    const saved = window.localStorage.getItem("shnq-theme");
    const initial = saved || "dark";
    document.documentElement.setAttribute("data-theme", initial);
    setTheme(initial);
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    window.localStorage.setItem("shnq-theme", next);
  }

  return { theme, toggle };
}

export default function AdminPanel() {
  const { theme, toggle } = useTheme();
  const [mode, setMode] = useState("demo");
  const [documents, setDocuments] = useState(documentsSeed);
  const [registry, setRegistry] = useState(registrySeed);
  const [error, setError] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);

  const [form, setForm] = useState({
    category_code: "SHNQ",
    title: "",
    code: "",
    lex_url: "",
    original_file: "",
    html_file: "",
  });

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      try {
        const [docs, stats] = await Promise.all([fetchDocuments(), fetchRegistry()]);
        if (!active) return;

        setDocuments(Array.isArray(docs) ? docs : []);
        setRegistry(stats || registrySeed);
        setMode("api");
        setError("");
      } catch {
        if (!active) return;
        setMode("demo");
        setError("Backend admin API topilmadi. Hozir demo realtime rejim ishlayapti.");
      }
    }

    bootstrap();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const timer = setInterval(async () => {
      if (mode === "api") {
        try {
          const [pipeline, stats] = await Promise.all([
            fetchPipelineStatus(),
            fetchRegistry(),
          ]);

          setDocuments(Array.isArray(pipeline) ? pipeline : []);
          setRegistry(stats || registrySeed);
          setError("");
        } catch {
          setError("Realtime API vaqtincha ishlamadi. Oxirgi holat ko'rsatilyapti.");
        }
      } else {
        setDocuments((prev) => simulateProgress(prev));
      }
    }, POLL_MS);

    return () => clearInterval(timer);
  }, [mode]);

  const dashboard = useMemo(() => {
    const total = documents.length;
    const done = documents.filter((d) => getStateFromPipeline(d.pipeline) === "done").length;
    const processing = documents.filter((d) => getStateFromPipeline(d.pipeline) === "processing").length;
    const queued = Math.max(0, total - done - processing);

    return { total, done, processing, queued };
  }, [documents]);

  function onChange(event) {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  async function onSubmit(event) {
    event.preventDefault();

    const payload = {
      ...form,
      created_at: new Date().toISOString(),
      pipeline: {
        doc_to_html: 0,
        html_chunking: 0,
        row_embedding: 0,
        image_embedding: 0,
        finished: false,
        state: "queued",
      },
    };

    if (mode === "api") {
      try {
        const created = await createDocument(payload);
        setDocuments((prev) => [created, ...prev]);
      } catch {
        setError("Document yaratish API ishlamadi, demo ro'yxatga qo'shildi.");
        setDocuments((prev) => [{ id: `doc-${Date.now()}`, ...payload }, ...prev]);
      }
    } else {
      setDocuments((prev) => [{ id: `doc-${Date.now()}`, ...payload }, ...prev]);
    }

    setForm((prev) => ({
      ...prev,
      title: "",
      code: "",
      lex_url: "",
      original_file: "",
      html_file: "",
    }));
  }

  return (
    <main className="admin-root">
      <aside className="sidebar">
        <h1>SHNQ Admin</h1>
        <p className="sidebar-sub">my.gov.uz uslubidagi boshqaruv paneli</p>
        <nav>
          <a href="#dashboard">Dashboard</a>
          <a href="#documents">Documents</a>
          <a href="#registry">Registry</a>
          <a href="#settings">Settings</a>
        </nav>
      </aside>

      <section className="content">
        <header className="topbar gov-topbar">
          <div>
            <h2>SHNQ Hujjatlar Admini</h2>
            <p>{mode === "api" ? "Real-time API rejimi" : "Demo real-time rejimi"}</p>
          </div>
          <button className="theme-btn" onClick={toggle}>
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
        </header>

        {error ? <div className="alert">{error}</div> : null}

        <section id="dashboard" className="card">
          <h3>Umumiy holat</h3>
          <div className="stats-grid">
            <div>
              <span>Jami hujjat</span>
              <strong>{dashboard.total}</strong>
            </div>
            <div>
              <span>Done</span>
              <strong>{dashboard.done}</strong>
            </div>
            <div>
              <span>Processing</span>
              <strong>{dashboard.processing}</strong>
            </div>
            <div>
              <span>Queued</span>
              <strong>{dashboard.queued}</strong>
            </div>
          </div>
        </section>

        <section id="documents" className="card">
          <div className="section-head">
            <h3>Hujjatlar</h3>
            <button className="add-btn" type="button" onClick={() => setShowAddForm((v) => !v)}>
              {showAddForm ? "Yopish" : "+ Hujjat qo'shish"}
            </button>
          </div>

          {showAddForm ? (
            <form className="doc-form gov-form" onSubmit={onSubmit}>
              <label>
                Category
                <select name="category_code" value={form.category_code} onChange={onChange}>
                  {categoriesSeed.map((c) => (
                    <option key={c.id} value={c.code}>
                      {c.code} - {c.name}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Title
                <input name="title" value={form.title} onChange={onChange} required />
              </label>

              <label>
                Code
                <input name="code" value={form.code} onChange={onChange} required />
              </label>

              <label>
                Lex URL
                <input name="lex_url" value={form.lex_url} onChange={onChange} />
              </label>

              <label>
                Original file path
                <input name="original_file" value={form.original_file} onChange={onChange} />
              </label>

              <label>
                HTML file path
                <input name="html_file" value={form.html_file} onChange={onChange} />
              </label>

              <button type="submit">Saqlash</button>
            </form>
          ) : null}

          <h4 className="sub-title">Hujjatlar ro'yxati va jarayon holati</h4>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Title</th>
                  <th>Category</th>
                  <th>Yaratilgan</th>
                  <th>Doc -&gt; HTML</th>
                  <th>HTML chunking</th>
                  <th>Row embedding</th>
                  <th>Image embedding</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>{doc.code}</td>
                    <td>{doc.title}</td>
                    <td>{doc.category_code || "-"}</td>
                    <td>{new Date(doc.created_at).toLocaleString("uz-UZ")}</td>
                    <td>
                      <StageCell label="convert" value={doc.pipeline?.doc_to_html} />
                    </td>
                    <td>
                      <StageCell label="chunks" value={doc.pipeline?.html_chunking} />
                    </td>
                    <td>
                      <StageCell label="rows" value={doc.pipeline?.row_embedding} />
                    </td>
                    <td>
                      <StageCell label="images" value={doc.pipeline?.image_embedding} />
                    </td>
                    <td>
                      <StatusPill state={getStateFromPipeline(doc.pipeline)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section id="registry" className="card">
          <h3>Data Registry (Django admin uslubida)</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Records</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(registry).map(([key, count]) => (
                  <tr key={key}>
                    <td>{key}</td>
                    <td>{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section id="settings" className="card">
          <h3>Sozlamalar</h3>
          <p>
            Theme: <strong>{theme}</strong>
          </p>
          <p>
            NEXT_PUBLIC_API_URL: <strong>{process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}</strong>
          </p>
          <p>
            Polling interval: <strong>{POLL_MS / 1000}s</strong>
          </p>
        </section>
      </section>
    </main>
  );
}
