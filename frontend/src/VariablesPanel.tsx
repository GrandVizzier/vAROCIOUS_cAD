import { useEffect, useState } from "react";
import { setVariables } from "./api";

function fmt(name: string, v: number | undefined) {
  if (v === undefined) return "";
  if (/^f/i.test(name) && Math.abs(v) >= 1e6) return `${+(v / 1e9).toPrecision(6)} GHz`;
  return `${+v.toPrecision(6)}`;
}

export default function VariablesPanel({ id, readonly, variables, values }: {
  id: string; readonly: boolean; variables: Record<string, string>; values: Record<string, number>;
}) {
  const [draft, setDraft] = useState(variables);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setDraft(variables), [variables]);

  const commit = async (name: string) => {
    if (draft[name] === variables[name]) return;
    try {
      await setVariables(id, { [name]: draft[name] }); // file write -> watcher -> rebuild -> ws
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div>
      <h3>Variables</h3>
      {readonly && <p className="muted small">Example projects are read-only.</p>}
      {error && <p className="warn small">{error}</p>}
      <table className="vars">
        <tbody>
          {Object.keys(variables).map((name) => (
            <tr key={name}>
              <td className="vname">{name}</td>
              <td>
                <input type="text" value={draft[name] ?? ""} disabled={readonly} spellCheck={false}
                       onChange={(e) => setDraft({ ...draft, [name]: e.target.value })}
                       onBlur={() => commit(name)}
                       onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
              </td>
              <td className="muted small vval">{fmt(name, values[name])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
