import { useEffect, useRef, useState } from 'react';
import { request } from '../backend.js';

const button = 'rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs disabled:opacity-40';

export default function OpenFASTCaseInspection({ definition = {}, disabled = false, onValidationChange }) {
  const signature = JSON.stringify({ case_directory: definition.case_directory, input_file: definition.input_file, output_file: definition.output_file, timeout_seconds: definition.timeout_seconds });
  const currentSignature = useRef(signature);
  currentSignature.current = signature;
  const callback = useRef(onValidationChange);
  callback.current = onValidationChange;
  const generation = useRef(0);
  const [inspection, setInspection] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(null);
  const result = inspection?.signature === signature ? inspection.value : null;
  const error = failure?.signature === signature ? failure.message : '';
  const busy = pending === signature;
  const complete = [definition.case_directory, definition.input_file, definition.output_file].every((value) => typeof value === 'string' && value.trim());

  useEffect(() => {
    generation.current += 1;
    setInspection(null); setFailure(null); setPending(null);
    callback.current?.(false);
    return () => { generation.current += 1; callback.current?.(false); };
  }, [signature]);

  const inspect = async () => {
    const epoch = ++generation.current;
    const submittedSignature = signature;
    setPending(signature); setFailure(null); setInspection(null); callback.current?.(false);
    try {
      const value = await request('/v1/openfast/inspect', { case: definition });
      if (epoch !== generation.current || submittedSignature !== currentSignature.current) return;
      setInspection({ signature: submittedSignature, value });
      callback.current?.(true, value);
    } catch (caught) {
      if (epoch === generation.current && submittedSignature === currentSignature.current) {
        setFailure({ signature: submittedSignature, message: caught.message }); callback.current?.(false);
      }
    } finally {
      if (epoch === generation.current && submittedSignature === currentSignature.current) setPending(null);
    }
  };

  return <section aria-label="OpenFAST case inspection" aria-busy={busy} className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h4 className="text-sm">Case snapshot inspection</h4><button className={button} disabled={disabled || busy || !complete} onClick={inspect}>{busy ? 'Inspecting case files…' : 'Inspect OpenFAST case'}</button></div>
    <p className="text-xs leading-5 text-zinc-400">Review the self-contained input files and snapshot fingerprint without selecting or running an executable. Execution validates the case again; inspection does not establish numerical correctness.</p>
    <p role="status" className={`text-xs ${result ? 'text-emerald-300' : 'text-zinc-500'}`}>{busy ? 'Inspecting the current case files.' : result ? `Case inspected · ${result.file_count} files · ${Number(result.total_bytes).toLocaleString()} bytes` : 'Case not inspected for the current inputs.'}</p>
    {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    {result && <>
      <p className="break-all text-xs text-zinc-400">Input: {result.input_file} · Expected output: {result.output_file}</p>
      <p className="break-all text-[10px] text-zinc-500">Snapshot SHA256: {result.case_hash}</p>
      {result.warnings?.length > 0 && <ul className="list-disc space-y-1 pl-4 text-xs text-amber-300">{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
      <details><summary className="cursor-pointer text-xs text-zinc-400">Case file inventory</summary><div className="mt-3 max-h-64 overflow-auto"><table aria-label="OpenFAST input file inventory" className="w-full text-left text-xs"><thead className="text-zinc-500"><tr><th className="p-2 font-normal">Relative file</th><th className="p-2 font-normal">Bytes</th><th className="p-2 font-normal">SHA256</th></tr></thead><tbody>{result.input_files.map((file) => <tr key={file.path} className="border-t border-zinc-800"><td className="p-2">{file.path}</td><td className="p-2 tabular-nums">{Number(file.bytes).toLocaleString()}</td><td className="break-all p-2 font-mono text-[10px] text-zinc-500">{file.sha256}</td></tr>)}</tbody></table></div></details>
    </>}
  </section>;
}
