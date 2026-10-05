import { useSearchParams } from "react-router-dom";
import { useLinkedIn } from "../../hooks/useLinkedIn";
import { AdminTabList, type AdminTabItem } from "../ui";
import { LinkedInCalendarSection } from "./LinkedInCalendarSection";
import { LinkedInDraftsSection } from "./LinkedInDraftsSection";
import { LinkedInIdeasSection } from "./LinkedInIdeasSection";
import { LinkedInPublishedSection } from "./LinkedInPublishedSection";
import { LinkedInSettingsCard } from "./LinkedInSettingsCard";

const SECTIONS = ["drafts", "calendar", "published", "ideas", "settings"] as const;
type Section = (typeof SECTIONS)[number];

const TABS: readonly AdminTabItem<Section>[] = [
  { id: "drafts", label: "Drafts" },
  { id: "calendar", label: "Calendar" },
  { id: "published", label: "Posted" },
  { id: "ideas", label: "Ideas" },
  { id: "settings", label: "Settings" },
];

function sectionFrom(search: URLSearchParams): Section {
  const value = search.get("section");
  return SECTIONS.includes(value as Section) ? (value as Section) : "drafts";
}

export function LinkedInTab() {
  const linkedIn = useLinkedIn();
  const [params, setParams] = useSearchParams();
  const section = sectionFrom(params);
  const overview = linkedIn.overview.data;
  const enabled = overview?.enabled ?? false;

  function setSection(id: Section) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("tab", "linkedin");
      next.set("section", id);
      if (id !== "drafts") next.delete("linkedin-post");
      if (id !== "ideas") next.delete("linkedin-idea");
      return next;
    }, { replace: true });
  }

  return (
    <div>
      {linkedIn.overview.isError ? (
        <p className="text-danger small">Could not load LinkedIn. Check API configuration and sign-in.</p>
      ) : null}
      {overview && !enabled ? (
        <p className="text-muted small">
          LinkedIn writes are off until LxSoftwareLinkedinEnabled is true. You can still read what is stored.
        </p>
      ) : null}
      <AdminTabList
        tabs={TABS}
        active={section}
        onChange={setSection}
        label="LinkedIn sections"
        idPrefix="linkedin"
        panelId="linkedin-panel"
      />
      <div className="tab-content" id="linkedin-panel" role="tabpanel">
        {section === "drafts" ? (
          <LinkedInDraftsSection settings={overview?.settings} enabled={enabled} />
        ) : null}
        {section === "calendar" ? <LinkedInCalendarSection settings={overview?.settings} /> : null}
        {section === "published" ? <LinkedInPublishedSection /> : null}
        {section === "ideas" ? <LinkedInIdeasSection settings={overview?.settings} enabled={enabled} /> : null}
        {section === "settings" && overview ? (
          <LinkedInSettingsCard overview={overview} enabled={enabled} />
        ) : null}
      </div>
    </div>
  );
}
