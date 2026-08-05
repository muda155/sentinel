import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Section from "@/components/Section";

describe("Section", () => {
  it("renders its children when open by default", () => {
    render(<Section title="Sources"><p>body</p></Section>);
    expect(screen.getByText("body")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Sources/ }).getAttribute("aria-expanded"))
      .toBe("true");
  });

  it("hides children when defaultOpen is false", () => {
    render(<Section title="Sources" defaultOpen={false}><p>body</p></Section>);
    expect(screen.queryByText("body")).toBeNull();
    expect(screen.getByRole("button", { name: /Sources/ }).getAttribute("aria-expanded"))
      .toBe("false");
  });

  it("toggles on click", () => {
    render(<Section title="Sources"><p>body</p></Section>);
    const trigger = screen.getByRole("button", { name: /Sources/ });
    fireEvent.click(trigger);
    expect(screen.queryByText("body")).toBeNull();
    fireEvent.click(trigger);
    expect(screen.getByText("body")).toBeTruthy();
  });

  it("shows a count beside the title when given one", () => {
    render(<Section title="Sources" count={7}><p>body</p></Section>);
    expect(screen.getByRole("button", { name: /Sources \(7\)/ })).toBeTruthy();
  });

  it("keeps the count visible while collapsed", () => {
    // The count is the reason to expand — hiding it with the body would
    // make a collapsed section useless.
    render(<Section title="Sources" count={7} defaultOpen={false}><p>body</p></Section>);
    expect(screen.getByRole("button", { name: /Sources \(7\)/ })).toBeTruthy();
  });
});
