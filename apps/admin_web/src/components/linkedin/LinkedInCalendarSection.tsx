import { useMemo } from "react";
import { useLinkedIn } from "../../hooks/useLinkedIn";
import { formatDateTimeHKT } from "../../lib/formatDisplay";
import { hookText, nextSlots, type LinkedInDraftSettings } from "../../lib/linkedinModel";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  AdminRecordTable,
} from "../ui";

const COLUMNS = [
  { key: "slot", header: "Slot" },
  { key: "post", header: "Post", priority: "secondary" as const },
];

export function LinkedInCalendarSection({ settings }: { readonly settings: LinkedInDraftSettings | undefined }) {
  const linkedIn = useLinkedIn();
  const posts = linkedIn.posts.data?.items;
  const slots = useMemo(() => {
    const rows = posts ?? [];
    if (!settings) return linkedIn.overview.data?.nextSlots ?? [];
    const taken = new Set(
      rows.filter((row) => row.status === "approved" || row.status === "published").map((row) => row.slotAt).filter(Boolean),
    );
    const upcoming = nextSlots(settings, new Date(), 12, taken);
    return [...taken, ...upcoming].sort();
  }, [linkedIn.overview.data?.nextSlots, posts, settings]);

  return (
    <AdminRecordTable label="LinkedIn slots">
      <AdminDataTable columns={COLUMNS} bare>
        {slots.length === 0 ? (
          <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No slots yet." />
        ) : (
          slots.map((slot) => {
            const match = (posts ?? []).find((row) => row.slotAt === slot && row.status !== "archived");
            const postText = match ? hookText(match.body) || statusLabel(match.status) : "Empty";
            return (
              <tr key={slot}>
                <AdminCell column="slot">
                  {formatDateTimeHKT(slot)}
                  <AdminDataTableCellMeta>{postText}</AdminDataTableCellMeta>
                </AdminCell>
                <AdminCell column="post">{postText}</AdminCell>
              </tr>
            );
          })
        )}
      </AdminDataTable>
    </AdminRecordTable>
  );
}

function statusLabel(status: string): string {
  return status === "published" ? "Posted" : "Approved";
}
