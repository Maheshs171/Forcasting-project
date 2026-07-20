import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Plus, CheckCircle2, XCircle, Trash2, Loader2, PlugZap } from "lucide-react";
import { api } from "../lib/api";

const inputCls =
  "w-full rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-[13px] text-slate-800 focus:outline-none focus:border-indigo-400 focus:bg-white transition-colors";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">{label}</span>
      {children}
    </label>
  );
}

export default function Settings() {
  const qc = useQueryClient();
  const { data: connections } = useQuery({ queryKey: ["connections"], queryFn: api.connections });

  const [form, setForm] = useState({ name: "", server: "", database: "", username: "", password: "", port: 3342 });
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [showForm, setShowForm] = useState(false);

  const testMutation = useMutation({
    mutationFn: () => api.testConnection(form),
    onSuccess: (r) => setTestResult(r),
  });

  const addMutation = useMutation({
    mutationFn: () => api.addConnection({ ...form, make_active: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connections"] });
      qc.invalidateQueries({ queryKey: ["env"] });
      setForm({ name: "", server: "", database: "", username: "", password: "", port: 3342 });
      setTestResult(null);
      setShowForm(false);
    },
  });

  const activateMutation = useMutation({
    mutationFn: (name: string) => api.activateConnection(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connections"] });
      qc.invalidateQueries({ queryKey: ["env"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteConnection(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connections"] }),
  });

  const canTest = form.server && form.database && form.username && form.password;

  return (
    <div className="max-w-4xl mx-auto space-y-7">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-slate-900">Settings</h1>
        <p className="text-[13px] text-slate-400 mt-1">
          Connect this app to a different SQL Server / database. Table and column names are assumed the same
          across every connection — no other configuration is needed when you switch.
        </p>
      </div>

      <div className="glass rounded-2xl p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Database size={16} className="text-slate-400" />
            <span className="text-[13.5px] font-semibold text-slate-900">Database connections</span>
          </div>
          <button
            onClick={() => setShowForm((s) => !s)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-[12.5px] font-medium text-white hover:bg-indigo-500 transition-colors"
          >
            <Plus size={14} /> Add connection
          </button>
        </div>

        <div className="space-y-2 mb-2">
          {!connections?.length && <div className="text-[12px] text-slate-400 italic py-4 text-center">No connections configured</div>}
          {connections?.map((c) => (
            <div
              key={c.name}
              className={`flex items-center justify-between rounded-xl border px-4 py-3 ${
                c.is_active ? "border-indigo-200 bg-indigo-50" : "border-slate-200"
              }`}
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold text-slate-800">{c.name}</span>
                  {c.is_active && (
                    <span className="text-[10px] font-bold uppercase tracking-wide text-indigo-600 bg-indigo-100 rounded-full px-2 py-0.5">
                      active
                    </span>
                  )}
                </div>
                <div className="text-[11.5px] text-slate-400 mt-0.5">
                  {c.server} &middot; {c.database} &middot; port {c.port} &middot; user {c.username}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {!c.is_active && (
                  <button
                    onClick={() => activateMutation.mutate(c.name)}
                    className="text-[12px] text-indigo-600 hover:text-indigo-700 font-medium px-2 py-1"
                  >
                    Set active
                  </button>
                )}
                <button
                  onClick={() => deleteMutation.mutate(c.name)}
                  className="text-slate-300 hover:text-red-500 p-1.5 transition-colors"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>

        {showForm && (
          <div className="mt-4 pt-4 border-t border-slate-200 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Connection name">
                <input className={inputCls} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="production" />
              </Field>
              <Field label="Port">
                <input
                  type="number"
                  className={inputCls}
                  value={form.port}
                  onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
                />
              </Field>
              <Field label="Server">
                <input
                  className={inputCls}
                  value={form.server}
                  onChange={(e) => setForm({ ...form, server: e.target.value })}
                  placeholder="your-server.database.windows.net"
                />
              </Field>
              <Field label="Database">
                <input className={inputCls} value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })} />
              </Field>
              <Field label="Username">
                <input className={inputCls} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
              </Field>
              <Field label="Password">
                <input
                  type="password"
                  className={inputCls}
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                />
              </Field>
            </div>

            {testResult && (
              <div
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-[12.5px] ${
                  testResult.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
                }`}
              >
                {testResult.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                {testResult.message}
              </div>
            )}

            <div className="flex items-center gap-2">
              <button
                onClick={() => testMutation.mutate()}
                disabled={!canTest || testMutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3.5 py-2 text-[12.5px] font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40 transition-colors"
              >
                {testMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
                Test connection
              </button>
              <button
                onClick={() => addMutation.mutate()}
                disabled={!canTest || !form.name || addMutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-[12.5px] font-medium text-white hover:bg-indigo-500 disabled:opacity-40 transition-colors"
              >
                {addMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                Save &amp; set active
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
