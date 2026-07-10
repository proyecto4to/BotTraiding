import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ParamSchemaForm } from "@/components/ParamSchemaForm";
import type { ParameterSpec } from "@/lib/types";

const schema: ParameterSpec[] = [
  {
    name: "fast_period",
    type: "int",
    default: 10,
    min: 2,
    max: 200,
    description: "Fast SMA lookback",
  },
  { name: "use_stops", type: "bool", default: true },
  {
    name: "mode",
    type: "str",
    default: "cross",
    choices: ["cross", "trend", "meanrev"],
  },
  { name: "risk_factor", type: "float", default: 0.5, min: 0, max: 1 },
];

describe("ParamSchemaForm", () => {
  it("renders one control per spec with the right types and bounds", () => {
    render(<ParamSchemaForm schema={schema} values={{}} onChange={() => {}} />);

    const fast = screen.getByLabelText(/fast_period/) as HTMLInputElement;
    expect(fast.type).toBe("number");
    expect(fast.min).toBe("2");
    expect(fast.max).toBe("200");
    expect(fast.value).toBe("10"); // default shown when no override

    const stops = screen.getByLabelText(/use_stops/) as HTMLInputElement;
    expect(stops.type).toBe("checkbox");
    expect(stops.checked).toBe(true);

    const mode = screen.getByLabelText(/mode/) as HTMLSelectElement;
    expect(mode.tagName).toBe("SELECT");
    expect(Array.from(mode.options).map((o) => o.value)).toEqual([
      "cross",
      "trend",
      "meanrev",
    ]);

    expect(screen.getByText("Fast SMA lookback")).toBeInTheDocument();
    expect(screen.getByText("Range: 2 – 200")).toBeInTheDocument();
  });

  it("reports typed values through onChange", () => {
    const onChange = vi.fn();
    render(<ParamSchemaForm schema={schema} values={{}} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText(/fast_period/), { target: { value: "25" } });
    expect(onChange).toHaveBeenLastCalledWith({ fast_period: 25 });

    fireEvent.click(screen.getByLabelText(/use_stops/));
    expect(onChange).toHaveBeenLastCalledWith({ use_stops: false });

    fireEvent.change(screen.getByLabelText(/mode/), { target: { value: "trend" } });
    expect(onChange).toHaveBeenLastCalledWith({ mode: "trend" });

    fireEvent.change(screen.getByLabelText(/risk_factor/), { target: { value: "0.75" } });
    expect(onChange).toHaveBeenLastCalledWith({ risk_factor: 0.75 });
  });

  it("shows existing override values over defaults", () => {
    render(
      <ParamSchemaForm schema={schema} values={{ fast_period: 42 }} onChange={() => {}} />,
    );
    expect((screen.getByLabelText(/fast_period/) as HTMLInputElement).value).toBe("42");
  });

  it("renders a friendly message for an empty schema", () => {
    render(<ParamSchemaForm schema={[]} values={{}} onChange={() => {}} />);
    expect(screen.getByText(/no configurable parameters/i)).toBeInTheDocument();
  });
});
