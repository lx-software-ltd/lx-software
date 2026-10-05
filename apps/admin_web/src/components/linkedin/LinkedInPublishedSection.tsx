import { useLinkedIn } from "../../hooks/useLinkedIn";
import { formatDateTimeHKT } from "../../lib/formatDisplay";
import { hookText, postUrl } from "../../lib/linkedinModel";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableEmptyRow,
  AdminRecordTable,
  AdminRowActions,
} from "../ui";

const COLUMNS = [
  { key: "hook", header: "Hook" },
  { key: "posted", header: "Posted", priority: "secondary" as const },
  { key: "reach", header: "Reach", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
];

function reachText(metrics: { reactions: number; comments: number; impressions: number | null } | null | undefined): string {
  if (!metrics) return "—";
  const base = `${metrics.reactions} reactions · ${metrics.comments} comments`;
  return metrics.impressions == null ? base : `${base} · ${metrics.impressions} impressions`;
}

export function LinkedInPublishedSection() {
  const linkedIn = useLinkedIn();
  const posts = (linkedIn.posts.data?.items ?? []).filter((row) => row.status === "published");
  return (
    <AdminRecordTable label="Posted on LinkedIn">
      <AdminDataTable columns={COLUMNS} bare>
        {posts.length === 0 ? (
          <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="Nothing posted yet." />
        ) : (
          posts.map((row) => {
            const url = postUrl(row);
            const when = row.manual?.postedAt || row.platform?.publishedAt || row.updatedAt || "";
            return (
              <tr key={row.postId}>
                <AdminCell column="hook">
                  {hookText(row.body) || "Untitled"}
                </AdminCell>
                <AdminCell column="posted">{when ? formatDateTimeHKT(when) : "—"}</AdminCell>
                <AdminCell column="reach">{reachText(row.metrics)}</AdminCell>
                <AdminCell column="ops" className="text-end">
                  <AdminRowActions
                    actions={[
                      {
                        id: "open",
                        label: "Open on LinkedIn",
                        iconClassName: "bi-box-arrow-up-right",
                        hidden: !url,
                        onClick: () => window.open(url, "_blank", "noopener,noreferrer"),
                      },
                      {
                        id: "copy",
                        label: "Copy URL",
                        iconClassName: "bi-clipboard",
                        hidden: !url,
                        onClick: () => void navigator.clipboard.writeText(url),
                      },
                    ]}
                  />
                </AdminCell>
              </tr>
            );
          })
        )}
      </AdminDataTable>
    </AdminRecordTable>
  );
}
