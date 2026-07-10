"use client";

/**
 * Renders a strategy's parameter schema (name/type/default/min/max/choices)
 * as form controls. Configuration UI only — validation and persistence are
 * the strategy-engine's job (PUT /api/strategies/{key}/config re-validates).
 */

import type { ParameterSpec } from "@/lib/types";

export type ParamValues = Record<string, unknown>;

export function ParamSchemaForm({
  schema,
  values,
  onChange,
}: {
  schema: ParameterSpec[];
  values: ParamValues;
  onChange: (next: ParamValues) => void;
}) {
  const set = (name: string, value: unknown) => onChange({ ...values, [name]: value });

  if (schema.length === 0) {
    return <p className="muted">This strategy has no configurable parameters.</p>;
  }

  return (
    <div className="param-form">
      {schema.map((spec) => {
        const current = values[spec.name] ?? spec.default;
        const inputId = `param-${spec.name}`;
        return (
          <div className="form-row" key={spec.name}>
            <label className="label" htmlFor={inputId}>
              {spec.name}
              <span className="muted"> ({spec.type})</span>
            </label>
            {renderControl(spec, current, inputId, set)}
            {spec.description ? <p className="field-hint">{spec.description}</p> : null}
            {spec.min !== null && spec.min !== undefined && spec.max !== null && spec.max !== undefined ? (
              <p className="field-hint">
                Range: {spec.min} – {spec.max}
              </p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function renderControl(
  spec: ParameterSpec,
  current: unknown,
  inputId: string,
  set: (name: string, value: unknown) => void,
) {
  if (spec.choices && spec.choices.length > 0) {
    return (
      <select
        id={inputId}
        className="input"
        value={String(current ?? "")}
        onChange={(e) => {
          const raw = e.target.value;
          const match = spec.choices!.find((c) => String(c) === raw);
          set(spec.name, match ?? raw);
        }}
      >
        {spec.choices.map((choice) => (
          <option key={String(choice)} value={String(choice)}>
            {String(choice)}
          </option>
        ))}
      </select>
    );
  }

  switch (spec.type) {
    case "bool":
    case "boolean":
      return (
        <input
          id={inputId}
          type="checkbox"
          className="toggle"
          checked={Boolean(current)}
          onChange={(e) => set(spec.name, e.target.checked)}
        />
      );
    case "int":
    case "integer":
    case "float":
    case "number":
      return (
        <input
          id={inputId}
          type="number"
          className="input"
          value={current === null || current === undefined ? "" : Number(current)}
          min={spec.min ?? undefined}
          max={spec.max ?? undefined}
          step={spec.type === "int" || spec.type === "integer" ? 1 : "any"}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              set(spec.name, spec.default);
              return;
            }
            const parsed =
              spec.type === "int" || spec.type === "integer"
                ? parseInt(raw, 10)
                : parseFloat(raw);
            if (!Number.isNaN(parsed)) set(spec.name, parsed);
          }}
        />
      );
    default:
      return (
        <input
          id={inputId}
          type="text"
          className="input"
          value={String(current ?? "")}
          onChange={(e) => set(spec.name, e.target.value)}
        />
      );
  }
}
