import { useMemo } from "react";
import { useLinkedIn } from "../../hooks/useLinkedIn";
import { formatDateTimeHKT } from "../../lib/formatDisplay";
import { hookText, nextSlots, type LinkedInDraftSettings } from "../../lib/linkedinModel";

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
    <div className="card">
      <div className="card-body p-0">
        <table className="table table-sm admin-table-compact mb-0">
          <caption className="visually-hidden">LinkedIn slots</caption>
          <thead>
            <tr>
              <th scope="col">Slot</th>
              <th scope="col">Post</th>
            </tr>
          </thead>
          <tbody>
            {slots.length === 0 ? (
              <tr>
                <td colSpan={2} className="text-center py-4">No slots yet.</td>
              </tr>
            ) : (
              slots.map((slot) => {
                const match = (posts ?? []).find((row) => row.slotAt === slot && row.status !== "archived");
                return (
                  <tr key={slot}>
                    <td>{formatDateTimeHKT(slot)}</td>
                    <td>{match ? hookText(match.body) || statusLabel(match.status) : "Empty"}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function statusLabel(status: string): string {
  return status === "published" ? "Posted" : "Approved";
}
