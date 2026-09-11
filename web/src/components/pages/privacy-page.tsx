import { useTranslation } from "react-i18next";
import { PageShell, Section, Prose, BulletList } from "./page-shell";

export function PrivacyPage() {
  const { t } = useTranslation();
  return (
    <PageShell title={t("privacy.title")} subtitle={t("privacy.subtitle")}>
      <Section title={t("privacy.intro")}>
        <Prose>{t("privacy.intro")}</Prose>
      </Section>
      <Section title={t("privacy.dataCollectedTitle")}>
        <Prose>{t("privacy.dataCollectedBody")}</Prose>
        <BulletList items={t("privacy.dataCollectedList", { returnObjects: true }) as unknown as string} />
      </Section>
      <Section title={t("privacy.dataNotCollectedTitle")}>
        <Prose>{t("privacy.dataNotCollectedBody")}</Prose>
        <BulletList items={t("privacy.dataNotCollectedList", { returnObjects: true }) as unknown as string} />
      </Section>
      <Section title={t("privacy.howProcessedTitle")}>
        <Prose>{t("privacy.howProcessedBody")}</Prose>
      </Section>
      <Section title={t("privacy.cookiesTitle")}>
        <Prose>{t("privacy.cookiesBody")}</Prose>
        <BulletList items={t("privacy.cookiesList", { returnObjects: true }) as unknown as string} />
      </Section>
      <Section title={t("privacy.dataRetentionTitle")}>
        <Prose>{t("privacy.dataRetentionBody")}</Prose>
      </Section>
      <Section title={t("privacy.yourRightsTitle")}>
        <Prose>{t("privacy.yourRightsBody")}</Prose>
      </Section>
      <Section title={t("privacy.changesTitle")}>
        <Prose>{t("privacy.changesBody")}</Prose>
      </Section>
      <Section title={t("privacy.contactTitle")}>
        <Prose>{t("privacy.contactBody")}</Prose>
      </Section>
    </PageShell>
  );
}
