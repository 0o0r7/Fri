/**
 * Flagged-DID badge (audit transparency commitment): the hero must surface
 * the number of spam/sybil-flagged DIDs — visible, never silently hidden —
 * whenever the API reports one, and stay quiet otherwise.
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
      <HeroSection counts={counts} connected stale={false} />
    </I18nextProvider>,
  );
}

const base: LiveCounts = {
  total_dids: 19542,
  total_rooms: 11,
  total_jobs: 152,
  total_contracts: 398,
  total_dids_scored: 500,
};

describe("HeroSection flagged badge", () => {
  it("shows the flagged count and links to the reputation tab", () => {
    renderHero({ ...base, flagged_dids: 123 });
    const chip = screen.getByText("123 flagged");
    expect(chip).toBeInTheDocument();
    expect(chip.closest("a")).toHaveAttribute("href", "#reputation");
  });

  it("hides the badge when nothing is flagged", () => {
    renderHero({ ...base, flagged_dids: 0 });
    expect(screen.queryByText(/flagged/)).not.toBeInTheDocument();
  });

  it("hides the badge when counts are absent (static boot)", () => {
    renderHero(null);
    expect(screen.queryByText(/flagged/)).not.toBeInTheDocument();
  });

  it("keeps rendering the four stat cards alongside the badge", () => {
    renderHero({ ...base, flagged_dids: 7 });
    expect(screen.getByText("Total DIDs")).toBeInTheDocument();
    expect(screen.getByText("Active Rooms")).toBeInTheDocument();
    expect(screen.getByText("TCLK Deals")).toBeInTheDocument();
    expect(screen.getByText("Kibble Jobs")).toBeInTheDocument();
    expect(screen.getByText("7 flagged")).toBeInTheDocument();
  });
});
