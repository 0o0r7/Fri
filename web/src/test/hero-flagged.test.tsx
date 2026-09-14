/**
 * Flagged-DID transparency (audit commitment): the hero must surface the
 * number of spam/sybil-flagged DIDs as an amber stat card linked to the
 * reputation tab — visible, never silently hidden — whenever the API
 * reports one, and stay quiet otherwise.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n";
import { HeroSection } from "@/components/hero-section";
import type { LiveCounts } from "@/hooks/useLiveData";

function renderHero(counts: LiveCounts | null) {
  return render(
    <I18nextProvider i18n={i18n}>
      <HeroSection counts={counts} />
    </I18nextProvider>,
  );
}

const base: LiveCounts = {
  total_dids: 19542,
  total_rooms: 11,
  total_jobs: 152,
  total_contracts: 398,
  total_dids_scored: 500,
  messages_observed: 4390,
};

describe("HeroSection flagged stat card", () => {
  it("shows the flagged count as an amber card linked to the reputation tab", () => {
    renderHero({ ...base, flagged_dids: 123 });
    const label = screen.getByText("Flagged DIDs");
    expect(label).toBeInTheDocument();
    expect(label.closest("a")).toHaveAttribute("href", "#reputation");
    expect(screen.getByText("123")).toBeInTheDocument();
  });

  it("hides the card when nothing is flagged", () => {
    renderHero({ ...base, flagged_dids: 0 });
    expect(screen.queryByText("Flagged DIDs")).not.toBeInTheDocument();
  });

  it("hides the card when counts are absent (static boot)", () => {
    renderHero(null);
    expect(screen.queryByText("Flagged DIDs")).not.toBeInTheDocument();
    expect(screen.getByText("DIDs indexed")).toBeInTheDocument();
  });

  it("renders the stat cards and the terminal boot frame", () => {
    renderHero({ ...base, flagged_dids: 7 });
    expect(screen.getByText("DIDs indexed")).toBeInTheDocument();
    expect(screen.getByText("Messages observed")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("fri — oracle link")).toBeInTheDocument();
  });
});
