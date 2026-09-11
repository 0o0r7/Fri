import { useTranslation } from "react-i18next";
import { PageShell, Section, Prose, BulletList } from "./page-shell";

export function TermsPage() {
  const { t } = useTranslation();
  return (
    <PageShell title={t("terms.title")} subtitle={t("terms.subtitle")}>
      <Section title={t("terms.acceptanceTitle")}>
        <Prose>{t("terms.acceptanceBody")}</Prose>
      </Section>
      <Section title={t("terms.descriptionTitle")}>
        <Prose>{t("terms.descriptionBody")}</Prose>
      </Section>
      <Section title={t("terms.notAffiliatedTitle")}>
        <Prose>{t("terms.notAffiliatedBody")}</Prose>
      </Section>
      <Section title={t("terms.accuracyTitle")}>
        <Prose>{t("terms.accuracyBody")}</Prose>
      </Section>
      <Section title={t("terms.useTitle")}>
        <Prose>{t("terms.useBody")}</Prose>
        <BulletList items={t("terms.useList", { returnObjects: true }) as unknown as string} />
      </Section>
      <Section title={t("terms.prohibitedTitle")}>
        <Prose>{t("terms.prohibitedBody")}</Prose>
        <BulletList items={t("terms.prohibitedList", { returnObjects: true }) as unknown as string} />
      </Section>
      <Section title={t("terms.liabilityTitle")}>
        <Prose>{t("terms.liabilityBody")}</Prose>
      </Section>
      <Section title={t("terms.changesTitle")}>
        <Prose>{t("terms.changesBody")}</Prose>
      </Section>
      <Section title={t("terms.contactTitle")}>
        <Prose>{t("terms.contactBody")}</Prose>
      </Section>
    </PageShell>
  );
}
