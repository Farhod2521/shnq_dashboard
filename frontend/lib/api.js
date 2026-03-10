const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://shnq-api.dashboard.iqmath.uz";

async function request(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    cache: "no-store",
  });

  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || `API error: ${res.status}`);
  }

  return res.json();
}

export async function fetchDocuments() {
  return request("/api/admin/documents");
}

export async function createDocument(payload) {
  return request("/api/admin/documents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchRegistry() {
  return request("/api/admin/registry-stats");
}

export async function fetchPipelineStatus() {
  return request("/api/admin/pipeline-status");
}
