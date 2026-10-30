import { useSearchParams } from "react-router-dom";
import { useResume } from "../../hooks/useResume";
import { AdminTabList, type AdminTabItem } from "../ui";
import { ResumeListSection } from "./ResumeListSection";
import { ResumeSettingsCard } from "./ResumeSettingsCard";
import { ResumeTailorSection } from "./ResumeTailorSection";
import { ResumeTrackerSection } from "./ResumeTrackerSection";

const SECTIONS = ["resumes", "tailor", "tracker", "settings"] as const;
type Section = (typeof SECTIONS)[number];

const TABS: readonly AdminTabItem<Section>[] = [
  { id: "resumes", label: "Resumes" },
  { id: "tailor", label: "New resume" },
  { id: "tracker", label: "Job tracker" },
  { id: "settings", label: "Settings" },
];

function sectionFrom(search: URLSearchParams): Section {
  const value = search.get("section");
  return SECTIONS.includes(value as Section) ? (value as Section) : "resumes";
}

export function ResumeTab() {
  const resume = useResume();
  const [params, setParams] = useSearchParams();
  const section = sectionFrom(params);
  const overview = resume.overview.data;
  const enabled = overview?.enabled ?? false;

  function setSection(id: Section) {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("tab", "resume");
        next.set("section", id);
        if (id !== "resumes") next.delete("resume");
        if (id !== "tracker") next.delete("application");
        return next;
      },
      { replace: true },
    );
  }

  return (
    <div>
      {resume.overview.isError ? (
        <p className="text-danger small">Could not load Resume. Check API configuration and sign-in.</p>
      ) : null}
      {overview && !enabled ? (
        <p className="text-muted small">Resume writes are off. You can still read what is stored.</p>
      ) : null}
      <AdminTabList
        tabs={TABS}
        active={section}
        onChange={setSection}
        label="Resume sections"
        idPrefix="resume"
        panelId="resume-panel"
      />
      <div className="tab-content" id="resume-panel" role="tabpanel">
        {section === "resumes" ? (
          <ResumeListSection enabled={enabled} templateResumeId={overview?.templateResumeId ?? ""} />
        ) : null}
        {section === "tailor" ? (
          <ResumeTailorSection
            enabled={enabled}
            templateResumeId={overview?.templateResumeId ?? ""}
            onOpenResume={(id) => {
              setParams(
                (current) => {
                  const next = new URLSearchParams(current);
                  next.set("tab", "resume");
                  next.set("section", "resumes");
                  next.set("resume", id);
                  next.delete("application");
                  return next;
                },
                { replace: true },
              );
            }}
          />
        ) : null}
        {section === "tracker" ? <ResumeTrackerSection enabled={enabled} /> : null}
        {section === "settings" && overview ? <ResumeSettingsCard overview={overview} enabled={enabled} /> : null}
      </div>
    </div>
  );
}
